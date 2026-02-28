"""
Supabase Token Manager
Handles authentication token management for Anitsu (Supabase).

Token Types:
  - Access Token: Short-lived JWT (1 hour) for API requests
  - Refresh Token: Long-lived token to generate new access tokens

The system reads tokens from browser cookies (Netscape format) and automatically
renews them when they expire.

Cookie Format Expected:
  sb-[PROJECT_ID]-auth-token.0 → Part 1 of auth token
  sb-[PROJECT_ID]-auth-token.1 → Part 2 of auth token (continuation)
  
Inside the cookie value is a JSON object with:
  {
    "access_token": "eyJ...",
    "expires_in": 3600,
    "expires_at": 1771812360,
    "refresh_token": "huiwbche62qj",
    ...
  }
"""

import json
import re
import os
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from time import time

import httpx

from ...core.config_manager import Config
from ... import LOGGER


class SupabaseTokenManager:
    """Manages Supabase authentication tokens with automatic refresh."""
    
    # Pattern to find Supabase auth cookies
    SUPABASE_COOKIE_PATTERN = r"sb-([a-z0-9]+)-auth-token"
    
    def __init__(self, cookie_jar=None, db_handler=None, user_id=None):
        """
        Initialize token manager.
        
        Args:
            cookie_jar: http.cookiejar.MozillaCookieJar instance with loaded cookies
            db_handler: Optional DbManager instance for persisting renewed tokens
            user_id: Optional Telegram user ID for user-specific token persistence
        """
        self.cookie_jar = cookie_jar
        self.project_id: Optional[str] = None
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at: Optional[float] = None
        self.backend: Optional[str] = None
        self.db_handler = db_handler
        self.user_id = user_id
        
        if cookie_jar:
            self._extract_tokens_from_cookies()
    
    def _extract_tokens_from_cookies(self) -> bool:
        """
        Extract Supabase tokens from cookie jar.
        
        Supabase splits the auth token across multiple cookies because it's too large.
        We need to reconstruct it from parts.
        
        Returns:
            True if tokens were extracted successfully, False otherwise
        """
        if not self.cookie_jar:
            LOGGER.warning("[SupabaseTokenManager] No cookie jar provided")
            return False
        
        LOGGER.debug("[SupabaseTokenManager] Extraindo tokens dos cookies...")
        
        # Find all Supabase auth cookies
        auth_parts = {}
        project_ids = set()
        
        for cookie in self.cookie_jar:
            match = re.match(self.SUPABASE_COOKIE_PATTERN, cookie.name)
            if match:
                project_id = match.group(1)
                project_ids.add(project_id)
                
                # Extract part number (0, 1, etc.) from cookie name
                # Format: sb-[PROJECT_ID]-auth-token.[PART]
                part_match = re.search(r'\.(\d+)$', cookie.name)
                part_num = int(part_match.group(1)) if part_match else 0
                
                auth_parts[part_num] = cookie.value
                LOGGER.debug(f"[SupabaseTokenManager] Encontrado parte {part_num} do token Supabase")
        
        if not auth_parts:
            LOGGER.warning("[SupabaseTokenManager] Nenhum cookie de autenticação Supabase encontrado")
            return False
        
        if len(project_ids) > 1:
            LOGGER.warning(f"[SupabaseTokenManager] Múltiplos Project IDs encontrados: {project_ids}")
        
        self.project_id = list(project_ids)[0]
        LOGGER.info(f"[SupabaseTokenManager] Project ID Supabase: {self.project_id}")
        
        # Reconstruct full auth token from parts
        full_auth_token = "".join(auth_parts[i] for i in sorted(auth_parts.keys()))
        
        if not full_auth_token:
            LOGGER.error("[SupabaseTokenManager] Token de autenticação vazio após reconstrução")
            return False
        
        LOGGER.debug(f"[SupabaseTokenManager] Token reconstruído com {len(full_auth_token)} caracteres")
        
        # Decode base64 prefix if present (Supabase encodes the JSON as base64)
        import base64 as _b64

        if full_auth_token.startswith("base64-"):
            # strip prefix and add padding if needed
            full_auth_token = full_auth_token[len("base64-"):]
            padding = 4 - len(full_auth_token) % 4
            if padding != 4:
                full_auth_token += "=" * padding
            try:
                full_auth_token = _b64.b64decode(full_auth_token).decode("utf-8")
            except Exception as e:
                LOGGER.error(f"[SupabaseTokenManager] Erro ao decodificar base64: {e}")
                return False

        # Parse as JSON
        try:
            auth_data = json.loads(full_auth_token)
            LOGGER.debug(f"[SupabaseTokenManager] Auth data keys: {list(auth_data.keys())}")
        except json.JSONDecodeError as e:
            LOGGER.error(f"[SupabaseTokenManager] Erro ao decodificar JSON do token: {e}")
            LOGGER.debug(f"[SupabaseTokenManager] Token value: {full_auth_token[:100]}...")
            return False
        
        # Extract tokens
        self.access_token = auth_data.get("access_token")
        self.refresh_token = auth_data.get("refresh_token")
        self.expires_at = auth_data.get("expires_at")
        
        if not self.access_token or not self.refresh_token:
            LOGGER.error(
                f"[SupabaseTokenManager] Tokens incompletos - "
                f"access_token: {bool(self.access_token)}, "
                f"refresh_token: {bool(self.refresh_token)}"
            )
            return False
        
        # Set backend URL
        self.backend = f"https://{self.project_id}.supabase.co"
        
        # Log token info (sanitized)
        if self.expires_at:
            expires_in = self.expires_at - time()
            hours = expires_in / 3600
            LOGGER.info(
                f"[SupabaseTokenManager] ✅ Tokens extraídos com sucesso\n"
                f"    Project ID: {self.project_id}\n"
                f"    Access Token: {self.access_token[:20]}...\n"
                f"    Refresh Token: {self.refresh_token[:10]}...\n"
                f"    Expira em: {hours:.1f} horas ({datetime.fromtimestamp(self.expires_at)})"
            )
        else:
            LOGGER.warning("[SupabaseTokenManager] ⚠️ expires_at não encontrado no token")
        
        return True
    
    def is_token_valid(self, buffer_seconds: int = 300) -> bool:
        """
        Check if access token is still valid.
        
        Args:
            buffer_seconds: Refresh token this many seconds before actual expiration
                          (default: 5 minutes) to avoid race conditions
        
        Returns:
            True if token is valid, False if expired or not set
        """
        if not self.access_token or not self.expires_at:
            LOGGER.warning("[SupabaseTokenManager] Token não foi extraído dos cookies")
            return False
        
        current_time = time()
        time_until_expiry = self.expires_at - current_time
        
        if time_until_expiry < buffer_seconds:
            LOGGER.warning(
                f"[SupabaseTokenManager] Access token expirado ou prestes a expirar "
                f"({time_until_expiry:.0f}s até expiração)"
            )
            return False
        
        return True
    
    async def refresh_access_token(self) -> bool:
        """
        Refresh the access token using the refresh token.
        
        Makes a POST request to Supabase auth endpoint to get a new access token.
        Supabase invalidates the old refresh token and issues a new one.
        
        After successful refresh, saves tokens to MongoDB if db_handler is available.
        
        Returns:
            True if refresh was successful, False otherwise
        """
        if not self.refresh_token or not self.backend:
            LOGGER.error("[SupabaseTokenManager] Refresh token ou backend não configurado")
            return False
        
        LOGGER.info(f"[SupabaseTokenManager] 🔄 Renovando access token...")
        
        url = f"{self.backend}/auth/v1/token?grant_type=refresh_token"
        
        # Prepare request body
        payload = {
            "refresh_token": self.refresh_token
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                )
            
            LOGGER.debug(f"[SupabaseTokenManager] Refresh response status: {resp.status_code}")
            
            if resp.status_code not in [200, 201]:
                LOGGER.error(
                    f"[SupabaseTokenManager] ❌ Falha ao renovar token (HTTP {resp.status_code})\n"
                    f"    Response: {resp.text[:200]}"
                )
                return False
            
            # Parse response
            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                LOGGER.error(f"[SupabaseTokenManager] Erro ao decodificar resposta: {e}")
                return False
            
            # Update tokens
            old_access_token = self.access_token[:10]
            old_refresh_token = self.refresh_token[:10]
            
            self.access_token = data.get("access_token")
            self.refresh_token = data.get("refresh_token")
            self.expires_at = data.get("expires_at")
            expires_in = data.get("expires_in", 0)
            
            if not self.access_token or not self.refresh_token:
                LOGGER.error("[SupabaseTokenManager] ❌ Resposta de refresh incompleta")
                return False
            
            LOGGER.info(
                f"[SupabaseTokenManager] ✅ Tokens renovados com sucesso!\n"
                f"    Novo Access Token: {self.access_token[:20]}...\n"
                f"    Novo Refresh Token: {self.refresh_token[:10]}...\n"
                f"    Válido por: {expires_in} segundos"
            )
            
            # ✅ NOVA: Salvar tokens renovados no MongoDB
            if self.db_handler:
                tokens_data = self.to_dict()
                try:
                    if self.user_id:
                        # Salvar tokens específicos do usuário
                        await self.db_handler.save_anitsu_tokens(self.user_id, tokens_data)
                    else:
                        # Salvar tokens globais padrão
                        await self.db_handler.save_global_anitsu_tokens(tokens_data)
                    LOGGER.info("[SupabaseTokenManager] ✅ Tokens renovados salvos no MongoDB")
                except Exception as e:
                    LOGGER.warning(f"[SupabaseTokenManager] ⚠️ Não foi possível salvar tokens no MongoDB: {e}")
                    # Não falha a renovação se MongoDB estiver indisponível
            
            return True
        
        except httpx.RequestError as e:
            LOGGER.error(f"[SupabaseTokenManager] Erro de conexão ao renovar: {e}")
            return False
        except Exception as e:
            LOGGER.exception(f"[SupabaseTokenManager] Erro inesperado ao renovar: {e}")
            return False
    
    async def ensure_valid_token(self) -> bool:
        """
        Ensure we have a valid access token, refreshing if necessary.
        
        Returns:
            True if token is valid (either was already valid or refresh succeeded)
            False if token is invalid and refresh failed
        """
        if self.is_token_valid():
            return True
        
        LOGGER.info("[SupabaseTokenManager] Access token inválido, tentando renovar...")
        return await self.refresh_access_token()
    
    def get_authorization_header(self) -> Optional[str]:
        """
        Get the Authorization header value for API requests.
        
        Should only be called after ensuring token is valid.
        
        Returns:
            "Bearer <access_token>" for use in Authorization header, or None if no token
        """
        if not self.access_token:
            return None
        return f"Bearer {self.access_token}"
    
    def to_dict(self) -> Dict:
        """
        Export current tokens as dictionary (for persistence).
        
        Returns:
            Dict with access_token, refresh_token, expires_at
        """
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "project_id": self.project_id,
        }
    
    def from_dict(self, data: Dict) -> bool:
        """
        Restore tokens from dictionary.
        
        Args:
            data: Dictionary with access_token, refresh_token, expires_at
        
        Returns:
            True if tokens were loaded successfully
        """
        try:
            self.access_token = data.get("access_token")
            self.refresh_token = data.get("refresh_token")
            self.expires_at = data.get("expires_at")
            self.project_id = data.get("project_id")
            
            if not all([self.access_token, self.refresh_token, self.expires_at]):
                LOGGER.error("[SupabaseTokenManager] Dados de token incompletos")
                return False
            
            # Set backend URL from project_id
            if self.project_id:
                self.backend = f"https://{self.project_id}.supabase.co"
            
            LOGGER.info(f"[SupabaseTokenManager] Tokens restaurados do dicionário")
            return True
        except Exception as e:
            LOGGER.error(f"[SupabaseTokenManager] Erro ao restaurar tokens: {e}")
            return False
