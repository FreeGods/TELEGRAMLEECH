#!/usr/bin/env python3
"""
Debug Nine Manga with better headers and cookies
"""

import asyncio
import re
from httpx import AsyncClient, Client


async def debug_with_better_headers():
    """Try better headers"""
    
    BASE_URL = "https://br.ninemanga.com"
    
    # Better headers with more details
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache"
    }
    
    print("Testing with better headers...")
    print(f"User-Agent: {HEADERS['User-Agent'][:50]}...")
    
    async with AsyncClient(timeout=30, follow_redirects=True) as client:
        try:
            # First, try to access the homepage to establish cookies
            print("\n1. Accessing homepage...")
            home_response = await client.get(
                BASE_URL,
                headers=HEADERS,
            )
            print(f"   Status: {home_response.status_code}")
            
            # Try search
            print("\n2. Attempting search...")
            response = await client.get(
                f"{BASE_URL}/search/",
                params={"wd": "Kimetsu"},
                headers={**HEADERS, "Referer": BASE_URL},
            )
            
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                # Find all links
                all_hrefs = re.findall(r'href=["\']([^"\']+)["\']', response.text)
                manga_hrefs = [h for h in all_hrefs if '/manga/' in h and h.startswith('http')]
                
                print(f"   Found {len(manga_hrefs)} manga links")
                
                if manga_hrefs:
                    print("\n   Sample manga links:")
                    for href in manga_hrefs[:5]:
                        print(f"     {href}")
                    return True
                else:
                    print("\n   Sample of response (first 1500 chars):")
                    print(response.text[:1500])
            else:
                print(f"   Error: Got status code {response.status_code}")
                if "cloudflare" in response.text.lower() or "blocked" in response.text.lower():
                    print("   Site is using Cloudflare protection")
        except Exception as e:
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
    
    return False


if __name__ == "__main__":
    success = asyncio.run(debug_with_better_headers())
    if success:
        print("\n✅ Success!")
    else:
        print("\n❌ Failed - may need to handle Cloudflare or other protections")
