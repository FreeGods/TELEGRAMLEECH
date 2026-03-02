"""
Novel Leech Command Module
Handles /novelleech command with source selection, search, volume/chapter range downloads.

Features:
  - Seleção de fonte (Central Novel, etc)
  - Busca ou link direto
  - Seleção de volumes/capítulos para download
  - Geração de EPUB profissional
  - Paginação de resultados
  - Navegação com botões ↩
"""

import asyncio
import os
import re
import shutil
from time import time
from typing import Optional

from pyrogram.filters import command, regex
from pyrogram.handlers import CallbackQueryHandler, MessageHandler

from .. import DOWNLOAD_DIR, LOGGER
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.central_novel_utils import CentralNovelDownloader
from ..helper.ext_utils.status_utils import get_readable_file_size
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
PAGE_SIZE = 6          # resultados por página
SESSION_TTL = 900      # 15 minutos
NOVELS_DIR = f"{DOWNLOAD_DIR}/novels"

# ─────────────────────────────────────────────
# Estado global das sessões por usuário
# ─────────────────────────────────────────────
novel_user_state: dict[int, dict] = {}


# ──────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────

def _touch(user_id: int):
    """Atualiza timestamp da sessão."""
    if user_id in novel_user_state:
        novel_user_state[user_id]["last_active"] = time()


def _clear(user_id: int):
    """Remove sessão do usuário."""
    novel_user_state.pop(user_id, None)


def _make_source(source_key: str, logger=None):
    """Factory para criar downloader da fonte."""
    if source_key == "central":
        return CentralNovelDownloader(logger=logger)
    # Expandir com outras fontes aqui
    return CentralNovelDownloader(logger=logger)


def _safe_filename(title: str) -> str:
    """Converte título em nome seguro para arquivos."""
    safe = re.sub(r"[^\w\s\-]", "", title, flags=re.UNICODE).strip()
    safe = re.sub(r"\s+", "_", safe)
    return safe[:50] or "novel"


async def _cleanup_dir(path: str):
    """Remove diretório com segurança."""
    try:
        if await aiopath.exists(path):
            await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)
    except Exception as e:
        LOGGER.warning(f"Novel cleanup warning: {e}")


def parse_chapter_range(
    chapters: list[dict], range_str: str
) -> list[dict]:
    """
    Parse de intervalo de capítulos.
    
    Formatos suportados: "1-5", "10", "15-20", "todos", etc
    """
    range_str = range_str.strip().lower()
    
    if not chapters:
        return []
    
    if range_str == "todos":
        return chapters
    
    if "-" in range_str:
        try:
            start_str, end_str = range_str.split("-", 1)
            start = float(start_str.strip())
            end = float(end_str.strip())
            
            return [
                c for c in chapters
                if start <= c.get("numero", 0) <= end
            ]
        except ValueError:
            return chapters
    else:
        try:
            target = float(range_str)
            return [c for c in chapters if c.get("numero", 0) == target]
        except ValueError:
            return chapters


# ──────────────────────────────────────────────
# Construção de menus
# ──────────────────────────────────────────────

def _source_menu(user_id: int) -> tuple:
    """Menu de seleção de fonte."""
    b = ButtonMaker()
    b.data_button("📖 Central Novel", f"nvl:{user_id}:src:central")
    b.data_button("❌ Cancelar", f"nvl:{user_id}:cancel")
    return "📚 <b>Escolha a fonte de novels:</b>", b.build_menu(1)


def _mode_menu(user_id: int) -> tuple:
    """Menu de seleção de modo (link/busca)."""
    b = ButtonMaker()
    b.data_button("🔗 Link direto", f"nvl:{user_id}:mode:link")
    b.data_button("🔍 Pesquisar", f"nvl:{user_id}:mode:search")
    b.data_button("↩ Voltar", f"nvl:{user_id}:back:source")
    b.data_button("❌ Cancelar", f"nvl:{user_id}:cancel")
    return "🎯 <b>Como deseja adicionar a novel?</b>", b.build_menu(2)


