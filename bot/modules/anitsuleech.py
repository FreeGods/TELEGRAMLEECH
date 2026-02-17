"""
Anitsu Leech Command Module
Handles /anitsuleech with search, folder navigation, and file download.

Features:
  - Search with paginated results (◀ ▶ navigation)
  - Folder browsing with breadcrumb path
  - Mirror or Leech files directly
  - Back button (↩) at every stage
  - Session timeout (10 min)
"""

import asyncio
import os
import re
from time import time

from pyrogram.filters import command, regex
from pyrogram.handlers import CallbackQueryHandler, MessageHandler

from .. import LOGGER
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.status_utils import get_readable_file_size
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    edit_message,
    send_message,
)
from ..helper.telegram_helper.bot_commands import BotCommands

# Importa o cliente Anitsu (assumindo que está em helper/ext_utils/)
try:
    from ..helper.ext_utils.anitsu_client import AnitsuClient, get_anitsu_client
except Exception as e:
    # Fallback se o cliente não estiver integrado ainda — registrar exceção completa
    LOGGER.exception("anitsu_client não encontrado ou erro ao importar — /anitsuleech não funcionará: %s", e)
    AnitsuClient = None
    get_anitsu_client = None


# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────
PAGE_SIZE     = 8
SESSION_TTL   = 600   # 10 min
MAX_PATH_LEN  = 60    # trunca paths muito longos na exibição

# ─────────────────────────────────────────────
# Estado global das sessões
# Estrutura:
#   stage         : str   — fase atual
#   search_query  : str   — termo de busca original
#   search_results: list  — resultados da última busca
#   page          : int   — página atual
#   current_path  : str   — caminho da pasta atual
#   breadcrumb    : list  — histórico de navegação
#   active_msg_id : int   — id da mensagem ativa
#   last_active   : float — timestamp última interação
# ─────────────────────────────────────────────
anitsu_user_state: dict[int, dict] = {}


# ─────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────

def _touch(user_id: int):
    if user_id in anitsu_user_state:
        anitsu_user_state[user_id]["last_active"] = time()


def _clear(user_id: int):
    anitsu_user_state.pop(user_id, None)


def _truncate(path: str, maxlen: int = MAX_PATH_LEN) -> str:
    """Trunca paths longos mantendo início e fim."""
    if len(path) <= maxlen:
        return path
    half = (maxlen - 3) // 2
    return f"{path[:half]}...{path[-half:]}"


def _safe_filename(name: str) -> str:
    """Remove caracteres inválidos de nomes de arquivo."""
    return re.sub(r'[^\w\s\-\.]', '_', name, flags=re.UNICODE).strip()


# ─────────────────────────────────────────────
# Construção de menus
# ─────────────────────────────────────────────

