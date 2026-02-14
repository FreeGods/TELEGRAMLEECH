#!/usr/bin/env python3
"""
Debug Nine Manga scraper to understand HTML structure
"""

import asyncio
import re
from httpx import AsyncClient


async def debug_ninemanga():
    """Debug NineMangaDownloader functionality"""
    
    BASE_URL = "https://br.ninemanga.com"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Upgrade-Insecure-Requests": "1",
    }
    
    print("Testing Nine Manga search...")
    print(f"URL: {BASE_URL}/search/")
    
    async with AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(
            f"{BASE_URL}/search/",
            params={"wd": "Kimetsu"},
            headers={**HEADERS, "Referer": f"{BASE_URL}/"},
        )
        
        print(f"Status: {response.status_code}")
        print(f"Content length: {len(response.text)}")
        
        # Print first 2000 chars
        print("\nFirst 2000 characters of response:")
        print(response.text[:2000])
        
        # Try to find any href patterns
        print("\n\nSearching for href patterns...")
        all_hrefs = re.findall(r'href=["\']([^"\']+)["\']', response.text)
        manga_hrefs = [h for h in all_hrefs if '/manga/' in h]
        
        print(f"Total hrefs: {len(all_hrefs)}")
        print(f"Manga hrefs: {len(manga_hrefs)}")
        
        if manga_hrefs:
            print("\nFirst 5 manga hrefs:")
            for href in manga_hrefs[:5]:
                print(f"  {href}")


if __name__ == "__main__":
    asyncio.run(debug_ninemanga())
