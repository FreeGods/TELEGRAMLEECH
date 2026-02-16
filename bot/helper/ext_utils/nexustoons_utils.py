"""
Utility module for downloading manga from Nexus Toons (nexustoons.com)
Uses their JSON API for direct access to chapters and pages
"""

import re
import os
import asyncio
import zipfile
from time import time
from typing import Optional, List, Tuple, Dict
from httpx import AsyncClient
from aiofiles import open as aiofiles_open
from aiofiles.os import path as aiopath
from aiofiles.os import makedirs


class NexusToonsDownloader:
    """Handler for Nexus Toons manga downloads via API"""

    BASE_URL = "https://nexustoons.com"
    API_BASE = f"{BASE_URL}/api"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": f"{BASE_URL}/",
    }

    def __init__(self, logger=None):
        self.logger = logger
        self.delay = 0.3  # Delay between requests in seconds
        self.last_request_time = 0

    async def _apply_delay(self):
        """Apply delay to avoid detection"""
        elapsed = time() - self.last_request_time
        if elapsed < self.delay:
            await asyncio.sleep(self.delay - elapsed)
        self.last_request_time = time()

    def _extract_chapter_number(self, chapter_dict: Dict) -> float:
        """Extract chapter number from chapter dict for sorting"""
        if isinstance(chapter_dict, dict):
            return float(chapter_dict.get("number", 0))
        return 0

    async def search(self, termo: str) -> List[Dict]:
        """
        Search for manga by title using API
        
        Args:
            termo: Search term
            
        Returns:
            List of manga results with title, slug, and metadata
        """
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.API_BASE}/mangas",
                    params={"search": termo},
                    headers=self.HEADERS,
                )
                
                # Check response status
                response.raise_for_status()
                
                # Validate response is not empty
                if not response.text or not response.text.strip():
                    if self.logger:
                        self.logger.error("Empty response from Nexus Toons API")
                    return []
                
                # Parse JSON safely
                try:
                    data = response.json()
                except Exception as json_err:
                    if self.logger:
                        self.logger.error(f"Invalid JSON response from Nexus Toons: {json_err}")
                        self.logger.debug(f"Response text: {response.text[:200]}")
                    return []
                
                mangas = data.get("data", [])
                
                # Format results consistently
                results = []
                for manga in mangas:
                    if not isinstance(manga, dict):
                        continue
                    results.append({
                        "id": manga.get("id"),
                        "title": manga.get("title", ""),
                        "slug": manga.get("slug", ""),
                        "url": f"{self.BASE_URL}/manga/{manga.get('slug')}",
                        "chapterCount": manga.get("chapterCount", 0),
                        "cover": manga.get("cover", ""),
                    })
                
                return results
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error searching manga on Nexus Toons: {e}")
            return []

    async def list_chapters(self, manga_slug: str) -> List[Dict]:
        """
        List all available chapters for a manga
        
        Args:
            manga_slug: Manga slug (not the full URL)
            
        Returns:
            Sorted list of chapter dictionaries
        """
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.API_BASE}/mangas/{manga_slug}",
                    headers=self.HEADERS,
                )
                
                # Check response status
                response.raise_for_status()
                
                # Validate response is not empty
                if not response.text or not response.text.strip():
                    if self.logger:
                        self.logger.error(f"Empty response listing chapters for {manga_slug}")
                    return []
                
                # Parse JSON safely
                try:
                    data = response.json()
                except Exception as json_err:
                    if self.logger:
                        self.logger.error(f"Invalid JSON response listing chapters from Nexus Toons: {json_err}")
                        self.logger.debug(f"Response text: {response.text[:200]}")
                    return []
                
                chapters = data.get("chapters", [])
                
                # Validate chapters list
                if not isinstance(chapters, list):
                    if self.logger:
                        self.logger.warning(f"Expected list of chapters, got {type(chapters)}")
                    return []
                
                # Sort by chapter number
                chapters.sort(key=self._extract_chapter_number)
                return chapters
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error listing chapters from Nexus Toons: {e}")
            return []

    async def get_manga_info(self, manga_slug: str) -> Dict:
        """
        Extract manga information from API
        
        Args:
            manga_slug: Manga slug
            
        Returns:
            Dictionary with manga info (title, description, image, etc.)
        """
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.API_BASE}/mangas/{manga_slug}",
                    headers=self.HEADERS,
                )
                
                # Check response status
                response.raise_for_status()
                
                # Validate response is not empty
                if not response.text or not response.text.strip():
                    if self.logger:
                        self.logger.error(f"Empty response getting info for {manga_slug}")
                    return {}
                
                # Parse JSON safely
                try:
                    data = response.json()
                except Exception as json_err:
                    if self.logger:
                        self.logger.error(f"Invalid JSON response getting manga info from Nexus Toons: {json_err}")
                        self.logger.debug(f"Response text: {response.text[:200]}")
                    return {}
                
                return {
                    "title": data.get("title", "Unknown"),
                    "description": data.get("description", ""),
                    "image": data.get("cover", ""),
                    "url": f"{self.BASE_URL}/manga/{manga_slug}",
                    "slug": manga_slug,
                    "chapterCount": data.get("chapterCount", 0),
                }
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting manga info from Nexus Toons: {e}")
            return {}

    async def download_chapter(
        self, chapter_dict: Dict, pasta: str, cover_data: bytes = None
    ) -> Tuple[Optional[str], int]:
        """
        Download a single chapter as CBZ file.

        Args:
            chapter_dict: Chapter dictionary with 'id' and 'number' keys.
            pasta:        Download directory path.
            cover_data:   Optional raw bytes of the manga cover image.
                          Written as 000_cover.jpg inside the CBZ.

        Returns:
            Tuple of (filepath, page_count) or (None, 0) if failed.
        """
        try:
            if not isinstance(chapter_dict, dict):
                if self.logger:
                    self.logger.error(f"Invalid chapter data: {chapter_dict}")
                return None, 0
            
            chapter_id     = chapter_dict.get("id")
            chapter_number = chapter_dict.get("number", 0)
            
            if not chapter_id:
                if self.logger:
                    self.logger.error("Chapter ID not found in chapter data")
                return None, 0
            
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.API_BASE}/chapter/{chapter_id}",
                    headers=self.HEADERS,
                )

                data  = response.json()
                pages = data.get("pages", [])
                
                if not pages:
                    if self.logger:
                        self.logger.warning(f"No pages found in chapter {chapter_id}")
                    return None, 0

                # Create directory
                await makedirs(pasta, exist_ok=True)

                # Use zero-padded human-readable chapter number in filename
                try:
                    num_float = float(chapter_number)
                    if num_float == int(num_float):
                        nome = f"cap_{int(num_float):05d}"
                    else:
                        nome = f"cap_{num_float:08.1f}"
                except (ValueError, TypeError):
                    nome = f"cap_{chapter_number}"

                cbz_path = f"{pasta}/{nome}.cbz"

                img_headers = {
                    **self.HEADERS,
                    "Accept": "image/webp,image/*,*/*",
                }
                
                with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_STORED) as cbz:
                    # Inject cover image as first entry when available
                    if cover_data:
                        cbz.writestr("000_cover.jpg", cover_data)

                    async with AsyncClient(timeout=30) as img_client:
                        for page in sorted(pages, key=lambda p: int(p.get("pageNumber", 0))):
                            try:
                                page_num = page.get("pageNumber", 0)
                                img_url  = page.get("imageUrl", "").strip()
                                
                                if not img_url:
                                    continue
                                
                                await self._apply_delay()
                                img_response = await img_client.get(
                                    img_url,
                                    headers=img_headers,
                                    timeout=30,
                                )
                                
                                # Extract file extension
                                ext = img_url.split("?")[0].split(".")[-1].lower()
                                if not ext or len(ext) > 4:
                                    ext = "jpg"
                                
                                cbz.writestr(f"{page_num:03d}.{ext}", img_response.content)
                            except Exception as e:
                                if self.logger:
                                    self.logger.warning(
                                        f"Error downloading page {page.get('pageNumber')} from chapter {chapter_id}: {e}"
                                    )

                return cbz_path, len(pages)

        except Exception as e:
            if self.logger:
                self.logger.error(f"Error downloading chapter {chapter_dict}: {e}")
            return None, 0

    async def download_range(
        self, manga_slug: str, start: int, end: int, pasta: str
    ) -> List[Tuple[str, int]]:
        """
        Download a range of chapters
        
        Args:
            manga_slug: Manga slug
            start: Start chapter (inclusive)
            end: End chapter (inclusive)
            pasta: Download directory path
            
        Returns:
            List of (filepath, page_count) tuples
        """
        chapters = await self.list_chapters(manga_slug)
        if not chapters:
            return []

        # Filter chapters in range
        selected = [
            cap
            for cap in chapters
            if start <= self._extract_chapter_number(cap) <= end
        ]

        results = []
        for chapter_dict in selected:
            cbz_path, page_count = await self.download_chapter(
                chapter_dict, pasta
            )
            if cbz_path:
                results.append((cbz_path, page_count))

        return results
