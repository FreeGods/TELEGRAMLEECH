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
    Callbacks de mensagens antigas são rejeitados silenciosamente.
    """
    state = manga_user_state.get(user_id)
    if not state:
        return False
    return state.get("active_msg_id") == message_id


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
        b.data_button(label, data)

    b.data_button("🔍 Nova busca",   f"mng:{user_id}:newsearch")
    b.data_button("↩ Voltar",        f"mng:{user_id}:back:mode")
    b.data_button("❌ Cancelar",     f"mng:{user_id}:cancel")

    msg = f"🔎 <b>Resultados</b> ({len(results)} encontrados):\nPágina {page + 1}/{total_pages}"
    return msg, b.build_menu(1, last_row_buttons=len(nav))


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

    state["selected_url"] = url
    state["stage"] = "loading_chapters"

    loading = await edit_message(query.message, "📊 <b>Carregando informações do mangá…</b>")

    try:
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

        loading = await send_message(message, "📊 <b>Ca
