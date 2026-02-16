"""
Utility module for downloading manga from Nine Manga (br.ninemanga.com)
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
        self.delay = 0.5  # Delay between requests in seconds
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
        """
        Search for manga by title
        
        Args:
            termo: Search term
            
        Returns:
            List of manga results with title and url
        """
        try:
            await self._apply_delay()
            
            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    f"{self.BASE_URL}/search/",
                    params={"wd": termo},
                    headers={**self.HEADERS, "Referer": f"{self.BASE_URL}/"},
                )

                # Extract manga links
                pattern = rf'href=["\']({re.escape(self.BASE_URL)}/manga/[^"\']+\.html)["\']'
                links = re.findall(pattern, response.text)
                
                # Remove duplicates
                vistos = set()
                resultado = []
                for link in links:
                    if link not in vistos and "/category/" not in link:
                        vistos.add(link)
                        # Extract title from URL
                        titulo = link.split("/manga/")[-1].replace(".html", "").replace("+", " ")
                        resultado.append({"url": link, "title": titulo})
                
                return resultado
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error searching manga: {e}")
            return []

    async def list_chapters(self, url_obra: str) -> List[str]:
        """
        List all available chapters for a manga.

        NineManga HTML structure (confirmed by debug):
          <li>
            <div class="chapter-name long"><a href="URL">ONE PIECE 1167 </a></div>
            <div class="chapter-name short"><a href="URL">Ch 1167</a></div>
            ...
          </li>

        Special case: chapter "000" has " 000" in short name (no "Ch" prefix).
        We extract the number from the surrounding <li> block to avoid
        using the internal cap_id (e.g. 6869768) as the chapter number.
        """
        try:
            await self._apply_delay()

            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    f"{url_obra}?waring=1",
                    headers={**self.HEADERS, "Referer": f"{self.BASE_URL}/"},
                )

                html = response.text

                # ── Step 1: Extract all <li> blocks that contain chapter links ──
                # Each <li> in NineManga wraps exactly one chapter entry.
                # We use a broad pattern to grab the whole <li>...</li> block.
                chapter_url_pat = re.compile(
                    rf'href=["\']({re.escape(self.BASE_URL)}/chapter/[^"\']+/(\d+)\.html)["\']'
                )

                # Split HTML into <li> segments to get proper per-chapter context
                li_blocks = re.findall(r'<li\b[^>]*>.*?</li>', html, re.S | re.I)

                vistos = set()
                caps   = []

                for block in li_blocks:
                    url_match = chapter_url_pat.search(block)
                    if not url_match:
                        continue

                    url    = url_match.group(1)
                    cap_id = url_match.group(2)

                    if url in vistos:
                        continue
                    vistos.add(url)

                    numero = None

                    # ── Extract chapter number from the <li> block ─────────────
                    # Priority 1: "chapter-name short" div  →  "Ch 1167" or " 000"
                    short_m = re.search(
                        r'class=["\']chapter-name\s+short["\'][^>]*>.*?<a[^>]*>\s*(.*?)\s*</a>',
                        block, re.S | re.I
                    )
                    if short_m:
                        short_text = re.sub(r'<[^>]+>', '', short_m.group(1)).strip()
                        # Matches "Ch 1167", "Ch 0", " 000", "1167", "1167.5"
                        num_m = re.search(r'(?:[Cc]h\s*)?(\d+(?:\.\d+)?)', short_text)
                        if num_m:
                            candidate = float(num_m.group(1))
                            if candidate < 10000:
                                numero = candidate

                    # Priority 2: "chapter-name long" div  →  "ONE PIECE 1167"
                    if numero is None:
                        long_m = re.search(
                            r'class=["\']chapter-name\s+long["\'][^>]*>.*?<a[^>]*>\s*(.*?)\s*</a>',
                            block, re.S | re.I
                        )
                        if long_m:
                            long_text = re.sub(r'<[^>]+>', '', long_m.group(1)).strip()
                            # Last number in the text: "ONE PIECE 1167 " → 1167
                            num_m = re.findall(r'(\d+(?:\.\d+)?)', long_text)
                            if num_m:
                                candidate = float(num_m[-1])
                                if candidate < 10000:
                                    numero = candidate

                    # Priority 3: any "Ch NNN" pattern anywhere in the block
                    if numero is None:
                        ch_m = re.search(
                            r'[Cc]h(?:ap(?:ter|ítulo)?)?\s*\.?\s*(\d+(?:\.\d+)?)', block
                        )
                        if ch_m:
                            candidate = float(ch_m.group(1))
                            if candidate < 10000:
                                numero = candidate

                    # Priority 4: URL path segment before the ID
                    # e.g. /chapter/one-piece-1100/6833501.html → 1100
                    if numero is None:
                        url_num = re.search(r'-(\d+(?:\.\d+)?)(?:/\d+\.html)$', url)
                        if url_num:
                            candidate = float(url_num.group(1))
                            if candidate < 10000:
                                numero = candidate

                    # Absolute fallback: raw cap_id (wrong, but won't crash)
                    if numero is None:
                        numero = float(cap_id)
                        if self.logger:
                            self.logger.warning(
                                f"NineManga: could not extract chapter number for {url}, "
                                f"using raw ID {cap_id}"
                            )

                    caps.append({"url": url, "id": cap_id, "number": numero})

                # Sort ascending by chapter number
                caps.sort(key=self._extract_chapter_number)
                return caps

        except Exception as e:
            if self.logger:
                self.logger.error(f"Error listing chapters: {e}")
            return []

    async def get_manga_info(self, url_obra: str, hint_title: str = "") -> Dict:
        """
        Extract manga information from manga page.

        The NineManga site does NOT use og:title / og:description meta tags.
        We use a cascade of fallbacks to find the title:
          1. <h1> inside the manga detail section
          2. <title> tag (cleaned up)
          3. hint_title passed by the caller (from search results, free)
          4. Title derived from the URL itself

        Args:
            url_obra:   Manga URL.
            hint_title: Optional title already known from search results.
                        Used as a high-quality fallback without an extra request.

        Returns:
            Dictionary with manga info (title, description, image, url).
        """
        try:
            await self._apply_delay()

            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    f"{url_obra}?waring=1",
                    headers={**self.HEADERS, "Referer": f"{self.BASE_URL}/"},
                )

                html = response.text

                # ── Title: cascade of fallbacks ───────────────────────────
                title = ""

                # 1) og:title (may exist on some mirror domains)
                m = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', html)
                if m:
                    title = m.group(1).strip()

                # 2) <h1> — NineManga puts <b> tags inside h1, so strip inner tags
                #    HTML: <h1><b>One Piece Manga</b></h1>
                if not title:
                    for pat in (
                        r'<h1[^>]*itemprop=["\']name["\'][^>]*>(.*?)</h1>',
                        r'<h1[^>]*class=["\'][^"\']*manga[^"\']*["\'][^>]*>(.*?)</h1>',
                        r'<h1[^>]*>(.*?)</h1>',
                    ):
                        m = re.search(pat, html, re.I | re.S)
                        if m:
                            # Strip any inner HTML tags (e.g. <b>, <span>)
                            inner = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                            if inner and inner.lower() not in ("ninemanga", "nine manga", "mangás"):
                                # Remove trailing " Manga" suffix if present to get clean title
                                # "One Piece Manga" → "One Piece"  but keep if title IS just one word
                                cleaned = re.sub(r'\s+[Mm]anga$', '', inner).strip()
                                title = cleaned if cleaned else inner
                                break

                # 3) <title> tag — strip site suffix
                if not title:
                    m = re.search(r'<title>([^<]+)</title>', html, re.I)
                    if m:
                        raw = m.group(1).strip()
                        # Remove "- Ler Online Mangás Livre - Nine Manga" type suffixes
                        raw = re.sub(r'\s*[-|–]\s*(?:Ler\s+Online|Nine\s*Manga|Mangás?\s+Livre).*$', '', raw, flags=re.I).strip()
                        # Remove "Manga brasil, ONE PIECE NNNN" noise — keep first meaningful segment
                        raw = re.sub(r',.*$', '', raw).strip()
                        raw = re.sub(r'\s+[Mm]anga\s+brasil.*$', '', raw).strip()
                        raw = re.sub(r'\s+[Mm]anga$', '', raw).strip()
                        if raw and len(raw) > 2:
                            title = raw

                # 4) Caller-supplied hint from search results (already clean)
                if not title and hint_title:
                    title = hint_title.strip()

                # 5) Derive from URL: /manga/One+Piece.html → "One Piece"
                if not title:
                    url_part = re.search(r'/manga/([^/?#]+)', url_obra)
                    if url_part:
                        title = url_part.group(1).replace("+", " ").replace("-", " ").replace(".html", "").title()

                title = title or "Unknown"

                # ── Description ───────────────────────────────────────────
                description = ""
                for pat in (
                    r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)["\']',
                    r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
                    r'<p[^>]*class=["\'][^"\']*summary[^"\']*["\'][^>]*>([^<]{20,})</p>',
                ):
                    m = re.search(pat, html, re.I)
                    if m:
                        description = m.group(1).strip()
                        break

                # ── Cover image ───────────────────────────────────────────
                image = ""
                for pat in (
                    r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                    r'<img[^>]*itemprop=["\']image["\']\s+src=["\']([^"\']+)["\']',
                    r'<img[^>]*class=["\'][^"\']*cover[^"\']*["\'][^>]*src=["\']([^"\']+)["\']',
                    # Typical NineManga cover pattern: img inside .manga_detail_top
                    r'class=["\'][^"\']*detail[^"\']*["\'][^>]*>.*?<img[^>]+src=["\']([^"\']+\.(?:jpg|jpeg|png|webp))["\']',
                ):
                    m = re.search(pat, html, re.I | re.S)
                    if m:
                        candidate = m.group(1).strip()
                        if candidate.startswith("http"):
                            image = candidate
                            break

                return {
                    "title": title,
                    "description": description,
                    "image": image,
                    "url": url_obra,
                }
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error getting manga info: {e}")
            # Return partial info using what we know from the URL / hint
            fallback_title = hint_title or ""
            if not fallback_title:
                url_part = re.search(r'/manga/([^/?#]+)', url_obra)
                if url_part:
                    fallback_title = url_part.group(1).replace("+", " ").replace("-", " ").replace(".html", "").title()
            return {"title": fallback_title or "Unknown", "description": "", "image": "", "url": url_obra}

    async def download_chapter(
        self, chapter_dict: Dict, pasta: str, cover_data: bytes = None
    ) -> Tuple[Optional[str], int]:
        """
        Download a single chapter as CBZ file.

        Args:
            chapter_dict: Chapter dictionary with 'url', 'id', and 'number' keys.
            pasta:        Download directory path.
            cover_data:   Optional raw bytes of the manga cover image.
                          If provided, it is written as 000_cover.jpg at the start
                          of every CBZ so that readers display the correct cover.

        Returns:
            Tuple of (filepath, page_count) or (None, 0) if failed.
        """
        try:
            if not isinstance(chapter_dict, dict):
                # Handle string URLs for backward compatibility
                url_cap = chapter_dict
                cap_id = re.search(r'/(\d+)\.html$', url_cap)
                cap_id = cap_id.group(1) if cap_id else "0"
                cap_number = cap_id   # no number info available
            else:
                url_cap    = chapter_dict.get("url")
                cap_id     = chapter_dict.get("id", "0")
                # Prefer the human-readable chapter number over the raw site ID
                cap_number = chapter_dict.get("number", cap_id)

            await self._apply_delay()
            
            images = []
            url_atual = url_cap
            pagina = 1
            max_paginas = 200

            async with AsyncClient(timeout=30, follow_redirects=True) as client:
                while url_atual and pagina <= max_paginas:
                    response = await client.get(
                        url_atual,
                        headers={**self.HEADERS, "Referer": f"{self.BASE_URL}/"},
                    )
                    html = response.text

                    # Extract image URLs
                    imgs = re.findall(
                        r'src=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']',
                        html,
                        re.I
                    )
                    
                    # Filter for real image CDNs
                    imgs_reais = [
                        i for i in imgs
                        if any(x in i for x in ["wpimg", "niadd", "pic", "yx247", "cdn"])
                    ]
                    
                    if imgs_reais:
                        images.append(imgs_reais[0])
                    else:
                        break

                    # Find next page
                    next_match = re.search(r'next_page\s*=\s*["\']([^"\']+)["\']', html)
                    if not next_match:
                        break
                    
                    next_path = next_match.group(1)
                    
                    # Validate that next page is part of same chapter
                    cap_id_match = re.search(r'/(\d+)(?:-\d+)?(?:\.html)?$', url_cap)
                    if cap_id_match and cap_id_match.group(1) in next_path and re.search(
                        r'-\d+(?:\.html)?$', next_path
                    ):
                        url_atual = (
                            f"{self.BASE_URL}{next_path}"
                            if next_path.startswith("/")
                            else next_path
                        )
                        pagina += 1
                    else:
                        break

            if not images:
                if self.logger:
                    self.logger.warning(f"No images found in {url_cap}")
                return None, 0

            # Create directory
            await makedirs(pasta, exist_ok=True)

            # Use the human-readable chapter number in the filename
            # Format: cap_0001100.0  →  zero-padded to 7 digits so filenames sort correctly
            try:
                num_float = float(cap_number)
                # Integer chapters → "cap_01100", decimal → "cap_01100.5"
                if num_float == int(num_float):
                    nome = f"cap_{int(num_float):05d}"
                else:
                    nome = f"cap_{num_float:08.1f}"
            except (ValueError, TypeError):
                nome = f"cap_{cap_number}"

            cbz_path = f"{pasta}/{nome}.cbz"

            img_headers = {**self.HEADERS, "Referer": f"{self.BASE_URL}/", "Accept": "image/webp,image/*,*/*"}
            
            with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_STORED) as cbz:
                # Inject cover image as first entry when available
                if cover_data:
                    cbz.writestr("000_cover.jpg", cover_data)

                async with AsyncClient(timeout=30) as client:
                    for i, img_url in enumerate(images, 1):
                        try:
                            await self._apply_delay()
                            img_response = await client.get(
                                img_url.strip(),
                                headers=img_headers,
                                timeout=30,
                            )
                            
                            # Extract file extension
                            ext = img_url.split("?")[0].split(".")[-1].lower()
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
                self.logger.error(f"Error downloading chapter {chapter_dict}: {e}")
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
        for chapter_dict in selected:
            cbz_path, page_count = await self.download_chapter(
                chapter_dict, pasta
            )
            if cbz_path:
                results.append((cbz_path, page_count))

        return results
