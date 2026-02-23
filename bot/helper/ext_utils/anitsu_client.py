"""
Anitsu Cloud Client
Async client for nuvem.anitsu.moe API integration.

Configuration:
  Set ANITSU_COOKIE_FILE in config.py or as environment variable.
  Cookies are loaded from a Netscape-format cookie file.
  
  Priority order:
  1. Provided cookie_file parameter
  2. Config.ANITSU_COOKIE_FILE
  3. anitsu_cookies.txt (in current directory)
  4. anitsu_cookies (without extension)
  5. cookies.txt
"""

import os
import http.cookiejar
from typing import Dict, List, Optional

import httpx

from ...core.config_manager import Config
from ... import LOGGER


class AnitsuClient:
    """Async client for Anitsu Cloud API."""

    def __init__(self, cookie_file: Optional[str] = None):
        """
        Initialize Anitsu client with cookies.
        
        Args:
            cookie_file: Path to cookie file. If None, tries default locations.
        
        Raises:
            FileNotFoundError: If no valid cookie file is found.
            RuntimeError: If cookie file cannot be loaded.
        """
        self.cookie_file = None
        self.backend = "https://nuvem.anitsu.moe"
        self._cookies: Optional[httpx.Cookies] = None
        
        # Determine which cookie file to use
        self.cookie_file = self._find_cookie_file(cookie_file)
        
        if not self.cookie_file:
            error_msg = (
                "Anitsu cookie file not found. "
                "Set ANITSU_COOKIE_FILE in config.py or upload anitsu_cookies.txt via botset private."
            )
            LOGGER.error(f"[AnitsuClient] {error_msg}")
            raise FileNotFoundError(error_msg)
        
        LOGGER.debug(f"[AnitsuClient] Carregando cookies de: {self.cookie_file}")
        self._load_cookies()
        LOGGER.debug(f"[AnitsuClient] Cookies carregados com sucesso")
    
    def _find_cookie_file(self, provided_file: Optional[str] = None) -> Optional[str]:
        """
        Find a valid cookie file from multiple locations.
        
        Priority:
        1. Provided file parameter
        2. Config.ANITSU_COOKIE_FILE
        3. Default filenames (anitsu_cookies.txt, anitsu_cookies, cookies.txt)
        """
        candidates = []
        
        # 1. Provided file
        if provided_file:
            candidates.append(provided_file)
        
        # 2. Config setting
        config_file = getattr(Config, "ANITSU_COOKIE_FILE", None)
        if config_file and config_file.strip():
            candidates.append(config_file.strip())
        
        # 3. Default filenames
        candidates.extend([
            "anitsu_cookies.txt",
            "anitsu_cookies",
            "cookies.txt",
        ])
        
        # Try each candidate
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                LOGGER.debug(f"[AnitsuClient] Found cookie file: {candidate}")
                return candidate
        
        LOGGER.warning(f"[AnitsuClient] Nenhum arquivo de cookies encontrado. Candidates: {candidates}")
        return None

    
    def _load_cookies(self):
        """Load cookies from Netscape-format file."""
        if not self.cookie_file or not os.path.exists(self.cookie_file):
            error_msg = (
                f"Anitsu cookie file not found: {self.cookie_file}\n"
                f"Export cookies from browser using an extension and save to this path."
            )
            LOGGER.error(f"[AnitsuClient] {error_msg}")
            raise FileNotFoundError(error_msg)

        try:
            LOGGER.debug(f"[AnitsuClient] Parsing cookie file: {self.cookie_file}")
            jar = http.cookiejar.MozillaCookieJar(self.cookie_file)
            jar.load(ignore_discard=True, ignore_expires=True)

            # Convert to httpx.Cookies
            self._cookies = httpx.Cookies()
            # Also build a Cookie header string to force-send cookies when necessary
            cookie_pairs = []
            for cookie in jar:
                self._cookies.set(
                    cookie.name,
                    cookie.value,
                    domain=cookie.domain,
                    path=cookie.path,
                )
                try:
                    cookie_pairs.append(f"{cookie.name}={cookie.value}")
                except Exception:
                    continue
            self._cookie_header = "; ".join(cookie_pairs) if cookie_pairs else ""
            LOGGER.debug(f"[AnitsuClient] {len(jar)} cookies carregados do arquivo")
            
            if len(jar) == 0:
                LOGGER.warning(f"[AnitsuClient] Arquivo de cookies está vazio ou inválido")
        
        except Exception as e:
            LOGGER.error(f"[AnitsuClient] Erro ao carregar cookies: {e}")
            raise RuntimeError(f"Falha ao carregar cookies: {str(e)}")

    def refresh_cookies(self):
        """Reload cookies from file (use after exporting new cookies)."""
        self._load_cookies()

    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Internal GET request handler."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"{self.backend}/",
            "Accept": "application/json",
        }

        # If we built a Cookie header from the cookie file, include it to ensure
        # cookies are sent even when domain/path attributes would prevent it.
        if getattr(self, "_cookie_header", None):
            headers["Cookie"] = self._cookie_header

        LOGGER.debug(f"[AnitsuClient] GET {endpoint} com params: {params}")

        async with httpx.AsyncClient(cookies=self._cookies, timeout=30, follow_redirects=True) as client:
            try:
                resp = await client.get(
                    f"{self.backend}{endpoint}",
                    params=params,
                    headers=headers,
                )

                LOGGER.debug(f"[AnitsuClient] Status: {resp.status_code}")

                if resp.status_code == 401:
                    # Log response body to help debug why cookies are rejected
                    txt = None
                    try:
                        txt = resp.text
                    except Exception:
                        txt = "<no response body>"
                    LOGGER.warning(f"[AnitsuClient] Sessão expirada (401). Response: {txt}")
                    return {
                        "error": "session_expired",
                        "detail": "Sessão expirada. Exporte novos cookies e use /anitsurefresh.",
                        "response": txt,
                    }
                if resp.status_code == 404:
                    LOGGER.warning(f"[AnitsuClient] Não encontrado (404): {endpoint}")
                    return {"error": "not_found", "detail": "Caminho não encontrado."}

                resp.raise_for_status()
                data = resp.json()
                LOGGER.debug(f"[AnitsuClient] Resposta JSON: {str(data)[:200]}")
                return data

            except httpx.HTTPStatusError as e:
                LOGGER.error(f"[AnitsuClient] Erro HTTP {e.response.status_code}: {e}")
                return {"error": "http_error", "detail": f"HTTP {e.response.status_code}"}
            except httpx.RequestError as e:
                LOGGER.error(f"[AnitsuClient] Erro de requisição: {e}")
                return {"error": "request_failed", "detail": str(e)}
            except Exception as e:
                LOGGER.exception(f"[AnitsuClient] Erro desconhecido em _get: {e}")
                return {"error": "unknown", "detail": str(e)}

    async def search(self, query: str) -> Dict:
        """
        Search for anime by name.

        Returns:
            {"query": str, "results": [{"name": str, "path": str}, ...]}
            or {"error": str, "detail": str} on failure.
        """
        LOGGER.info(f"[AnitsuClient] Buscando por: {query}")
        result = await self._get("/api/search", {"q": query})
        if "error" in result:
            LOGGER.error(f"[AnitsuClient] Erro na busca: {result.get('detail')}")
        else:
            LOGGER.info(f"[AnitsuClient] Busca retornou {len(result.get('results', []))} resultados")
        return result

    async def list_files(self, path: str = "") -> Dict:
        """
        List files and folders at a given path.

        Returns:
            {
                "path": str,
                "parent": str | null,
                "files": [
                    {
                        "name": str,
                        "is_directory": bool,
                        "size": int,
                        "modified": str (ISO),
                        "extension": str | null
                    },
                    ...
                ]
            }
            or {"error": str, "detail": str} on failure.
        """
        LOGGER.info(f"[AnitsuClient] Listando arquivos em: {path or '/'}")
        result = await self._get("/api/files", {"path": path})
        if "error" in result:
            LOGGER.error(f"[AnitsuClient] Erro ao listar {path}: {result.get('detail')}")
        else:
            files_count = len(result.get('files', []))
            LOGGER.info(f"[AnitsuClient] Caminho {path} retornou {files_count} itens")
        return result

    def download_url(self, path: str) -> str:
        """
        Generate direct download URL for a file.

        Args:
            path: Full file path (e.g., "Animes/Letra N/Naruto/episode.mkv")

        Returns:
            Direct download URL with authentication cookies embedded.
        """
        # URL encoding handled by httpx internally when used with session
        import urllib.parse
        return f"{self.backend}/api/download?path={urllib.parse.quote(path)}"

    def get_download_info(self, path: str) -> Dict:
        """
        Get file metadata without downloading (async wrapper for HEAD request).

        Returns:
            {
                "url": str,
                "size": int,
                "content_type": str,
                "filename": str,
                "ok": bool
            }
            or {"ok": False, "error": str} on failure.
        """
        # This is a sync method — convert to async if needed, or call from executor
        # For now, returning a dict that can be awaited externally
        url = self.download_url(path)
        return {
            "url": url,
            "size": 0,  # placeholder — actual size fetched on download
            "filename": os.path.basename(path),
            "ok": True,
        }


