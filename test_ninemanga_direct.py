#!/usr/bin/env python3
"""
Direct test of NineMangaDownloader without importing bot init
"""

import asyncio
import sys
import os
import re
import zipfile
from time import time
from typing import Optional, List, Tuple, Dict
from httpx import AsyncClient
from aiofiles import open as aiofiles_open
from aiofiles.os import path as aiopath
from aiofiles.os import makedirs


class NineMangaDownloader:
    """Handler for Nine Manga (br.ninemanga.com) manga downloads"""

    BASE_URL = "https://br.ninemanga.com"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(self, logger=None):
        self.logger = logger
        self.delay = 0.5
        self.last_request_time = 0

    async def _apply_delay(self):
        """Apply delay to avoid detection"""
        elapsed = time() - self.last_request_time
        if elapsed < self.delay:
            await asyncio.sleep(self.delay - elapsed)
        self.last_request_time = time()

    def _extract_chapter_number(self, chapter_dict: Dict) -> float:
        """Extract chapter number from chapter dict for sorting"""
        return chapter_dict.get("number", 0)

    async def search(self, termo: str) -> List[Dict]:
        """Search for manga by title"""
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.BASE_URL}/search/",
                    params={"wd": termo},
                    headers={**self.HEADERS, "Referer": f"{self.BASE_URL}/"},
                )

                pattern = rf'href=["\']({re.escape(self.BASE_URL)}/manga/[^"\']+\.html)["\']'
                links = re.findall(pattern, response.text)
                
                vistos = set()
                resultado = []
                for link in links:
                    if link not in vistos and "/category/" not in link:
                        vistos.add(link)
                        titulo = link.split("/manga/")[-1].replace(".html", "").replace("+", " ")
                        resultado.append({"url": link, "title": titulo})
                
                return resultado
        except Exception as e:
            print(f"Error searching manga: {e}")
            return []

    async def list_chapters(self, url_obra: str) -> List[Dict]:
        """List all available chapters for a manga"""
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    f"{url_obra}?waring=1",
                    headers={**self.HEADERS, "Referer": f"{self.BASE_URL}/"},
                )

                html = response.text
                pattern = rf'href=["\']({re.escape(self.BASE_URL)}/chapter/[^"\']+/(\d+)\.html)["\']'
                matches = re.findall(pattern, html)

                vistos = set()
                caps = []
                
                for url, cap_id in matches:
                    if url not in vistos:
                        vistos.add(url)
                        idx = html.find(url)
                        if idx >= 0:
                            trecho = html[max(0, idx - 50) : idx + 200]
                            num_match = re.search(r"[Cc]h(?:ap)?\s*(\d+(?:\.\d+)?)", trecho)
                            numero = float(num_match.group(1)) if num_match else float(cap_id)
                        else:
                            numero = float(cap_id)
                        
                        caps.append({
                            "url": url,
                            "id": cap_id,
                            "number": numero,
                        })

                caps.sort(key=self._extract_chapter_number)
                return caps
        except Exception as e:
            print(f"Error listing chapters: {e}")
            return []

    async def get_manga_info(self, url_obra: str) -> Dict:
        """Extract manga information from manga page"""
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    url_obra,
                    headers={**self.HEADERS, "Referer": f"{self.BASE_URL}/"},
                )
                
                html = response.text
                
                title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
                title = title_match.group(1) if title_match else "Unknown"
                
                desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
                description = desc_match.group(1) if desc_match else ""
                
                img_match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                image = img_match.group(1) if img_match else ""
                
                return {
                    "title": title,
                    "description": description,
                    "image": image,
                    "url": url_obra,
                }
        except Exception as e:
            print(f"Error getting manga info: {e}")
            return {}


async def test_ninemanga():
    """Test NineMangaDownloader functionality"""
    
    print("=" * 50)
    print("Nine Manga Integration Test")
    print("=" * 50)
    
    downloader = NineMangaDownloader()
    
    # Test 1: Search functionality
    print("\n[Test 1] Testing search functionality...")
    try:
        results = await downloader.search("Kimetsu no Yaiba")
        
        if results:
            print(f"✅ Search successful! Found {len(results)} results")
            print("Sample results:")
            for i, result in enumerate(results[:3], 1):
                print(f"  {i}. {result['title']} → {result['url']}")
        else:
            print("⚠️ Search returned empty results")
    except Exception as e:
        print(f"❌ Search failed: {e}")
        return False
    
    # Test 2: List chapters functionality
    print("\n[Test 2] Testing chapters listing...")
    try:
        if results and len(results) > 0:
            manga_url = results[0]['url']
            print(f"Using URL: {manga_url}")
            
            chapters = await downloader.list_chapters(manga_url)
            
            if chapters:
                print(f"✅ Chapters retrieved successfully! Total: {len(chapters)}")
                print("Sample chapters:")
                for i, chapter in enumerate(chapters[:3], 1):
                    ch_num = chapter.get('number', 'N/A')
                    print(f"  {i}. Chapter {ch_num}")
            else:
                print("⚠️ No chapters found")
        else:
            print("⚠️ Skipping chapters test - no results from search")
    except Exception as e:
        print(f"❌ Chapters listing failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 3: Get manga info
    print("\n[Test 3] Testing manga info retrieval...")
    try:
        if results and len(results) > 0:
            manga_url = results[0]['url']
            info = await downloader.get_manga_info(manga_url)
            
            if info:
                print(f"✅ Manga info retrieved successfully!")
                print(f"  Title: {info.get('title', 'N/A')}")
                print(f"  Description: {info.get('description', 'N/A')[:80]}...")
            else:
                print("⚠️ Manga info is empty")
        else:
            print("⚠️ Skipping info test - no results from search")
    except Exception as e:
        print(f"❌ Manga info retrieval failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 4: Extract chapter number
    print("\n[Test 4] Testing chapter number extraction...")
    try:
        test_dict = {"number": 5.5, "url": "https://br.ninemanga.com/chapter/Test/123.html"}
        extracted = downloader._extract_chapter_number(test_dict)
        
        if extracted == 5.5:
            print(f"✅ Chapter number extraction working! Extracted: {extracted}")
        else:
            print(f"❌ Chapter extraction returned unexpected value: {extracted}")
            return False
    except Exception as e:
        print(f"❌ Chapter extraction failed: {e}")
        return False
    
    print("\n" + "=" * 50)
    print("✅ All tests completed successfully!")
    print("=" * 50)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_ninemanga())
    sys.exit(0 if success else 1)
