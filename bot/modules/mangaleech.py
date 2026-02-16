"""
Manga Leech Command Module
Handles /mangaleech command with source selection, search, chapter range downloads.

Integrations:
  - Flag -z  → empacota todos os CBZs num único ZIP antes de enviar
  - Paginação → lista de mangás com setas ◀ ▶ quando > PAGE_SIZE resultados
  - Voltar    → botão ↩ em todas as fases (source → mode → search/link → chapters)
  - Anti-ghost → callbacks de mensagens antigas ignorados silenciosamente
  - Re-search → ao digitar numa fase de espera de texto, nova pesquisa sem reiniciar
"""

import asyncio
import io
import os
import re
import shutil
import zipfile
from time import time

from httpx import AsyncClient as HttpxClient
from pyrogram.filters import command, regex
from pyrogram.handlers import CallbackQueryHandler, MessageHandler

from .. import DOWNLOAD_DIR, LOGGER
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.mangaflower_utils import (
    MangaFlowerDownloader,
    parse_chapter_range,
)
from ..helper.ext_utils.ninemanga_utils import NineMangaDownloader
from ..helper.ext_utils.nexustoons_utils import NexusToonsDownloader
from ..helper.ext_utils.status_utils import (
    get_readable_file_size,
    get_progress_bar_string,
)
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    edit_message,
    send_message,
    send_file,
)
from ..helper.telegram_helper.bot_commands import BotCommands
from aiofiles.os import path as aiopath, remove as aio_remove

# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────
PAGE_SIZE = 8          # resultados por página na lista de mangás
SESSION_TTL = 600      # segundos antes de uma sessão expirar (10 min)

# ─────────────────────────────────────────────
# Estado global das sessões por usuário
# Estrutura de cada entrada:
#   stage          : str  – fase atual do fluxo
#   source         : str  – "flower" | "nine" | "nexus"
#   mode           : str  – "link" | "search"
#   downloader     : objeto downloader
#   selected_url   : str  – URL/slug do mangá escolhido
#   chapters       : list – lista de capítulos
#   search_results : list – últimos resultados de busca
#   page           : int  – página atual na lista de resultados
#   active_msg_id  : int  – id da mensagem de controle ativa
#   last_active    : float– timestamp da última interação
#   use_zip        : bool – empacotar em ZIP antes de enviar
# ─────────────────────────────────────────────
manga_user_state: dict[int, dict] = {}


# ──────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────

def _touch(user_id: int):
    """Atualiza timestamp da sessão."""
    if user_id in manga_user_state:
        manga_user_state[user_id]["last_active"] = time()


def _is_active_msg(user_id: int, message_id: int) -> bool:
    """
    Verifica se o callback vem da mensagem de controle atual.

    NOTA: desativado — quando o usuário digita texto, o bot cria uma *nova*
    mensagem ("Pesquisando…") cujo ID é diferente da mensagem anterior de botões.
    O active_msg_id fica defasado e bloquearia callbacks legítimos.
    A proteção por user_id (caller_id == cb_user_id) já é suficiente.
    """
    return True


def _clear(user_id: int):
    manga_user_state.pop(user_id, None)


def _make_source(source_key: str, logger=None):
    if source_key == "nine":
        return NineMangaDownloader(logger=logger)
    if source_key == "nexus":
        return NexusToonsDownloader(logger=logger)
    return MangaFlowerDownloader(logger=logger)


def _chapter_number(downloader, chapter_data) -> float:
    """Extrai número de capítulo de forma segura para qualquer fonte."""
    try:
        return downloader._extract_chapter_number(chapter_data)
    except Exception:
        return 0.0


async def _cleanup_dir(path: str):
    try:
        if await aiopath.exists(path):
            await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)
    except Exception as e:
        LOGGER.warning(f"Manga cleanup warning: {e}")


def _safe_filename(title: str) -> str:
    """Converte o título do mangá num nome de arquivo seguro para qualquer SO."""
    # Remove caracteres inválidos em nomes de arquivo, mantém letras, dígitos, espaço, hífen
    safe = re.sub(r'[^\w\s\-]', '', title, flags=re.UNICODE).strip()
    # Compacta espaços múltiplos e substitui por underline
    safe = re.sub(r'\s+', '_', safe)
    return safe[:50] or "manga"


