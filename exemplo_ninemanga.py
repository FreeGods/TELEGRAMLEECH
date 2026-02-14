#!/usr/bin/env python3
"""
Exemplo de uso da classe NineMangaDownloader
Demonstra como utilizar o downloader Nine Manga de forma standalone
"""

import asyncio
import logging
from bot.helper.ext_utils.ninemanga_utils import NineMangaDownloader

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def exemplo_busca_simples():
    """Exemplo 1: Buscar um mangá"""
    print("\n" + "="*60)
    print("EXEMPLO 1: Busca de Mangá")
    print("="*60)
    
    downloader = NineMangaDownloader(logger=logger)
    
    # Buscar por nome
    resultados = await downloader.search("Kimetsu no Yaiba")
    
    print(f"\nEncontrados {len(resultados)} resultados:")
    for i, manga in enumerate(resultados[:5], 1):
        print(f"{i}. {manga['title']}")
        print(f"   URL: {manga['url']}\n")
    
    return resultados[0] if resultados else None


async def exemplo_listar_capitulos(manga_url):
    """Exemplo 2: Listar capítulos de um mangá"""
    print("\n" + "="*60)
    print("EXEMPLO 2: Listar Capítulos")
    print("="*60)
    
    downloader = NineMangaDownloader(logger=logger)
    
    # Listar capítulos
    capitulos = await downloader.list_chapters(manga_url)
    
    print(f"\nTotal de capítulos: {len(capitulos)}")
    print("\nPrimeiros 5 capítulos:")
    for cap in capitulos[:5]:
        print(f"  Capítulo {cap['number']} (ID: {cap['id']})")
    
    if len(capitulos) > 5:
        print("  ...")
        print(f"\nÚltimos 2 capítulos:")
        for cap in capitulos[-2:]:
            print(f"  Capítulo {cap['number']} (ID: {cap['id']})")
    
    return capitulos


async def exemplo_info_manga(manga_url):
    """Exemplo 3: Obter informações do mangá"""
    print("\n" + "="*60)
    print("EXEMPLO 3: Informações do Mangá")
    print("="*60)
    
    downloader = NineMangaDownloader(logger=logger)
    
    # Obter informações
    info = await downloader.get_manga_info(manga_url)
    
    print(f"\nTítulo: {info.get('title', 'N/A')}")
    print(f"\nDescrição:")
    desc = info.get('description', 'N/A')
    print(f"  {desc[:200]}..." if len(desc) > 200 else f"  {desc}")
    
    if info.get('image'):
        print(f"\nCapa: {info['image']}")


async def exemplo_parsear_intervalo():
    """Exemplo 4: Parser de intervalo de capítulos"""
    print("\n" + "="*60)
    print("EXEMPLO 4: Parser de Intervalo")
    print("="*60)
    
    from bot.helper.ext_utils.mangaflower_utils import parse_chapter_range
    
    testes = [
        "1",
        "5-10",
        "1-5",
        "15.5-20.5",
        "todos"  # será None
    ]
    
    print("\nTestando parser de intervalo:")
    for teste in testes:
        start, end = parse_chapter_range(teste) if teste != "todos" else (None, None)
        print(f"  '{teste}' → início: {start}, fim: {end}")


async def exemplo_download_capitulo(capitulo_data, pasta_destino):
    """Exemplo 5: Baixar um capítulo"""
    print("\n" + "="*60)
    print("EXEMPLO 5: Download de Capítulo")
    print("="*60)
    
    downloader = NineMangaDownloader(logger=logger)
    
    print(f"\nBaixando capítulo {capitulo_data['number']}...")
    print(f"Para: {pasta_destino}")
    
    # Download
    cbz_path, paginas = await downloader.download_chapter(
        capitulo_data,
        pasta_destino
    )
    
    if cbz_path:
        print(f"\n✅ Sucesso!")
        print(f"  Arquivo: {cbz_path}")
        print(f"  Páginas: {paginas}")
    else:
        print(f"\n❌ Falha ao baixar")


async def exemplo_download_intervalo(manga_url, inicio, fim, pasta_destino):
    """Exemplo 6: Baixar intervalo de capítulos"""
    print("\n" + "="*60)
    print("EXEMPLO 6: Download de Intervalo")
    print("="*60)
    
    downloader = NineMangaDownloader(logger=logger)
    
    print(f"\nBaixando capítulos {inicio} a {fim}...")
    print(f"Para: {pasta_destino}")
    
    # Download de intervalo
    resultados = await downloader.download_range(
        manga_url,
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
    print("EXEMPLOS DE USO - NineMangaDownloader")
    print("="*60)
    
    try:
        # Exemplo 1: Buscar
        resultado_busca = await exemplo_busca_simples()
        
        if not resultado_busca:
            print("\n⚠️ Nenhum resultado encontrado. Abortando")
            return
        
        manga_url = resultado_busca['url']
        
        # Exemplo 2: Listar capítulos
        capitulos = await exemplo_listar_capitulos(manga_url)
        
        # Exemplo 3: Info
        await exemplo_info_manga(manga_url)
        
        # Exemplo 4: Parser
        await exemplo_parsear_intervalo()
        
        # Exemplo 5: Download único (comentado para não fazer download real)
        # await exemplo_download_capitulo(capitulos[0], "./manga_test")
        
        # Exemplo 6: Download intervalo (comentado)
        # await exemplo_download_intervalo(manga_url, 1, 5, "./manga_test")
        
        print("\n" + "="*60)
        print("✅ Todos os exemplos completados!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # IMPORTANTE: Se o site está bloqueando bots (Cloudflare),
    # você pode precisar de:
    # 1. Usar um IP residente (não de data center)
    # 2. Implementar suporte a JavaScript (Selenium/Playwright)
    # 3. Usar um serviço de proxy/API
    
    print("""
    ⚠️  NOTA IMPORTANTE:
    
    O site br.ninemanga.com utiliza proteção Cloudflare que pode
    bloquear requisições de bots e IPs de data centers.
    
    Este exemplo pode falhar se executado de:
    - Dev containers
    - Servidores em cloud
    - IPs associados a data centers
    
    Funcionará corretamente em:
    - Máquinas locais com IP residencial
    - Servidores com IPs residentes
    """)
    
    asyncio.run(main())