def _search_results_menu(user_id: int, results: list, page: int) -> tuple:
    """Menu paginado de resultados de busca."""
    start = page * PAGE_SIZE
    end   = start + PAGE_SIZE
    page_results = results[start:end]
    total_pages  = max(1, -(-len(results) // PAGE_SIZE))

    b = ButtonMaker()
    for i, item in enumerate(page_results):
        name = item.get("name", "?")[:50]
        b.data_button(name, f"ant:{user_id}:sel:{start + i}")

    # Navegação
    nav = []
    if page > 0:
        nav.append(("◀", f"ant:{user_id}:page:{page - 1}"))
    nav.append((f"{page + 1}/{total_pages}", f"ant:{user_id}:noop"))
    if end < len(results):
        nav.append(("▶", f"ant:{user_id}:page:{page + 1}"))
    for label, data in nav:
        b.data_button(label, data)

    b.data_button("🔍 Nova busca", f"ant:{user_id}:newsearch")
    b.data_button("❌ Cancelar",   f"ant:{user_id}:cancel")

    msg = f"🎌 <b>Resultados</b> ({len(results)} encontrados)\nPágina {page + 1}/{total_pages}"
    return msg, b.build_menu(1, last_row_buttons=len(nav))


def _folder_menu(user_id: int, path: str, files: list, parent: str | None) -> tuple:
    """Menu de navegação de pasta."""
    folders = [f for f in files if f.get("is_directory")]
    docs    = [f for f in files if not f.get("is_directory")]

    b = ButtonMaker()

    # Pastas
    for folder in folders[:15]:  # limita a 15 para não estourar callback
        fname = folder["name"][:45]
        subpath = f"{path}/{folder['name']}" if path else folder["name"]
        b.data_button(f"📁 {fname}", f"ant:{user_id}:nav:{subpath}")

    # Arquivos
    for doc in docs[:10]:
        fname = doc["name"][:40]
        fpath = f"{path}/{doc['name']}" if path else doc["name"]
        # Codifica o path em base64 para evitar overflow no callback_data
        import base64
        fpath_enc = base64.b64encode(fpath.encode()).decode()[:50]
        b.data_button(f"🎬 {fname}", f"ant:{user_id}:file:{fpath_enc}")

    # Controles
    if parent is not None:
        b.data_button("↩ Voltar", f"ant:{user_id}:nav:{parent}" if parent else f"ant:{user_id}:back:results")
    b.data_button("🔍 Nova busca", f"ant:{user_id}:newsearch")
    b.data_button("❌ Cancelar",   f"ant:{user_id}:cancel")

    path_display = _truncate(path or "/", 60)
    msg = f"📂 <b>{path_display}</b>\n\n"
    if folders:
        msg += f"📁 {len(folders)} pasta(s)\n"
    if docs:
        msg += f"🎬 {len(docs)} arquivo(s)"
    return msg, b.build_menu(1)


def _file_actions_menu(user_id: int, fpath: str, info: dict) -> tuple:
    """Menu de ações para um arquivo."""
    import base64
    fpath_enc = base64.b64encode(fpath.encode()).decode()[:50]

    b = ButtonMaker()
    b.data_button("🔗 Mirror",  f"ant:{user_id}:mirror:{fpath_enc}")
    b.data_button("📥 Leech",   f"ant:{user_id}:leech:{fpath_enc}")
    b.data_button("↩ Voltar",   f"ant:{user_id}:back:folder")
    b.data_button("❌ Cancelar", f"ant:{user_id}:cancel")

    fname = info.get("filename", os.path.basename(fpath))[:60]
    size  = get_readable_file_size(info.get("size", 0))
    msg = (
        f"📄 <b>{fname}</b>\n\n"
        f"💾 Tamanho: {size}\n\n"
        f"<b>Escolha a ação:</b>"
    )
    return msg, b.build_menu(2)


# ─────────────────────────────────────────────
# Comando principal
# ─────────────────────────────────────────────

@new_task
async def anitsuleech(client, message):
    """Ponto de entrada: /anitsuleech"""
    # Verifica se o cliente está disponível
    if not get_anitsu_client:
        LOGGER.error("[Anitsu] Client function não disponível - import falhou")
        await send_message(message, "❌ Anitsu client não configurado. Contate o admin.")
        return

    # Tenta instanciar o cliente
    try:
        ac = get_anitsu_client()
        LOGGER.info(f"[Anitsu] Cliente inicializado com sucesso")
    except RuntimeError as e:
        LOGGER.error(f"[Anitsu] Erro ao inicializar cliente: {e}")
        await send_message(message, f"❌ Anitsu não configurado: {str(e)}")
        return
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro inesperado ao inicializar:** {e}")
        await send_message(message, f"❌ Erro ao inicializar Anitsu: {str(e)}")
        return

    user = message.from_user
    if not user:
        LOGGER.warning("[Anitsu] Mensagem sem usuário")
        return
    user_id = user.id

    LOGGER.info(f"[Anitsu] Iniciando /anitsuleech para usuário {user_id}")
    _clear(user_id)

    txt = (
        "🎌 <b>Anitsu Cloud Leech</b>\n\n"
        "Digite o nome do anime que deseja buscar:"
    )
    reply = await send_message(message, txt)

    anitsu_user_state[user_id] = {
        "stage":       "waiting_search",
        "active_msg_id": reply.id,
        "last_active": time(),
    }
    LOGGER.info(f"[Anitsu] Sessão iniciada para {user_id}")


# ─────────────────────────────────────────────
# Dispatcher central de callbacks
# ─────────────────────────────────────────────

@new_task
async def anitsu_callback(client, query):
    """Handler único para todos os callbacks do fluxo Anitsu.

    Envolve o dispatcher em um try/except para capturar quaisquer
    exceções inesperadas e registrar traceback completo nos logs.
    """
    try:
        parts = query.data.split(":")
        if len(parts) < 3:
            LOGGER.warning(f"[Anitsu] Callback inválido: {query.data}")
            await query.answer("❌ Dados inválidos", show_alert=True)
            return

        try:
            cb_user_id = int(parts[1])
        except ValueError:
            LOGGER.warning(f"[Anitsu] Não foi possível extrair user_id de: {query.data}")
            await query.answer()
            return

        action = parts[2]
        param = ":".join(parts[3:]) if len(parts) > 3 else ""  # Suporta colons no param
        caller_id = getattr(query.from_user, 'id', None)

        LOGGER.debug(f"[Anitsu] Callback: action={action}, user={cb_user_id}, caller={caller_id}")

        if caller_id != cb_user_id:
            LOGGER.warning(f"[Anitsu] Acesso negado: {caller_id} tentou acessar sessão de {cb_user_id}")
            await query.answer("❌ Esta sessão não é sua.", show_alert=True)
            return

        if cb_user_id not in anitsu_user_state:
            LOGGER.info(f"[Anitsu] Sessão expirada para {cb_user_id}")
            await query.answer("⏱️ Sessão expirada. Use /anitsuleech novamente.", show_alert=True)
            return

        _touch(cb_user_id)
        state = anitsu_user_state[cb_user_id]

        # ── Cancelar ──────────────────────────────
        if action == "cancel":
            LOGGER.info(f"[Anitsu] Cancelando sessão para {cb_user_id}")
            await query.answer()
            await edit_message(query.message, "❌ Operação cancelada.")
            _clear(cb_user_id)
            return

        # ── Noop ──────────────────────────────────
        if action == "noop":
            await query.answer()
            return

        # ── Nova busca ────────────────────────────
        if action == "newsearch":
            await query.answer()
            await edit_message(query.message, "🔍 <b>Nova busca:</b>\nDigite o nome do anime:")
            state["stage"] = "waiting_search"
            return

        # ── Paginação ─────────────────────────────
        if action == "page":
            await query.answer()
            try:
                page = int(param)
            except ValueError:
                return
            state["page"] = page
            results = state.get("search_results", [])
            txt, markup = _search_results_menu(cb_user_id, results, page)
            await edit_message(query.message, txt, markup)
            return

        # ── Seleção de resultado ──────────────────
        if action == "sel":
            await query.answer()
            try:
                idx = int(param)
            except ValueError:
                return
            await _handle_select(query, cb_user_id, state, idx)
            return

        # ── Navegação de pasta ────────────────────
        if action == "nav":
            await query.answer()
            await _navigate_folder(query, cb_user_id, state, param)
            return

        # ── Seleção de arquivo ────────────────────
        if action == "file":
            await query.answer()
            await _handle_file_select(query, cb_user_id, state, param)
            return

        # ── Mirror / Leech ────────────────────────
        if action in ("mirror", "leech"):
            await query.answer()
            await _handle_download_action(query, cb_user_id, state, action, param)
            return

        # ── Voltar ────────────────────────────────
        if action == "back":
            await query.answer()
            await _handle_back(query, cb_user_id, state, param)
            return

        await query.answer()
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro inesperado no callback: {e}")
        try:
            await query.answer("❌ Erro interno. Veja logs para detalhes.", show_alert=True)
        except Exception:
            pass
        return


# ─────────────────────────────────────────────
# Handlers de ações
# ─────────────────────────────────────────────

async def _handle_select(query, user_id: int, state: dict, idx: int):
    """Usuário selecionou um anime da lista de busca."""
    results = state.get("search_results", [])
    if idx >= len(results):
        LOGGER.warning(f"[Anitsu] Índice inválido: {idx} (total: {len(results)})")
        await edit_message(query.message, "❌ Resultado inválido.")
        return

    selected = results[idx]
    path = selected.get("path", "")
    LOGGER.info(f"[Anitsu] Selecionado: {selected.get('name')} -> {path}")
    state["current_path"] = path
    state["breadcrumb"] = [path]

    await _navigate_folder(query, user_id, state, path)


async def _navigate_folder(query, user_id: int, state: dict, path: str):
    """Navega para uma pasta."""
    LOGGER.debug(f"[Anitsu] Navegando para pasta: {path}")
    loading = await edit_message(query.message, f"📂 <b>Carregando...</b> {_truncate(path, 40)}")

    try:
        ac = get_anitsu_client()
        LOGGER.debug(f"[Anitsu] Cliente obtido, chamando list_files({path})...")
        # IMPORTANTE: list_files é assíncrono, deve usar await
        data = await ac.list_files(path)
        LOGGER.debug(f"[Anitsu] Resposta recebida: {type(data)} - {str(data)[:200]}")
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro ao navegar pasta {path}: {e}")
        await edit_message(loading, f"❌ Erro ao acessar pasta: {str(e)[:100]}")
        return

    if not data:
        LOGGER.warning(f"[Anitsu] list_files retornou None ou vazio")
        await edit_message(loading, f"❌ Resposta vazia do servidor")
        return

    if isinstance(data, dict) and "error" in data:
        detail = data.get('detail', 'Erro desconhecido')
        LOGGER.warning(f"[Anitsu] Erro na resposta: {detail}")
        await edit_message(loading, f"❌ {detail}")
        return

    files = data.get("files", [])
    parent = data.get("parent")

    if not files:
        LOGGER.info(f"[Anitsu] Pasta vazia: {path}")
        await edit_message(loading, "📂 Pasta vazia.")
        return

    state["current_path"] = path
    LOGGER.info(f"[Anitsu] Exibindo {len(files)} itens em {path}")
    txt, markup = _folder_menu(user_id, path, files, parent)
    await edit_message(loading, txt, markup)


async def _handle_file_select(query, user_id: int, state: dict, fpath_enc: str):
    """Usuário selecionou um arquivo."""
    import base64
    try:
        fpath = base64.b64decode(fpath_enc).decode()
    except Exception:
        await edit_message(query.message, "❌ Erro ao decodificar caminho do arquivo.")
        return

    loading = await edit_message(query.message, f"🔗 <b>Obtendo info...</b>")

    try:
        ac = get_anitsu_client()
        LOGGER.debug(f"[Anitsu] Obtendo info do arquivo: {fpath}...")
        info = ac.get_download_info(fpath)
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro ao obter info do arquivo: {e}")
        await edit_message(loading, f"❌ Erro: {str(e)[:100]}")
        return

    if not info.get("ok"):
        await edit_message(loading, f"❌ Arquivo inacessível: {info.get('error', 'Desconhecido')}")
        return

    state["selected_file"] = fpath
    state["file_info"] = info
    txt, markup = _file_actions_menu(user_id, fpath, info)
    await edit_message(loading, txt, markup)


async def _handle_download_action(query, user_id: int, state: dict, action: str, fpath_enc: str):
    """Mirror ou Leech o arquivo."""
    import base64
    try:
        fpath = base64.b64decode(fpath_enc).decode()
    except Exception as e:
        LOGGER.error(f"[Anitsu] Erro ao decodificar caminho: {e}")
        await edit_message(query.message, "❌ Erro ao decodificar caminho.")
        return

    try:
        ac = get_anitsu_client()
        url = ac.download_url(fpath)
        LOGGER.info(f"[Anitsu] URL gerada para {action}: {url[:80]}...")
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro ao gerar URL: {e}")
        await edit_message(query.message, f"❌ Erro: {str(e)[:100]}")
        return

    fname = os.path.basename(fpath)
    LOGGER.info(f"[Anitsu] Iniciando {action.upper()} para: {fname}")
    _clear(user_id)

    # Cria uma mensagem falsa com o comando correspondente para chamar o handler nativo
    if action == "mirror":
        fake_text = f"/mirror {url}"
    else:
        fake_text = f"/leech {url}"

    await edit_message(
        query.message,
        f"🚀 <b>Iniciando {action.upper()}:</b>\n\n"
        f"📄 {fname}\n"
        f"🔗 {url[:80]}...\n\n"
        f"<i>Executando: <code>{fake_text}</code></i>"
    )

    # Simula o comando para o handler nativo de mirror/leech
    # IMPORTANTE: isso assume que você tem acesso ao dispatcher do bot
    # e que os handlers de mirror/leech aceitam message.text como entrada
    try:
        from ..modules.mirror_leech import mirror, leech
        message = query.message
        message.text = fake_text

        if action == "mirror":
            LOGGER.debug(f"[Anitsu] Chamando handler de mirror")
            await mirror(None, message)
        else:
            LOGGER.debug(f"[Anitsu] Chamando handler de leech")
            await leech(None, message)
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro ao executar {action}: {e}")
        await send_message(
            query.message.chat.id,
            f"❌ Erro ao iniciar download. Execute manualmente:\n<code>{fake_text}</code>"
        )


async def _handle_back(query, user_id: int, state: dict, target: str):
    """Voltar para etapa anterior."""
    LOGGER.debug(f"[Anitsu] Voltando para: {target}")
    if target == "results":
        # Volta para lista de resultados de busca
        results = state.get("search_results", [])
        page    = state.get("page", 0)
        if not results:
            LOGGER.warning(f"[Anitsu] Tentativa de voltar sem resultados em cache")
            await edit_message(query.message, "❌ Nenhum resultado para voltar.")
            return
        LOGGER.info(f"[Anitsu] Voltando para resultados (página {page})")
        txt, markup = _search_results_menu(user_id, results, page)
        await edit_message(query.message, txt, markup)

    elif target == "folder":
        # Volta para a pasta atual
        path = state.get("current_path", "")
        LOGGER.info(f"[Anitsu] Voltando para pasta: {path}")
        await _navigate_folder(query, user_id, state, path)


# ─────────────────────────────────────────────
# Handler de texto (busca)
# ─────────────────────────────────────────────

@new_task
async def anitsu_message_handler(client, message):
    """Recebe entrada de texto do usuário (busca)."""
    if not message.from_user:
        return
    user_id = message.from_user.id

    # Verifica se há uma sessão ativa para este usuário
    if user_id not in anitsu_user_state:
        return

    state = anitsu_user_state[user_id]
    stage = state.get("stage", "")

    LOGGER.debug(f"[Anitsu] Mensagem recebida de {user_id}, stage={stage}")

    # TTL check
    last_active = state.get("last_active", 0)
    time_diff = time() - last_active
    if time_diff > SESSION_TTL:
        LOGGER.info(f"[Anitsu] Sessão expirada para {user_id} (idle por {time_diff:.0f}s)")
        _clear(user_id)
        await send_message(message, "⏱️ Sessão expirada. Use /anitsuleech novamente.")
        return

    _touch(user_id)

    if stage == "waiting_search":
        LOGGER.debug(f"[Anitsu] Processando busca para {user_id}")
        try:
            await _handle_search(client, message, user_id, state)
        except Exception as e:
            LOGGER.exception(f"[Anitsu] Erro ao processar busca para {user_id}: {e}")
            await send_message(message, f"❌ Erro ao processar busca: {str(e)[:100]}")
            _clear(user_id)
    else:
        LOGGER.debug(f"[Anitsu] Stage '{stage}' não é 'waiting_search', ignorando mensagem")


async def _handle_search(client, message, user_id: int, state: dict):
    """Processa a busca digitada pelo usuário."""
    query = message.text.strip() if message.text else ""
    if not query:
        LOGGER.warning(f"[Anitsu] Usuário {user_id} enviou busca vazia")
        return

    LOGGER.info(f"[Anitsu] Buscando por: {query}")
    loading = await send_message(message, f"🔍 <b>Buscando:</b> {query}...")

    try:
        ac = get_anitsu_client()
        LOGGER.debug(f"[Anitsu] Chamando search({query})...")
        # IMPORTANTE: search é assíncrono, deve usar await
        data = await ac.search(query)
        LOGGER.debug(f"[Anitsu] Resposta de busca: {type(data)} - {str(data)[:200]}")
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro ao buscar {query}: {e}")
        await edit_message(loading, f"❌ Erro na busca: {str(e)[:100]}")
        return

    if not data:
        LOGGER.warning(f"[Anitsu] search retornou None ou vazio para '{query}'")
        b = ButtonMaker()
        b.data_button("🔍 Tentar novamente", f"ant:{user_id}:newsearch")
        b.data_button("❌ Cancelar",         f"ant:{user_id}:cancel")
        await edit_message(loading, f"❌ Resposta vazia do servidor", b.build_menu(1))
        return

    if isinstance(data, dict) and "error" in data:
        detail = data.get("detail", "Erro desconhecido")
        LOGGER.warning(f"[Anitsu] Erro na resposta: {detail}")
        b = ButtonMaker()
        b.data_button("🔍 Tentar novamente", f"ant:{user_id}:newsearch")
        b.data_button("❌ Cancelar",         f"ant:{user_id}:cancel")
        await edit_message(loading, f"❌ {detail}", b.build_menu(1))
        return

    results = data.get("results", [])
    if not results:
        LOGGER.info(f"[Anitsu] Nenhum resultado para '{query}'")
        b = ButtonMaker()
        b.data_button("🔍 Tentar novamente", f"ant:{user_id}:newsearch")
        b.data_button("❌ Cancelar",         f"ant:{user_id}:cancel")
        await edit_message(loading, f"❌ Nenhum resultado para <b>{query}</b>", b.build_menu(1))
        return

    state["search_query"]   = query
    state["search_results"] = results
    state["page"] = 0
    state["stage"] = "results"

    LOGGER.info(f"[Anitsu] Encontrados {len(results)} resultados para '{query}'")
    txt, markup = _search_results_menu(user_id, results, 0)
    await edit_message(loading, txt, markup)
    state["active_msg_id"] = loading.id
