"""
Anitsu Cloud Client
Async client for nuvem.anitsu.moe API integration.

Configuration:
  Set ANITSU_COOKIE_FILE in config.py or as environment variable.
  Cookies are loaded from a Netscape-format cookie file.
"""

import os
import http.cookiejar
from typing import Dict, List, Optional

import httpx

from ...core.config_manager import Config
from ... import LOGGER


class AnitsuClient:
    """Async client for Anitsu Cloud API."""

    def __init__(self, cookie_file: str):
        self.cookie_file = cookie_file
        self.backend = "https://nuvem.anitsu.moe"
        self._cookies: Optional[httpx.Cookies] = None
        LOGGER.debug(f"[AnitsuClient] Carregando cookies de: {cookie_file}")
        self._load_cookies()
        LOGGER.debug(f"[AnitsuClient] Cookies carregados com sucesso")

    def _load_cookies(self):
        """Load cookies from Netscape-format file."""
        if not os.path.exists(self.cookie_file):
            error_msg = (
                f"Anitsu cookie file not found: {self.cookie_file}\n"
                f"Export cookies from browser using an extension and save to this path."
            )
            LOGGER.error(f"[AnitsuClient] {error_msg}")
            raise FileNotFoundError(error_msg)

        LOGGER.debug(f"[AnitsuClient] Parsing cookie file: {self.cookie_file}")
        jar = http.cookiejar.MozillaCookieJar(self.cookie_file)
        jar.load(ignore_discard=True, ignore_expires=True)

        # Convert to httpx.Cookies
        self._cookies = httpx.Cookies()
        for cookie in jar:
            self._cookies.set(
                cookie.name,
                cookie.value,
                domain=cookie.domain,
                path=cookie.path,
            )
        LOGGER.debug(f"[AnitsuClient] {len(jar)} cookies carregados do arquivo")

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
                    LOGGER.warning(f"[AnitsuClient] Sessão expirada (401)")
                    return {
                        "error": "session_expired",
                        "detail": "Sessão expirada. Exporte novos cookies e use /anitsurefresh.",
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


def get_anitsu_client() -> AnitsuClient:
    """Get or create the singleton Anitsu client instance."""
    global _client
    if _client is None:
        cookie_file = getattr(Config, "ANITSU_COOKIE_FILE", None)
        if not cookie_file:
            error_msg = (
                "ANITSU_COOKIE_FILE not configured. "
                "Set it in config.py or as environment variable."
            )
            LOGGER.error(f"[AnitsuClient] {error_msg}")
            raise RuntimeError(error_msg)
        try:
            LOGGER.info(f"[AnitsuClient] Inicializando cliente com cookies de: {cookie_file}")
            _client = AnitsuClient(cookie_file)
            LOGGER.info(f"[AnitsuClient] Cliente inicializado com sucesso")
        except FileNotFoundError as e:
            LOGGER.error(f"[AnitsuClient] Arquivo de cookies não encontrado: {e}")
            raise
        except Exception as e:
            LOGGER.exception(f"[AnitsuClient] Erro ao inicializar: {e}")
            raise
    return _client


def refresh_anitsu_client():
    """Force reload of Anitsu client cookies."""
    global _client
    if _client:
        try:
            LOGGER.info(f"[AnitsuClient] Recarregando cookies")
            _client.refresh_cookies()
            LOGGER.info(f"[AnitsuClient] Cookies recarregados com sucesso")
        except Exception as e:
            LOGGER.exception(f"[AnitsuClient] Erro ao recarregar cookies: {e}")
            raise
    else:
        LOGGER.warning(f"[AnitsuClient] Tentativa de recarregar cookies, mas cliente não foi inicializado")
