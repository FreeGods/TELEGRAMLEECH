#!/usr/bin/env python3
"""
Exemplo de uso da classe NexusToonsDownloader
Demonstra como utilizar o downloader Nexus Toons de forma standalone
"""

import asyncio
import logging
from bot.helper.ext_utils.nexustoons_utils import NexusToonsDownloader

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def exemplo_busca_simples():
    """Exemplo 1: Buscar um mangá"""
    print("\n" + "="*60)
    print("EXEMPLO 1: Busca de Mangá")
    print("="*60)
    
    downloader = NexusToonsDownloader(logger=logger)
    
    # Buscar por nome
    resultados = await downloader.search("Solo Leveling")
    
    print(f"\nEncontrados {len(resultados)} resultados:")
    for i, manga in enumerate(resultados[:5], 1):
        print(f"{i}. {manga['title']}")
        print(f"   Slug: {manga['slug']}")
        print(f"   Capítulos: {manga['chapterCount']}\n")
    
    return resultados[0] if resultados else None


async def exemplo_listar_capitulos(manga_slug):
    """Exemplo 2: Listar capítulos de um mangá"""
    print("\n" + "="*60)
    print("EXEMPLO 2: Listar Capítulos")
    print("="*60)
    
    downloader = NexusToonsDownloader(logger=logger)
    
    # Listar capítulos
    capitulos = await downloader.list_chapters(manga_slug)
    
    print(f"\nSlug: {manga_slug}")
    print(f"Total de capítulos: {len(capitulos)}")
    print("\nPrimeiros 5 capítulos:")
    for cap in capitulos[:5]:
        print(f"  Capítulo {cap['number']} (ID: {cap['id']})")
    
    if len(capitulos) > 5:
        print("  ...")
        print(f"\nÚltimos 2 capítulos:")
        for cap in capitulos[-2:]:
            print(f"  Capítulo {cap['number']} (ID: {cap['id']})")
    
    return capitulos


async def exemplo_info_manga(manga_slug):
    """Exemplo 3: Obter informações do mangá"""
    print("\n" + "="*60)
    print("EXEMPLO 3: Informações do Mangá")
    print("="*60)
    
    downloader = NexusToonsDownloader(logger=logger)
    
    # Obter informações
    info = await downloader.get_manga_info(manga_slug)
    
    print(f"\nTítulo: {info.get('title', 'N/A')}")
    print(f"Slug: {info.get('slug', 'N/A')}")
    print(f"Capítulos: {info.get('chapterCount', 'N/A')}")
    print(f"\nDescrição:")
    desc = info.get('description', 'N/A')
    print(f"  {desc[:200]}..." if len(desc) > 200 else f"  {desc}")
    
    if info.get('image'):
        print(f"\nCapa: {info['image'][:80]}...")


async def exemplo_api_endpoints():
    """Exemplo 4: Entendendo os endpoints da API"""
    print("\n" + "="*60)
    print("EXEMPLO 4: Endpoints da API Nexus Toons")
    print("="*60)
    
    print("""
    Endpoints disponíveis:

    1. Buscar Mangás:
       GET /api/mangas?search=termo
       Retorna: lista de mangas com id, title, slug, chapterCount, cover

    2. Obter Info do Mangá:
       GET /api/mangas/{slug}
       Retorna: detalhes do mangá incluindo lista de capítulos

    3. Obter Capítulo:
       GET /api/chapter/{chapter_id}
       Retorna: detalhes do capítulo com lista de páginas

    Exemplo de resposta de capítulo:
    {
        "id": "123",
        "number": 1.0,
        "title": "Chapter 1",
        "pages": [
            {
                "pageNumber": 1,
                "imageUrl": "https://..."
            },
            ...
        ]
    }
    """)


async def exemplo_download_capitulo(chapter_data, pasta_destino):
    """Exemplo 5: Baixar um capítulo"""
    print("\n" + "="*60)
    print("EXEMPLO 5: Download de Capítulo")
    print("="*60)
    
    downloader = NexusToonsDownloader(logger=logger)
    
    print(f"\nBaixando capítulo {chapter_data['number']}...")
    print(f"Para: {pasta_destino}")
    
    # Download
    cbz_path, paginas = await downloader.download_chapter(
        chapter_data,
        pasta_destino
    )
    
    if cbz_path:
        print(f"\n✅ Sucesso!")
        print(f"  Arquivo: {cbz_path}")
        print(f"  Páginas: {paginas}")
    else:
        print(f"\n❌ Falha ao baixar")


async def exemplo_download_intervalo(manga_slug, inicio, fim, pasta_destino):
    """Exemplo 6: Baixar intervalo de capítulos"""
    print("\n" + "="*60)
    print("EXEMPLO 6: Download de Intervalo")
    print("="*60)
    
    downloader = NexusToonsDownloader(logger=logger)
    
    print(f"\nBaixando capítulos {inicio} a {fim}...")
    print(f"Manga: {manga_slug}")
    print(f"Para: {pasta_destino}")
    
    # Download de intervalo
    resultados = await downloader.download_range(
        manga_slug,
        start=inicio,
        end=fim,
        pasta=pasta_destino
    )
    
    if resultados:
        print(f"\n✅ {len(resultados)} capítulos baixados com sucesso:")
        total_paginas = 0
        for caminho, paginas in resultados:
            print(f"  {caminho}: {paginas} páginas")
            total_paginas += paginas
        print(f"\nTotal: {total_paginas} páginas")
    else:
        print(f"\n❌ Falha ao baixar")


async def main():
    """Executar exemplos"""
    print("\n" + "="*60)
    print("EXEMPLOS DE USO - NexusToonsDownloader")
    print("="*60)
    
    try:
        # Exemplo 1: Buscar
        resultado_busca = await exemplo_busca_simples()
        
        if not resultado_busca:
            print("\n⚠️ Nenhum resultado encontrado. Abortando")
            return
        
        manga_slug = resultado_busca['slug']
        
        # Exemplo 2: Listar capítulos
        capitulos = await exemplo_listar_capitulos(manga_slug)
        
        # Exemplo 3: Info
        await exemplo_info_manga(manga_slug)
        
        # Exemplo 4: Endpoints
        await exemplo_api_endpoints()
        
        # Exemplo 5: Download único (comentado para não fazer download real)
        # await exemplo_download_capitulo(capitulos[0], "./manga_test")
        
        # Exemplo 6: Download intervalo (comentado)
        # await exemplo_download_intervalo(manga_slug, 1, 5, "./manga_test")
        
        print("\n" + "="*60)
        print("✅ Todos os exemplos completados!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("""
    ℹ️  INFORMAÇÕES:
    
    Nexus Toons usa uma API JSON pública, então o acesso é mais
    confiável comparado a sites com proteção Cloudflare.
    
    Exemplo de slug: "solo-leveling", "tower-of-god", etc
    
    Você pode encontrar slugs em:
    - URLs: https://nexustoons.com/manga/{slug}
    - Resultados de busca
    """)
    
    asyncio.run(main())
