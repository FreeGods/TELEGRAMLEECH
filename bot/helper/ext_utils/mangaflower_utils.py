"""
Utility module for downloading manga from Flower Mangas (flowermangas.net)
Supports both search and direct link methods
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


class MangaFlowerDownloader:
    """Handler for Flower Mangas manga downloads"""

    BASE_URL = "https://flowermangas.net"
    AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36"
    }

    def __init__(self, logger=None):
        self.logger = logger
        self.delay = 1.0  # Delay between requests in seconds
        self.last_request_time = 0

    async def _apply_delay(self):
        """Apply delay to avoid detection"""
        elapsed = time() - self.last_request_time
        if elapsed < self.delay:
            await asyncio.sleep(self.delay - elapsed)
        self.last_request_time = time()

    async def search(self, termo: str) -> List[Dict]:
        """
        Search for manga by title
        
        Args:
            termo: Search term
            
        Returns:
            List of manga results with title and url
        """
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30) as client:
                response = await client.post(
                    self.AJAX_URL,
                    data={"action": "wp-manga-search-manga", "title": termo},
                    headers={**self.HEADERS, "X-Requested-With": "XMLHttpRequest"},
                )

                data = response.json()
                if data.get("success"):
                    results = data.get("data", [])
                    # Transform results to ensure consistent format
                    return [
                        {
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "image": r.get("image", ""),
                        }
                        for r in results
                    ]
                return []
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error searching manga: {e}")
            return []

    @staticmethod
    def _extract_chapter_number(url: str) -> float:
        """Extract chapter number from URL for sorting"""
        match = re.search(r"capitulo-(\d+(?:\.\d+)?)", url)
        return float(match.group(1)) if match else 0

    async def list_chapters(self, url_obra: str) -> List[str]:
        """
        List all available chapters for a manga
        
        Args:
            url_obra: Manga URL
            
        Returns:
            Sorted list of chapter URLs
        """
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(url_obra, headers=self.HEADERS)

                slug = url_obra.rstrip("/").split("/")[-1]
                padrao = rf'href="(https://flowermangas\.net/manga/{slug}/capitulo-[^"]+/)"'
                caps = re.findall(padrao, response.text)

                # Remove duplicates while preserving order
                vistos = set()
                unicos = []
                for c in caps:
                    if c not in vistos:
                        vistos.add(c)
                        unicos.append(c)

                # Sort by chapter number
                unicos.sort(key=self._extract_chapter_number)
                return unicos
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error listing chapters: {e}")
            return []

    async def get_manga_info(self, url_obra: str) -> Dict:
        """
        Extract manga information from manga page
        
        Args:
            url_obra: Manga URL
            
        Returns:
            Dictionary with manga info (title, description, image, etc.)
        """
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(url_obra, headers=self.HEADERS)
                
                # Extract title
                title_match = re.search(r'<meta property="og:title" content="([^"]+)"', response.text)
                title = title_match.group(1) if title_match else "Unknown"
                
                # Extract description
                desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', response.text)
                description = desc_match.group(1) if desc_match else ""
                
                # Extract image
                img_match = re.search(r'<meta property="og:image" content="([^"]+)"', response.text)
                image = img_match.group(1) if img_match else ""
                
                return {
                    "title": title,
                    "description": description,
                    "image": image,
                    "url": url_obra,
                }
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting manga info: {e}")
            return {}

    async def download_chapter(
        self, url_cap: str, pasta: str
    ) -> Tuple[Optional[str], int]:
        """
        Download a single chapter as CBZ file
        
        Args:
            url_cap: Chapter URL
            pasta: Download directory path
            
        Returns:
            Tuple of (filepath, page_count) or (None, 0) if failed
        """
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(url_cap, headers=self.HEADERS)

                # Try multiple patterns to find images
                images = re.findall(
                    r'wp-manga-chapter-img[^>]*src="\s*(https?://[^\"\s]+)',
                    response.text,
                )
                if not images:
                    images = re.findall(
                        r'src="\s*(https?://cdn\.flowermng\.com/[^\"\s]+\.(?:jpg|png|webp))',
                        response.text,
                    )

                if not images:
                    if self.logger:
                        self.logger.warning(f"No images found in {url_cap}")
                    return None, 0

                # Create directory
                await makedirs(pasta, exist_ok=True)

                # Extract chapter name
                nome_cap = url_cap.rstrip("/").split("/")[-1]
                cbz_path = f"{pasta}/{nome_cap}.cbz"

                # Download images and create CBZ
                with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_STORED) as cbz:
                    for i, img_url in enumerate(images, 1):
                        await self._apply_delay()
                        try:
                            img_response = await client.get(
                                img_url.strip(),
                                timeout=30,
                                headers={**self.HEADERS, "Referer": url_cap},
                            )
                            
                            # Extract extension
                            ext = img_url.split(".")[-1].split("?")[0]
                            if not ext or len(ext) > 4:
                                ext = "jpg"
                            
                            cbz.writestr(f"{i:03d}.{ext}", img_response.content)
                        except Exception as e:
                            if self.logger:
                                self.logger.warning(
                                    f"Error downloading image {i} from {url_cap}: {e}"
                                )

                return cbz_path, len(images)

        except Exception as e:
            if self.logger:
                self.logger.error(f"Error downloading chapter {url_cap}: {e}")
            return None, 0

    async def download_range(
        self, url_obra: str, start: int, end: int, pasta: str
    ) -> List[Tuple[str, int]]:
        """
        Download a range of chapters
        
        Args:
            url_obra: Manga URL
            start: Start chapter (inclusive)
            end: End chapter (inclusive)
            pasta: Download directory path
            
        Returns:
            List of (filepath, page_count) tuples
        """
        chapters = await self.list_chapters(url_obra)
        if not chapters:
            return []

        # Filter chapters in range
        selected = [
            cap
            for cap in chapters
            if start <= self._extract_chapter_number(cap) <= end
        ]

        results = []
        for chapter_url in selected:
            cbz_path, page_count = await self.download_chapter(
                chapter_url, pasta
            )
            if cbz_path:
                results.append((cbz_path, page_count))

        return results


def parse_chapter_range(input_str: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse chapter range input (e.g., "12-22" or "5")
    
    Args:
        input_str: Range string
        
    Returns:
        Tuple of (start, end) chapter numbers or (None, None) if invalid
    """
    try:
        if "-" in input_str:
            parts = input_str.split("-")
            if len(parts) != 2:
                return None, None
            start = float(parts[0].strip())
            end = float(parts[1].strip())
            if start <= end:
                return start, end
            return None, None
        else:
            num = float(input_str.strip())
            return num, num
    except ValueError:
        return None, None