def _results_menu(user_id: int, results: list, page: int) -> tuple:
    """Menu paginado de resultados de busca."""
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_results = results[start:end]
    total_pages = max(1, -(-len(results) // PAGE_SIZE))
    
    b = ButtonMaker()
    for i, r in enumerate(page_results):
        title = r.get("title", "Sem título")[:45]
        b.data_button(title, f"nvl:{user_id}:pick:{start + i}")
    
    # Paginação
    nav = []
    if page > 0:
        nav.append(("◀", f"nvl:{user_id}:page:{page - 1}"))
    nav.append((f"{page + 1}/{total_pages}", f"nvl:{user_id}:noop"))
    if end < len(results):
        nav.append(("▶", f"nvl:{user_id}:page:{page + 1}"))
    for label, data in nav:
        b.data_button(label, data, position="l_body")
    
    b.data_button("🔍 Nova busca", f"nvl:{user_id}:newsearch", position="footer")
    b.data_button("↩ Voltar", f"nvl:{user_id}:back:mode", position="footer")
    b.data_button("❌ Cancelar", f"nvl:{user_id}:cancel", position="footer")
    
    msg = f"🔎 <b>Resultados</b> ({len(results)} encontrados):\nPágina {page + 1}/{total_pages}"
    return msg, b.build_menu(1, lb_cols=len(nav), f_cols=3)


def _volumes_menu(user_id: int, volumes_data: dict) -> tuple:
    """Menu de seleção de volumes."""
    b = ButtonMaker()
    
    for vol_num in sorted(volumes_data.keys()):
        caps = volumes_data[vol_num]
        if caps:
            first_cap = caps[0].get("numero", 1)
            last_cap = caps[-1].get("numero", len(caps))
            label = f"Vol {vol_num} (Cap {first_cap}-{last_cap})"
            b.data_button(label, f"nvl:{user_id}:vol:{vol_num}")
    
    b.data_button("📥 Todos os volumes", f"nvl:{user_id}:vol:all")
    b.data_button("↩ Voltar", f"nvl:{user_id}:back:mode")
    b.data_button("❌ Cancelar", f"nvl:{user_id}:cancel")
    
    msg = "📚 <b>Selecione volume(s) para baixar:</b>"
    return msg, b.build_menu(1, f_cols=3)


def _chapters_menu(user_id: int, info: dict, chapters: list, vol_num: Optional[int] = None) -> str:
    """Menu de especificação de intervalo de capítulos."""
    try:
        first = chapters[0].get("numero", 1) if chapters else 1
        last = chapters[-1].get("numero", len(chapters)) if chapters else len(chapters)
    except Exception:
        first, last = 1, len(chapters)
    
    msg = f"📖 <b>{info.get('title', 'Desconhecido')}</b>\n\n"
    if vol_num:
        msg += f"📕 <b>Volume:</b> {vol_num}\n"
    msg += f"📊 <b>Total de capítulos:</b> {len(chapters)}\n"
    msg += f"📍 <b>Do capítulo</b> {first} <b>ao</b> {last}\n"
    
    if info.get("description"):
        desc = info["description"][:150]
        msg += f"\n📝 {desc}{'…' if len(info.get('description', '')) > 150 else ''}\n"
    
    msg += "\n📌 <b>Digite o intervalo de capítulos:</b>"
    msg += "\n<i>Exemplos: 1-5 · 10 · 15-20 · todos</i>"
    
    return msg


# ──────────────────────────────────────────────
# Comando principal
# ──────────────────────────────────────────────

@new_task
async def novelleech(client, message):
    """Ponto de entrada do /novelleech"""
    user = message.from_user
    if not user:
        return
    user_id = user.id
    
    # Cancela sessão anterior
    _clear(user_id)
    
    txt, markup = _source_menu(user_id)
    reply = await send_message(message, txt, markup)
    
    novel_user_state[user_id] = {
        "stage": "source",
        "active_msg_id": reply.id,
        "last_active": time(),
    }


# ──────────────────────────────────────────────
# Dispatcher central de callbacks
# ──────────────────────────────────────────────

@new_task
async def novel_callback(client, query):
    """Handler único para todos os callbacks do fluxo novel."""
    parts = query.data.split(":")
    
    if len(parts) < 3:
        await query.answer("❌ Dados inválidos", show_alert=True)
        return
    
    try:
        cb_user_id = int(parts[1])
    except ValueError:
        await query.answer()
        return
    
    action = parts[2]
    param = parts[3] if len(parts) > 3 else ""
    caller_id = query.from_user.id
    
    # Apenas o dono da sessão pode interagir
    if caller_id != cb_user_id:
        await query.answer("❌ Esta sessão não é sua", show_alert=True)
        return
    
    if cb_user_id not in novel_user_state:
        await query.answer("⏰ Sessão expirada", show_alert=True)
        return
    
    _touch(cb_user_id)
    state = novel_user_state[cb_user_id]
    
    # Ações especiais
    if action == "cancel":
        _clear(cb_user_id)
        await edit_message(query.message, "❌ Cancelado.")
        await query.answer()
        return
    
    if action == "noop":
        await query.answer()
        return
    
    if action == "back":
        await query.answer()
        await _handle_back(client, query, state, param)
        return
    
    # Ações por stage
    if state["stage"] == "source":
        if action == "src":
            await _handle_source_select(client, query, cb_user_id, param)
    
    elif state["stage"] == "mode":
        if action == "mode":
            await _handle_mode_select(client, query, cb_user_id, param)
    
    elif state["stage"] == "link_input":
        if action == "newsearch":
            state["stage"] = "search_input"
            await edit_message(
                query.message,
                "🔍 <b>Digite o nome da novel para buscar:</b>",
            )
            await query.answer()
    
    elif state["stage"] == "search_results":
        if action == "pick":
            await _handle_pick_novel(client, query, cb_user_id, int(param))
        elif action == "page":
            await _handle_page_change(client, query, cb_user_id, int(param))
        elif action == "newsearch":
            state["stage"] = "search_input"
            await edit_message(
                query.message,
                "🔍 <b>Digite o nome da novel para buscar:</b>",
            )
            await query.answer()
    
    elif state["stage"] == "volume_selection":
        if action == "vol":
            await _handle_volume_select(client, query, cb_user_id, param)
    
    await query.answer()


async def _handle_source_select(client, query, user_id: int, source: str):
    """Usuário selecionou fonte."""
    state = novel_user_state[user_id]
    state["source"] = source
    state["stage"] = "mode"
    state["downloader"] = _make_source(source, logger=LOGGER)
    
    txt, markup = _mode_menu(user_id)
    await edit_message(query.message, txt, markup)


async def _handle_mode_select(client, query, user_id: int, mode: str):
    """Usuário selecionou modo (link ou busca)."""
    state = novel_user_state[user_id]
    state["mode"] = mode
    
    if mode == "link":
        state["stage"] = "link_input"
        await edit_message(
            query.message,
            "🔗 <b>Cole o link da novel do Central Novel:</b>",
        )
    else:
        state["stage"] = "search_input"
        await edit_message(
            query.message,
            "🔍 <b>Digite o nome da novel para buscar:</b>",
        )


async def _handle_pick_novel(client, query, user_id: int, result_idx: int):
    """Usuário selecionou novel dos resultados."""
    state = novel_user_state[user_id]
    
    if "search_results" not in state or result_idx >= len(state["search_results"]):
        await query.answer("❌ Seleção inválida", show_alert=True)
        return
    
    novel = state["search_results"][result_idx]
    state["selected_novel"] = novel
    
    await edit_message(
        query.message,
        f"⏳ <b>Carregando volumes e capítulos...</b>",
    )
    
    downloader = state["downloader"]
    volumes = await downloader.list_volumes_and_chapters(novel["url"])
    
    if not volumes:
        await edit_message(
            query.message,
            "❌ Não foi possível carregar os volumes desta novel.",
        )
        return
    
    state["volumes"] = volumes
    state["stage"] = "volume_selection"
    
    txt, markup = _volumes_menu(user_id, volumes)
    await edit_message(query.message, txt, markup)


async def _handle_page_change(client, query, user_id: int, page: int):
    """Usuário mudou página de resultados."""
    state = novel_user_state[user_id]
    state["page"] = page
    
    results = state.get("search_results", [])
    txt, markup = _results_menu(user_id, results, page)
    await edit_message(query.message, txt, markup)


async def _handle_volume_select(client, query, user_id: int, vol_param: str):
    """Usuário selecionou volume(s)."""
    state = novel_user_state[user_id]
    volumes = state["volumes"]
    
    if vol_param == "all":
        selected_volumes = volumes
    else:
        try:
            vol_num = int(vol_param)
            selected_volumes = {vol_num: volumes[vol_num]} if vol_num in volumes else {}
        except ValueError:
            await query.answer("❌ Volume inválido", show_alert=True)
            return
    
    if not selected_volumes:
        await query.answer("❌ Nenhum volume selecionado", show_alert=True)
        return
    
    state["selected_volumes"] = selected_volumes
    state["stage"] = "chapters_input"
    
    # Obtém todos os capítulos dos volumes selecionados
    all_chapters = []
    for vol_num in sorted(selected_volumes.keys()):
        all_chapters.extend(selected_volumes[vol_num])
    
    novel = state["selected_novel"]
    txt = _chapters_menu(user_id, novel, all_chapters)
    await edit_message(query.message, txt)


def _handle_back(client, query, state: dict, back_to: str):
    """Usuário clicou em voltar."""
    if back_to == "source":
        state["stage"] = "source"
        txt, markup = _source_menu(query.from_user.id)
    elif back_to == "mode":
        state["stage"] = "mode"
        txt, markup = _mode_menu(query.from_user.id)
    elif back_to == "chapters":
        state["stage"] = "volume_selection"
        txt, markup = _volumes_menu(query.from_user.id, state["volumes"])
    else:
        return
    
    asyncio.create_task(edit_message(query.message, txt, markup))


async def _handle_back(client, query, state: dict, back_to: str):
    """Usuário clicou em voltar."""
    if back_to == "source":
        state["stage"] = "source"
        txt, markup = _source_menu(query.from_user.id)
    elif back_to == "mode":
        state["stage"] = "mode"
        txt, markup = _mode_menu(query.from_user.id)
    elif back_to == "chapters":
        state["stage"] = "volume_selection"
        txt, markup = _volumes_menu(query.from_user.id, state["volumes"])
    else:
        return
    
    await edit_message(query.message, txt, markup)


# ──────────────────────────────────────────────
# Handler de mensagens de texto
# ──────────────────────────────────────────────

@new_task
async def novel_text_handler(client, message):
    """Handler para texto enviado durante fluxo de novel."""
    user_id = message.from_user.id
    
    if user_id not in novel_user_state:
        return
    
    state = novel_user_state[user_id]
    _touch(user_id)
    
    # Está aguardando link?
    if state["stage"] == "link_input":
        link = message.text.strip()
        if not link.startswith("http"):
            await send_message(message, "❌ URL inválida. Digite um link válido.")
            return
        
        state["selected_novel"] = {"url": link, "title": "Novel (link direto)"}
        
        await send_message(message, "⏳ <b>Carregando volumes e capítulos...</b>")
        
        downloader = state["downloader"]
        volumes = await downloader.list_volumes_and_chapters(link)
        
        if not volumes:
            await send_message(message, "❌ Não foi possível carregar os volumes.")
            return
        
        state["volumes"] = volumes
        state["stage"] = "volume_selection"
        
        txt, markup = _volumes_menu(user_id, volumes)
        await send_message(message, txt, markup)
    
    # Está aguardando busca?
    elif state["stage"] == "search_input":
        term = message.text.strip()
        
        await send_message(message, f"🔍 <b>Buscando '{term}'...</b>")
        
        downloader = state["downloader"]
        results = await downloader.search(term)
        
        if not results:
            await send_message(message, "❌ Nenhum resultado encontrado.")
            state["stage"] = "search_input"
            return
        
        state["search_results"] = results
        state["page"] = 0
        state["stage"] = "search_results"
        
        txt, markup = _results_menu(user_id, results, 0)
        await send_message(message, txt, markup)
    
    # Está aguardando intervalo de capítulos?
    elif state["stage"] == "chapters_input":
        range_str = message.text.strip()
        
        selected_volumes = state["selected_volumes"]
        all_chapters = []
        for vol_num in sorted(selected_volumes.keys()):
            all_chapters.extend(selected_volumes[vol_num])
        
        selected_chapters = parse_chapter_range(all_chapters, range_str)
        
        if not selected_chapters:
            await send_message(message, "❌ Intervalo inválido. Digite novamente.")
            return
        
        state["selected_chapters"] = selected_chapters
        
        # Inicia download
        await _start_novel_download(client, message, state, user_id)


async def _start_novel_download(client, message, state: dict, user_id: int):
    """Inicia download dos capítulos selecionados."""
    downloader = state["downloader"]
    novel = state["selected_novel"]
    chapters = state["selected_chapters"]
    
    await send_message(
        message,
        f"📥 <b>Baixando {len(chapters)} capítulo(s)...</b>\n\n"
        f"Novel: {novel['title']}\n"
        f"Capítulos: {len(chapters)}",
    )
    
    # Agrupa capítulos por volume
    volumes_data = {}
    for chapter in chapters:
        # Encontra qual volume este capítulo pertence
        for vol_num, vol_chapters in state["selected_volumes"].items():
            if chapter in vol_chapters:
                if vol_num not in volumes_data:
                    volumes_data[vol_num] = []
                volumes_data[vol_num].append(chapter)
                break
    
    # Baixa conteúdo dos capítulos
    for vol_num in sorted(volumes_data.keys()):
        vol_chapters = volumes_data[vol_num]
        volumes_data[vol_num] = []
        
        for chapter in vol_chapters:
            html_content, imgs = await downloader.download_chapter(chapter["url"])
            
            if html_content:
                volumes_data[vol_num].append({
                    "numero": chapter["numero"],
                    "html": html_content,
                    "imgs": imgs,
                })
                await send_message(
                    message,
                    f"✅ <b>Vol {vol_num} Cap {chapter['numero']}</b>",
                )
            else:
                await send_message(
                    message,
                    f"⚠️ <b>Vol {vol_num} Cap {chapter['numero']}</b> - falhou",
                )
    
    # Cria EPUB
    await send_message(message, "📦 <b>Criando EPUB...</b>")
    
    os.makedirs(NOVELS_DIR, exist_ok=True)
    title = novel.get("title", "Novel")
    author = "Central Novel"
    
    safe_name = _safe_filename(title)
    epub_path = f"{NOVELS_DIR}/{safe_name}.epub"
    
    try:
        epub_path = await downloader.create_epub(
            title,
            author,
            volumes_data,
            epub_path,
        )
        
        # Envia arquivo
        await send_file(
            client,
            message.chat.id,
            epub_path,
            caption=f"📖 <b>{title}</b>\n\n✅ EPUB gerado com sucesso!",
        )
        
        await send_message(message, f"✅ <b>Download concluído!</b>")
        
    except Exception as e:
        LOGGER.error(f"EPUB creation error: {e}")
        await send_message(message, f"❌ Erro ao criar EPUB: {str(e)[:100]}")
    
    finally:
        await downloader.close()
        _clear(user_id)