# ─────────────────────────────────────────────
# Singleton instance
# ─────────────────────────────────────────────
_client: Optional[AnitsuClient] = None
_client_lock = None  # Will be set to asyncio.Lock if needed


def get_anitsu_client(cookie_file: Optional[str] = None) -> AnitsuClient:
    """
    Get or create the Anitsu client instance.
    
    Args:
        cookie_file: Optional path to cookie file. If provided, creates/returns client with that file.
        
    Returns:
        AnitsuClient instance
        
    Raises:
        FileNotFoundError: If no valid cookie file is found
        RuntimeError: If client cannot be initialized
    """
    global _client
    
    # If a specific cookie_file is provided, always create a new instance
    if cookie_file:
        try:
            LOGGER.debug(f"[AnitsuClient] Criando novo cliente com cookies de: {cookie_file}")
            return AnitsuClient(cookie_file)
        except Exception as e:
            LOGGER.error(f"[AnitsuClient] Erro ao criar cliente com arquivo {cookie_file}: {e}")
            raise
    
    # Otherwise, use singleton
    if _client is None:
        try:
            LOGGER.info(f"[AnitsuClient] Inicializando cliente Anitsu singleton")
            _client = AnitsuClient()
            LOGGER.info(f"[AnitsuClient] Cliente inicializado com sucesso de: {_client.cookie_file}")
        except FileNotFoundError as e:
            LOGGER.error(f"[AnitsuClient] Arquivo de cookies não encontrado: {e}")
            raise
        except Exception as e:
            LOGGER.exception(f"[AnitsuClient] Erro ao inicializar: {e}")
            raise
    
    return _client


def refresh_anitsu_client(cookie_file: Optional[str] = None):
    """
    Force reload of Anitsu client cookies.
    
    Args:
        cookie_file: Optional new cookie file path
    """
    global _client
    try:
        if cookie_file:
            LOGGER.info(f"[AnitsuClient] Recarregando cookies de novo arquivo: {cookie_file}")
            _client = AnitsuClient(cookie_file)
        elif _client:
            LOGGER.info(f"[AnitsuClient] Recarregando cookies do arquivo atual: {_client.cookie_file}")
            _client.refresh_cookies()
        else:
            LOGGER.warning(f"[AnitsuClient] Tentativa de recarregar cookies, mas cliente não foi inicializado")
            _client = AnitsuClient()
        LOGGER.info(f"[AnitsuClient] Cookies recarregados com sucesso")
    except Exception as e:
        LOGGER.exception(f"[AnitsuClient] Erro ao recarregar cookies: {e}")
        raise



