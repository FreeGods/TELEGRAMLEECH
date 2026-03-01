"""
Central Novel Downloader
Handles searching, downloading, and converting novels from centralnovel.com to EPUB format.

Uses:
  - httpx → requisições HTTP assíncronas
  - ebooklib → geração profissional de EPUB
  - regex → parsing de estrutura de volumes/capítulos
"""

import asyncio
import io
import os
import re
from collections import defaultdict
from typing import Optional

from httpx import AsyncClient as HttpxClient
from ebooklib import epub
from lxml import html as lxml_html


class CentralNovelDownloader:
    """Downloader para Central Novel com suporte a volumes e capítulos."""

    BASE_URL = "https://centralnovel.com"
    
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }

    def __init__(self, logger=None):
        self.logger = logger
        self.client = None

    async def _ensure_client(self):
        """Lazy initialization do cliente HTTP."""
        if self.client is None:
            self.client = HttpxClient(timeout=30, follow_redirects=True)

    async def close(self):
        """Fecha o cliente HTTP corretamente."""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def search(self, term: str) -> list[dict]:
        """
        Busca novels por termo no Central Novel.
        
        Retorna lista de dicts com keys: url, title
        """
        await self._ensure_client()
        
        try:
            resp = await self.client.get(
                self.BASE_URL,
                params={"s": term},
                headers=self.DEFAULT_HEADERS,
            )
            resp.raise_for_status()
        except Exception as e:
            self.logger and self.logger.error(f"CN search error: {e}")
            return []

        # Extrai links de séries
        pattern = rf'href=["\']({re.escape(self.BASE_URL)}/series/[^"\']+/)["\']'
        links = re.findall(pattern, resp.text)
        
        seen = set()
        results = []
        
        for link in links:
            if link in seen:
                continue
            seen.add(link)
            
            title = link.split("/series/")[-1].rstrip("/").replace("-", " ").title()
            results.append({"url": link, "title": title})
        
        return results

    async def list_volumes_and_chapters(self, novel_url: str) -> dict[int, list[dict]]:
        """
        Lista volumes e capítulos da novel.
        
        Retorna: {volume_numero: [{"numero": cap_num, "url": cap_url}, ...], ...}
        """
        await self._ensure_client()
        
        try:
            resp = await self.client.get(novel_url, headers=self.DEFAULT_HEADERS)
            resp.raise_for_status()
        except Exception as e:
            self.logger and self.logger.error(f"CN list volumes error: {e}")
            return {}

        # Extrai slug da URL
        slug = novel_url.split("/series/")[-1].rstrip("/")
        
        # Procura por padrão "Vol. X Cap. Y"
        pattern = r"Vol\.\s*(\d+)\s*Cap\.\s*(\d+)"
        matches = re.findall(pattern, resp.text, re.IGNORECASE)
        
        volumes = defaultdict(list)
        
        for vol_str, cap_str in matches:
            vol_num = int(vol_str)
            cap_num = int(cap_str)
            cap_url = f"{self.BASE_URL}/{slug}-capitulo-{cap_num}/"
            
            volumes[vol_num].append({
                "numero": cap_num,
                "url": cap_url,
            })
        
        # Ordena capítulos dentro de cada volume
        for vol_num in volumes:
            volumes[vol_num].sort(key=lambda c: c["numero"])
        
        return dict(sorted(volumes.items()))

    @staticmethod
    def _clean_paragraph(text: str) -> Optional[str]:
        """Remove lixo de parágrafos (comentários, login, etc)."""
        garbage_keywords = [
            "comentário", "inscrever", "login", "conectar", "discord",
            "concordo", "email", "nome*", "label", "inline feedbacks",
            "mais votado", "mais recente", "criar uma conta", "privacidade",
            "notificar", "botão de login", "compartilhadas pelo provedor",
        ]
        
        text_lower = text.lower()
        if any(kw in text_lower for kw in garbage_keywords):
            return None
        
        # Remove tags HTML
        clean = re.sub(r"<[^>]+>", "", text)
        clean = re.sub(r"&[a-z]+;", "", clean)
        
        if len(clean.strip()) < 10:
            return None
        
        if re.match(r"^[\s\W]*$", clean):
            return None
        
        return clean

    async def download_chapter(self, chapter_url: str) -> tuple[str, list[str]]:
        """
        Baixa conteúdo de um capítulo.
        
        Retorna: (html_content, lista_de_urls_de_imagem)
        """
        await self._ensure_client()
        
        try:
            resp = await self.client.get(chapter_url, headers=self.DEFAULT_HEADERS)
            resp.raise_for_status()
        except Exception as e:
            self.logger and self.logger.error(f"CN download chapter error: {e}")
            return "", []

        html_text = resp.text
        
        # Encontra entry-content
        entry_idx = html_text.find("entry-content")
        if entry_idx < 0:
            return "", []
        
        # Para antes dos comentários
        end_idx = html_text.find("wpd-thread-list", entry_idx)
        if end_idx < 0:
            end_idx = html_text.find("comment", entry_idx)
        if end_idx < 0:
            end_idx = entry_idx + 100000
        
        section = html_text[entry_idx:end_idx]
        
        # Extrai parágrafos
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", section, re.DOTALL)
        
        clean_paragraphs = []
        for p in paragraphs:
            cleaned = self._clean_paragraph(p)
            if cleaned:
                # Remove classes mas preserva formatação
                cleaned = re.sub(r' class=["\'][^"\']*["\']', "", cleaned)
                clean_paragraphs.append(f"<p>{cleaned}</p>")
        
        html_content = "\n".join(clean_paragraphs)
        
        # Extrai URLs de imagens
        images = re.findall(
            r'<img[^>]+src=["\']([^"\']+)["\']',
            html_content
        )
        images = [
            img for img in images
            if any(x in img for x in ["wp-content", "uploads", "centralnovel"])
        ]
        
        return html_content, images

    async def download_image(self, image_url: str) -> Optional[bytes]:
        """Baixa uma imagem e retorna bytes."""
        await self._ensure_client()
        
        try:
            resp = await self.client.get(image_url, headers=self.DEFAULT_HEADERS)
            resp.raise_for_status()
            return resp.content if len(resp.content) > 512 else None
        except Exception as e:
            self.logger and self.logger.warning(f"CN image download error: {e}")
            return None

    async def create_epub(
        self,
        title: str,
        author: str,
        volumes_data: dict[int, list[dict]],
        output_path: str,
    ) -> str:
        """
        Cria arquivo EPUB com estrutura de volumes.
        
        volumes_data: {vol_num: [{"numero": cap_num, "html": content, "imgs": urls}, ...], ...}
        
        Retorna: caminho do arquivo EPUB criado
        """
        # Cria o livro EPUB
        book = epub.EpubBook()
        book.set_id(f"cn-{re.sub(r'[^\\w]', '_', title)}")
        book.set_title(title)
        book.set_language("pt-BR")
        book.add_author(author)
        
        # CSS
        css_content = """
        @charset "UTF-8";
        body {
            font-family: "Georgia", "Palatino", "Times New Roman", serif;
            margin: 1.5em 1em;
            line-height: 1.8;
            color: #2c2c2c;
            font-size: 1.1em;
        }
        h1 {
            text-align: center;
            margin: 2.5em 0 2em 0;
            font-size: 2em;
            font-weight: bold;
            color: #1a1a1a;
            border-bottom: 2px solid #ccc;
            padding-bottom: 0.5em;
        }
        p {
            margin: 1em 0;
            text-align: justify;
            text-indent: 1.5em;
            word-spacing: normal;
            letter-spacing: 0.01em;
        }
        h1 + p { text-indent: 0; }
        em, i { font-style: italic; }
        strong, b { font-weight: bold; color: #1a1a1a; }
        img {
            max-width: 100%;
            height: auto;
            display: block;
            margin: 2em auto;
        }
        """
        
        css = epub.EpubItem()
        css.set_id("style")
        css.set_file_name("style.css")
        css.content = css_content.encode("utf-8")
        book.add_item(css)
        
        # Dicionário para mapear URLs de imagens para nomes de arquivo
        images_map = {}
        
        # Processa volumes e capítulos
        chapters = []
        toc_entries = []
        
        for vol_num in sorted(volumes_data.keys()):
            vol_chapters = volumes_data[vol_num]
            self.logger and self.logger.info(
                f"EPUB: Volume {vol_num}: {len(vol_chapters)} capítulos"
            )
            
            for cap_data in vol_chapters:
                cap_num = cap_data["numero"]
                html_content = cap_data["html"]
                img_urls = cap_data["imgs"]
                
                # Baixa e processa imagens
                for img_url in img_urls:
                    if img_url not in images_map:
                        img_bytes = await self.download_image(img_url)
                        if img_bytes:
                            ext = img_url.split(".")[-1].split("?")[0][:4]
                            img_name = f"img_{len(images_map)}.{ext}"
                            
                            img_item = epub.EpubItem()
                            img_item.set_id(f"img{len(images_map)}")
                            img_item.set_file_name(f"images/{img_name}")
                            img_item.content = img_bytes
                            book.add_item(img_item)
                            
                            images_map[img_url] = img_name
                
                # Substitui URLs de imagens pelo caminho local
                for old_url, new_name in images_map.items():
                    html_content = html_content.replace(
                        old_url,
                        f"./images/{new_name}"
                    )
                
                # Cria capítulo EPUB
                chapter = epub.EpubHtml()
                chapter.set_id(f"vol{vol_num}_cap{cap_num}")
                chapter.set_file_name(f"vol{vol_num}_cap{cap_num}.xhtml")
                chapter.set_language("pt-BR")
                
                chapter_html = f"""
                <html>
                <head>
                <meta charset="UTF-8"/>
                <title>Volume {vol_num} - Capítulo {cap_num}</title>
                <link rel="stylesheet" type="text/css" href="style.css"/>
                </head>
                <body>
                <h1>Volume {vol_num} - Capítulo {cap_num}</h1>
                {html_content}
                </body>
                </html>
                """
                
                chapter.content = chapter_html
                chapter.add_item(css)
                book.add_item(chapter)
                
                chapters.append(chapter)
                toc_entries.append((f"Vol {vol_num} Cap {cap_num}", chapter))
        
        # Adiciona TOC
        book.toc = toc_entries
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        
        # Define spine
        book.spine = ["nav"] + chapters
        
        # Salva EPUB
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        await asyncio.to_thread(epub.write_epub, output_path, book, {})
        
        return output_path

    def _extract_chapter_number(self, chapter_data: dict) -> float:
        """Extrai número do capítulo para suportar filtragem."""
        try:
            return float(chapter_data.get("numero", 0))
        except (ValueError, TypeError):
            return 0.0