async def _fetch_cover(image_url: str) -> bytes | None:
    """
    Baixa a imagem de capa do mangá e retorna os bytes brutos.
    Retorna None em caso de falha para não interromper o download dos capítulos.
    """
    if not image_url or not image_url.startswith("http"):
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
            "Accept": "image/webp,image/*,*/*",
        }
        async with HttpxClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(image_url, headers=headers)
            if resp.status_code == 200 and len(resp.content) > 1024:
                return resp.content
    except Exception as e:
        LOGGER.warning(f"Manga cover fetch failed ({image_url}): {e}")
    return None


# ──────────────────────────────────────────────
# Construção de menus
# ──────────────────────────────────────────────

def _source_menu(user_id: int) -> tuple:
    b = ButtonMaker()
    b.data_button("🌸 Flower Mangas", f"mng:{user_id}:src:flower")
    b.data_button("🔥 Nine Manga",    f"mng:{user_id}:src:nine")
    b.data_button("🌐 Nexus Toons",   f"mng:{user_id}:src:nexus")
    b.data_button("❌ Cancelar",      f"mng:{user_id}:cancel")
    return "📚 <b>Escolha a fonte de mangá:</b>", b.build_menu(1)


def _mode_menu(user_id: int) -> tuple:
    b = ButtonMaker()
    b.data_button("🔗 Link direto", f"mng:{user_id}:mode:link")
    b.data_button("🔍 Pesquisar",   f"mng:{user_id}:mode:search")
    b.data_button("↩ Voltar",       f"mng:{user_id}:back:source")
    b.data_button("❌ Cancelar",    f"mng:{user_id}:cancel")
    return "🎯 <b>Como deseja adicionar o mangá?</b>", b.build_menu(2)


