#!/usr/bin/env python3
"""
Test script for Nine Manga integration
Tests the NineMangaDownloader class and its functionality
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.helper.ext_utils.ninemanga_utils import NineMangaDownloader


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
                    ch_num = chapter.get('number', 'N/A') if isinstance(chapter, dict) else 'N/A'
                    ch_url = chapter.get('url', chapter) if isinstance(chapter, dict) else chapter
                    print(f"  {i}. Chapter {ch_num} → {ch_url[:50]}...")
            else:
                print("⚠️ No chapters found")
        else:
            print("⚠️ Skipping chapters test - no results from search")
    except Exception as e:
        print(f"❌ Chapters listing failed: {e}")
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
                print(f"  Description: {info.get('description', 'N/A')[:100]}...")
            else:
                print("⚠️ Manga info is empty")
        else:
            print("⚠️ Skipping info test - no results from search")
    except Exception as e:
        print(f"❌ Manga info retrieval failed: {e}")
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