def _results_menu(user_id: int, results: list, page: int) -> tuple:
    """Monta menu paginado de resultados de busca."""
    start = page * PAGE_SIZE
    end   = start + PAGE_SIZE
    page_results = results[start:end]
    total_pages  = max(1, -(-len(results) // PAGE_SIZE))   # ceil division

    b = ButtonMaker()
    for i, r in enumerate(page_results):
        title = r.get("title", "Sem título")[:50]
        b.data_button(title, f"mng:{user_id}:pick:{start + i}")

    # Linha de paginação
    nav = []
    if page > 0:
        nav.append(("◀", f"mng:{user_id}:page:{page - 1}"))
    nav.append((f"{page + 1}/{total_pages}", f"mng:{user_id}:noop"))
    if end < len(results):
        nav.append(("▶", f"mng:{user_id}:page:{page + 1}"))
    for label, data in nav:
        b.data_button(label, data, position="l_body")

    b.data_button("🔍 Nova busca",   f"mng:{user_id}:newsearch", position="footer")
    b.data_button("↩ Voltar",        f"mng:{user_id}:back:mode", position="footer")
    b.data_button("❌ Cancelar",     f"mng:{user_id}:cancel", position="footer")

    msg = f"🔎 <b>Resultados</b> ({len(results)} encontrados):\nPágina {page + 1}/{total_pages}"
    return msg, b.build_menu(1, lb_cols=len(nav), f_cols=3)


def _chapters_menu(user_id: int, info: dict, chapters: list, source: str) -> str:
    try:
        if source in ("nine", "nexus"):
            first = chapters[0].get("number", 1) if isinstance(chapters[0], dict) else 1
            last  = chapters[-1].get("number", len(chapters)) if isinstance(chapters[-1], dict) else len(chapters)
        else:
            def _cap_n(c):
                m = re.search(r"capitulo-(\d+(?:\.\d+)?)", str(c))
                return m.group(1) if m else "?"
            first = _cap_n(chapters[0])
            last  = _cap_n(chapters[-1])
    except Exception:
        first, last = 1, len(chapters)

    msg  = f"📖 <b>{info.get('title', 'Desconhecido')}</b>\n\n"
    msg += f"📊 <b>Total de capítulos:</b> {len(chapters)}\n"
    msg += f"📍 <b>Do capítulo</b> {first} <b>ao</b> {last}\n"
    if info.get("description"):
        desc = info["description"][:200]
        msg += f"\n📝 {desc}{'…' if len(info['description']) > 200 else ''}\n"
    msg += "\n📌 <b>Digite o intervalo de capítulos:</b>"
    msg += "\n<i>Exemplos: 1-5 · 10 · 15-20 · todos</i>"
    if manga_user_state.get(user_id, {}).get("use_zip"):
        msg += "\n\n🗜️ <i>Modo ZIP ativado: os capítulos serão enviados num único arquivo.</i>"
    return msg


# ──────────────────────────────────────────────
# Comando principal
# ──────────────────────────────────────────────

@new_task
async def mangaleech(client, message):
    """Ponto de entrada do /mangaleech [-z]"""
    user = message.from_user
    if not user:
        return
    user_id = user.id

    # Detecta flag -z (compactar em ZIP)
    args = message.text.split() if message.text else []
    use_zip = "-z" in args

    # Cancela sessão anterior se houver
    _clear(user_id)

    txt, markup = _source_menu(user_id)
    reply = await send_message(message, txt, markup)

    manga_user_state[user_id] = {
        "stage":       "source",
        "active_msg_id": reply.id,
        "last_active": time(),
        "use_zip":     use_zip,
    }


# ──────────────────────────────────────────────
# Dispatcher central de callbacks
# Todos os botões passam por aqui via regex ^mng:
# Formato: mng:{user_id}:{action}:{param}
# ──────────────────────────────────────────────

@new_task
async def manga_callback(client, query):
    """Handler único para todos os callbacks do fluxo manga."""
    parts = query.data.split(":")
    # Esperado: mng : user_id : action [: param]
    if len(parts) < 3:
        await query.answer("❌ Dados inválidos", show_alert=True)
        return

    try:
        cb_user_id = int(parts[1])
    except ValueError:
        await query.answer()
        return

    action = parts[2]
    param  = parts[3] if len(parts) > 3 else ""

    caller_id = query.from_user.id

    # Apenas o dono da sessão pode interagir
    if caller_id != cb_user_id:
        await query.answer("❌ Esta sessão não é sua.", show_alert=True)
        return

    # Sessão existe?
    if cb_user_id not in manga_user_state:
        await query.answer("⏱️ Sessão expirada. Use /mangaleech novamente.", show_alert=True)
        return

    # Callback vem da mensagem ativa? (anti-ghost)
    if not _is_active_msg(cb_user_id, query.message.id):
        await query.answer("⏱️ Esta mensagem não está mais ativa.", show_alert=True)
        return

    _touch(cb_user_id)
    state = manga_user_state[cb_user_id]

    # ── Cancelar ──────────────────────────────
    if action == "cancel":
        await query.answer()
        await edit_message(query.message, "❌ Operação cancelada.")
        _clear(cb_user_id)
        return

    # ── Noop (botão de página atual) ──────────
    if action == "noop":
        await query.answer()
        return

    # ── Voltar ────────────────────────────────
    if action == "back":
        await query.answer()
        await _handle_back(query, cb_user_id, state, param)
        return

    # ── Seleção de fonte ──────────────────────
    if action == "src":
        await query.answer()
        if param not in ("flower", "nine", "nexus"):
            return
        state["source"]     = param
        state["downloader"] = _make_source(param, LOGGER)
        state["stage"]      = "mode"

        txt, markup = _mode_menu(cb_user_id)
        await edit_message(query.message, txt, markup)
        return

    # ── Seleção de modo ───────────────────────
    if action == "mode":
        await query.answer()
        await _enter_mode(query, cb_user_id, state, param)
        return

    # ── Paginação de resultados ───────────────
    if action == "page":
        await query.answer()
        try:
            page = int(param)
        except ValueError:
            return
        state["page"] = page
        results = state.get("search_results", [])
        txt, markup = _results_menu(cb_user_id, results, page)
        await edit_message(query.message, txt, markup)
        return

    # ── Seleção de mangá na lista ─────────────
    if action == "pick":
        await query.answer()
        try:
            idx = int(param)
        except ValueError:
            return
        await _pick_manga(query, cb_user_id, state, idx)
        return

    # ── Nova busca (sem reiniciar o fluxo) ────
    if action == "newsearch":
        await query.answer()
        source = state.get("source", "flower")
        if source == "nine":
            example = "ex: Naruto"
        elif source == "nexus":
            example = "ex: Solo Leveling"
        else:
            example = "ex: Kimetsu no Yaiba"
        state["stage"] = "waiting_search"
        await edit_message(query.message, f"🔍 <b>Nova busca:</b>\nDigite o nome do mangá ({example}):")
        return

    await query.answer()


# ──────────────────────────────────────────────
# Voltar
# ──────────────────────────────────────────────

async def _handle_back(query, user_id: int, state: dict, target: str):
    """Retorna para a fase indicada."""
    if target == "source":
        # Volta para escolha de fonte
        state["stage"] = "source"
        state.pop("source", None)
        state.pop("downloader", None)
        state.pop("mode", None)
        txt, markup = _source_menu(user_id)
        await edit_message(query.message, txt, markup)

    elif target == "mode":
        # Volta para escolha de modo (link/search)
        state["stage"] = "mode"
        state.pop("mode", None)
        state.pop("search_results", None)
        state.pop("page", None)
        txt, markup = _mode_menu(user_id)
        await edit_message(query.message, txt, markup)

    elif target == "results":
        # Volta para a lista de resultados
        results = state.get("search_results", [])
        page    = state.get("page", 0)
        if not results:
            # Sem resultados para voltar → vai para modo
            state["stage"] = "mode"
            txt, markup = _mode_menu(user_id)
        else:
            state["stage"] = "results"
            txt, markup = _results_menu(user_id, results, page)
        await edit_message(query.message, txt, markup)


# ──────────────────────────────────────────────
# Entrar em modo (link ou search)
# ──────────────────────────────────────────────

async def _enter_mode(query, user_id: int, state: dict, mode: str):
    state["mode"]  = mode
    source = state.get("source", "flower")

    if mode == "link":
        if source == "nine":
            example = "https://br.ninemanga.com/manga/Kimetsu+no+Yaiba.html"
        elif source == "nexus":
            example = "https://nexustoons.com/manga/solo-leveling"
        else:
            example = "https://flowermangas.net/manga/solo-leveling/"
        state["stage"] = "waiting_link"
        await edit_message(query.message, f"🔗 <b>Envie o link do mangá:</b>\n<i>{example}</i>")

    elif mode == "search":
        state["stage"] = "waiting_search"
        await edit_message(query.message, "🔍 <b>Digite o nome do mangá que deseja procurar:</b>")


# ──────────────────────────────────────────────
# Selecionar mangá da lista
# ──────────────────────────────────────────────

async def _pick_manga(query, user_id: int, state: dict, idx: int):
    results = state.get("search_results", [])
    if idx >= len(results):
        await edit_message(query.message, "❌ Resultado inválido.")
        return

    source     = state.get("source", "flower")
    downloader = state.get("downloader")
    selected   = results[idx]
    url        = selected.get("slug") if source == "nexus" else selected.get("url")

    # Título já disponível nos resultados de busca — usado como hint para o NineManga
    # que não tem og:title nas páginas de obra
    hint_title = selected.get("title", "")

    state["selected_url"] = url
    state["stage"] = "loading_chapters"

    loading = await edit_message(query.message, "📊 <b>Carregando informações do mangá…</b>")

    try:
        # Passa hint_title para get_manga_info — no NineManga evita retornar "Unknown"
        if source == "nine":
            chapters, info = await asyncio.gather(
                downloader.list_chapters(url),
                downloader.get_manga_info(url, hint_title=hint_title),
            )
        else:
            chapters, info = await asyncio.gather(
                downloader.list_chapters(url),
                downloader.get_manga_info(url),
            )
    except Exception as e:
        LOGGER.error(f"Manga pick error: {e}")
        await edit_message(loading, "❌ Erro ao carregar capítulos. Tente novamente.")
        _clear(user_id)
        return

    if not chapters:
        # Botão para voltar aos resultados sem reiniciar
        b = ButtonMaker()
        b.data_button("↩ Voltar à lista", f"mng:{user_id}:back:results")
        b.data_button("❌ Cancelar",      f"mng:{user_id}:cancel")
        await edit_message(loading, "❌ Nenhum capítulo encontrado para este mangá.", b.build_menu(1))
        state["stage"] = "results"
        return

    state["chapters"] = chapters
    state["manga_info"] = info
    state["stage"] = "waiting_chapters"

    msg = _chapters_menu(user_id, info, chapters, source)
    await edit_message(loading, msg)
    state["active_msg_id"] = loading.id


# ──────────────────────────────────────────────
# Handler de mensagens de texto (pesquisa/link/capítulos)
# ──────────────────────────────────────────────

@new_task
async def manga_message_handler(client, message):
    """Recebe entrada de texto do usuário em qualquer fase de espera."""
    if not message.from_user:
        return
    user_id = message.from_user.id

    if user_id not in manga_user_state:
        return

    state = manga_user_state[user_id]
    stage = state.get("stage", "")

    # Verifica TTL da sessão
    if time() - state.get("last_active", 0) > SESSION_TTL:
        _clear(user_id)
        await send_message(message, "⏱️ Sessão expirada. Use /mangaleech novamente.")
        return

    _touch(user_id)

    if stage in ("waiting_search", "waiting_link"):
        await _handle_text_input(client, message, user_id, state, stage)
    elif stage == "waiting_chapters":
        await _handle_chapter_input(client, message, user_id, state)


# ──────────────────────────────────────────────
# Processar texto de busca ou link
# ──────────────────────────────────────────────

async def _handle_text_input(client, message, user_id: int, state: dict, stage: str):
    mode       = state.get("mode", "search")
    user_input = message.text.strip() if message.text else ""
    downloader = state.get("downloader")
    source     = state.get("source", "flower")

    if not downloader or not user_input:
        return

    if stage == "waiting_search":
        loading = await send_message(message, "🔍 <b>Pesquisando…</b>")
        results = await downloader.search(user_input)

        if not results:
            b = ButtonMaker()
            b.data_button("🔍 Tentar novamente", f"mng:{user_id}:newsearch")
            b.data_button("↩ Voltar",            f"mng:{user_id}:back:mode")
            b.data_button("❌ Cancelar",         f"mng:{user_id}:cancel")
            await edit_message(loading, "❌ <b>Nenhum resultado encontrado.</b>\nTente com outro nome.", b.build_menu(1))
            state["active_msg_id"] = loading.id
            state["stage"] = "results_empty"
            return

        state["search_results"] = results
        state["page"] = 0
        state["stage"] = "results"

        txt, markup = _results_menu(user_id, results, 0)
        await edit_message(loading, txt, markup)
        state["active_msg_id"] = loading.id

    elif stage == "waiting_link":
        # Valida o link antes de prosseguir
        url = user_input
        if not url.startswith("http"):
            await send_message(message, "❌ Link inválido. Envie uma URL completa.")
            return

        # Para Nexus, extrai o slug do link
        if source == "nexus":
            m = re.search(r"/manga/([^/?#]+)", url)
            if not m:
                await send_message(message, "❌ Não foi possível extrair o slug do link.")
                return
            url = m.group(1)

        state["selected_url"] = url
        state["stage"] = "loading_chapters"

        loading = await send_message(message, "📊 <b>Carregando informações do mangá…</b>")

        try:
            # Para NineManga, extrai hint do próprio link como fallback de título
            if source == "nine":
                url_part = re.search(r'/manga/([^/?#]+)', url)
                hint = url_part.group(1).replace("+", " ").replace("-", " ").replace(".html", "").title() if url_part else ""
                chapters, info = await asyncio.gather(
                    downloader.list_chapters(url),
                    downloader.get_manga_info(url, hint_title=hint),
                )
            else:
                chapters, info = await asyncio.gather(
                    downloader.list_chapters(url),
                    downloader.get_manga_info(url),
                )
        except Exception as e:
            LOGGER.error(f"Manga link load error: {e}")
            await edit_message(loading, "❌ Erro ao carregar. Verifique o link e tente novamente.")
            _clear(user_id)
            return

        if not chapters:
            await edit_message(loading, "❌ Nenhum capítulo encontrado. Verifique o link.")
            _clear(user_id)
            return

        state["chapters"]   = chapters
        state["manga_info"] = info
        state["stage"]      = "waiting_chapters"
        state["active_msg_id"] = loading.id

        msg = _chapters_menu(user_id, info, chapters, source)
        await edit_message(loading, msg)


# ──────────────────────────────────────────────
# Processar intervalo de capítulos e fazer download
# ──────────────────────────────────────────────

async def _handle_chapter_input(client, message, user_id: int, state: dict):
    user_input = message.text.strip() if message.text else ""
    downloader = state.get("downloader")
    chapters   = state.get("chapters", [])
    url        = state.get("selected_url")
    source     = state.get("source", "flower")
    use_zip    = state.get("use_zip", False)
    info       = state.get("manga_info", {})

    # Nome limpo do mangá para usar em arquivos e mensagens
    manga_title    = info.get("title") or "Manga"
    manga_filename = _safe_filename(manga_title)   # ex: "One_Piece"
    cover_url      = info.get("image", "")

    if not all([downloader, chapters, url]):
        await send_message(message, "❌ Erro de sessão. Use /mangaleech novamente.")
        _clear(user_id)
        return

    # Parse do intervalo
    if user_input.lower() in ("todos", "all"):
        start, end = 0, float("inf")
    else:
        parsed = parse_chapter_range(user_input)
        if parsed is None or parsed[0] is None:
            await send_message(
                message,
                "❌ <b>Formato inválido.</b>\n"
                "Use: <code>1-5</code> · <code>10</code> · <code>15-20</code> · <code>todos</code>"
            )
            return
        start, end = parsed

    # Filtra capítulos no intervalo
    selected_chapters = [
        c for c in chapters
        if start <= _chapter_number(downloader, c) <= end
    ]

    if not selected_chapters:
        await send_message(message, "❌ Nenhum capítulo encontrado nesse intervalo.")
        return

    # Libera estado antes de um processo longo
    _clear(user_id)
    dl_msg = await send_message(
        message,
        f"⏳ <b>Iniciando download de {len(selected_chapters)} capítulo(s) de</b> <i>{manga_title}</i>…"
    )
    download_dir = f"{DOWNLOAD_DIR}manga/{user_id}_{int(time())}"

    # Baixa a capa uma vez para embutir em todos os CBZs
    cover_data: bytes | None = None
    if cover_url:
        await edit_message(dl_msg, f"🖼️ <b>Baixando capa de</b> <i>{manga_title}</i>…")
        cover_data = await _fetch_cover(cover_url)
        if cover_data:
            LOGGER.info(f"Manga cover fetched: {len(cover_data)} bytes")
        else:
            LOGGER.warning(f"Manga cover unavailable for: {manga_title}")

    results: list[tuple[str, int, float]] = []   # (cbz_path, page_count, cap_num)

    try:
        for idx, chapter_data in enumerate(selected_chapters, 1):
            pct = int((idx / len(selected_chapters)) * 100)
            bar = get_progress_bar_string(f"{pct}%")

            # Número do capítulo para exibição no progresso
            cap_num = _chapter_number(downloader, chapter_data)
            if cap_num == int(cap_num):
                cap_display = str(int(cap_num))
            else:
                cap_display = str(cap_num)

            await edit_message(
                dl_msg,
                f"⏳ <b>Baixando</b> <i>{manga_title}</i>…\n\n"
                f"{bar} {pct}%\n\n"
                f"📥 Capítulo <code>{cap_display}</code> ({idx}/{len(selected_chapters)})"
            )

            cbz_path, page_count = await downloader.download_chapter(
                chapter_data, download_dir, cover_data=cover_data
            )

            if cbz_path:
                # Renomeia o arquivo para incluir o título do mangá
                # ex: /path/cap_01100.cbz  →  /path/One_Piece_Cap_01100.cbz
                old_base = os.path.basename(cbz_path)          # cap_01100.cbz
                cap_part = old_base                             # fallback
                # Extrai a parte numérica do nome gerado pelo downloader
                m = re.match(r'(cap_.+)\.cbz$', old_base, re.I)
                if m:
                    cap_part = m.group(1)                       # cap_01100
                new_name = f"{manga_filename}_{cap_part}.cbz"  # One_Piece_cap_01100.cbz
                new_path = os.path.join(os.path.dirname(cbz_path), new_name)
                try:
                    os.rename(cbz_path, new_path)
                    cbz_path = new_path
                except Exception as rename_err:
                    LOGGER.warning(f"Could not rename CBZ: {rename_err}")

                results.append((cbz_path, page_count, cap_num))

        if not results:
            await edit_message(dl_msg, "❌ Falha no download de todos os capítulos.")
            await _cleanup_dir(download_dir)
            return

        # ── Modo ZIP ──────────────────────────────────────────────────────
        if use_zip:
            await edit_message(dl_msg, f"🗜️ <b>Compactando</b> <i>{manga_title}</i> em ZIP…")
            zip_name = f"{manga_filename}_caps.zip"
            zip_path = os.path.join(download_dir, zip_name)

            def _make_zip():
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fp, _, _ in results:
                        zf.write(fp, arcname=os.path.basename(fp))

            await asyncio.to_thread(_make_zip)

            total_size = os.path.getsize(zip_path)
            await edit_message(
                dl_msg,
                f"📤 <b>Enviando ZIP de</b> <i>{manga_title}</i>…\n"
                f"{len(results)} capítulos · {get_readable_file_size(total_size)}"
            )
            cap_nums = sorted(r[2] for r in results)
            first_c  = int(cap_nums[0])  if cap_nums[0]  == int(cap_nums[0])  else cap_nums[0]
            last_c   = int(cap_nums[-1]) if cap_nums[-1] == int(cap_nums[-1]) else cap_nums[-1]
            caption  = (
                f"📦 <b>{manga_title}</b>\n"
                f"📚 {len(results)} capítulos"
                + (f" (Cap. {first_c}–{last_c})" if first_c != last_c else f" (Cap. {first_c})")
                + f"\n💾 {get_readable_file_size(total_size)}"
            )
            await send_file(message, zip_path, caption=caption)
            await edit_message(dl_msg, f"✅ <b>ZIP de</b> <i>{manga_title}</i> <b>enviado!</b>")

        # ── Modo normal (CBZ individuais) ─────────────────────────────────
        else:
            total_size = sum(
                os.path.getsize(fp) for fp, _, _ in results if os.path.exists(fp)
            )
            await edit_message(
                dl_msg,
                f"✅ <b>Download concluído!</b> <i>{manga_title}</i>\n\n"
                f"📦 {len(results)} capítulos · {get_readable_file_size(total_size)}\n"
                f"📤 <b>Enviando para o Telegram…</b>"
            )

            for idx, (fp, pages, cap_num) in enumerate(results, 1):
                pct  = int((idx / len(results)) * 100)
                bar  = get_progress_bar_string(f"{pct}%")
                fname = os.path.basename(fp)
                cap_display = str(int(cap_num)) if cap_num == int(cap_num) else str(cap_num)

                await edit_message(
                    dl_msg,
                    f"📤 <b>Enviando</b> <i>{manga_title}</i>…\n"
                    f"{bar} {pct}%\n"
                    f"{idx}/{len(results)} — Cap. {cap_display}"
                )
                try:
                    size    = os.path.getsize(fp)
                    caption = (
                        f"📖 <b>{manga_title}</b> — Cap. {cap_display}\n"
                        f"📄 {pages} páginas · {get_readable_file_size(size)}"
                        + ("\n🖼️ <i>Capa incluída</i>" if cover_data else "")
                    )
                    await send_file(message, fp, caption=caption)
                except Exception as e:
                    LOGGER.error(f"Error sending {fp}: {e}")
                    await send_message(
                        message,
                        f"⚠️ Erro ao enviar Cap. {cap_display}: {str(e)[:120]}"
                    )

            await edit_message(
                dl_msg,
                f"✅ <b>Todos os capítulos de</b> <i>{manga_title}</i> <b>foram enviados!</b>"
            )

    except Exception as e:
        LOGGER.error(f"Manga download error: {e}")
        await send_message(message, f"❌ Erro durante o download: {str(e)[:200]}")
    finally:
        await _cleanup_dir(download_dir)
