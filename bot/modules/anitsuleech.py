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
    from ..helper.ext_utils.anitsu_client import AnitsuClient, get_anitsu_client, refresh_anitsu_client
except Exception as e:
    # Fallback se o cliente não estiver integrado ainda — registrar exceção completa
    LOGGER.exception("anitsu_client não encontrado ou erro ao importar — /anitsuleech não funcionará: %s", e)
    AnitsuClient = None
    get_anitsu_client = None
    refresh_anitsu_client = None


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


async def _get_anitsu_client_for_user(user_id: int):
    """
    Get Anitsu client for a specific user.
    
    Tries to use user-specific cookie if available, falls back to global client.
    
    Args:
        user_id: Telegram user ID
        
    Returns:
        AnitsuClient instance
        
    Raises:
        Exception: If client cannot be initialized
    """
    from .. import user_data
    
    user_cookie_file = None
    if user_id in user_data and "USER_COOKIE_FILE" in user_data[user_id]:
        user_cookie_file = user_data[user_id].get("USER_COOKIE_FILE")
        LOGGER.debug(f"[Anitsu] Cookie file do usuário {user_id} encontrado: {user_cookie_file}")
    
    try:
        if user_cookie_file:
            return get_anitsu_client(cookie_file=user_cookie_file)
        else:
            return get_anitsu_client()
    except Exception as e:
        LOGGER.error(f"[Anitsu] Erro ao obter cliente para usuário {user_id}: {e}")
        raise


def _truncate(path: str, maxlen: int = MAX_PATH_LEN) -> str:
    """Trunca paths longos mantendo início e fim."""
    if len(path) <= maxlen:
        return path
    half = (maxlen - 3) // 2
    return f"{path[:half]}...{path[-half:]}"


def _safe_filename(name: str) -> str:
    """Remove caracteres inválidos de nomes de arquivo."""
    return re.sub(r'[^\w\s\-\.]', '_', name, flags=re.UNICODE).strip()


def parse_file_range(input_str: str) -> tuple[int, int] | tuple[None, None]:
    """
    Parse file range input (e.g., "1-10" or "5").
    
    Args:
        input_str: Range string
        
    Returns:
        Tuple of (start_idx, end_idx) or (None, None) if invalid
    """
    try:
        if "-" in input_str:
            parts = input_str.split("-")
            if len(parts) != 2:
                return None, None
            start = int(parts[0].strip())
            end = int(parts[1].strip())
            if start > 0 and end > 0 and start <= end:
                return start - 1, end - 1  # Converte para 0-based
            return None, None
        else:
            num = int(input_str.strip())
            if num > 0:
                return num - 1, num - 1  # Single file
            return None, None
    except ValueError:
        return None, None


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
    """Menu de navegação de pasta - mostra pastas e lista de arquivos."""
    folders = [f for f in files if f.get("is_directory")]
    docs    = [f for f in files if not f.get("is_directory")]

    b = ButtonMaker()

    # Prepare um mapa curto de callback ids para evitar callback_data muito longo
    user_state = anitsu_user_state.setdefault(user_id, {})
    cb_map = user_state.setdefault("cb_map", {})
    cb_counter = user_state.get("_cb_counter", 0)

    def _store_cb(val: str) -> str:
        nonlocal cb_counter
        cb_counter += 1
        key = f"c{cb_counter}"
        cb_map[key] = val
        user_state["_cb_counter"] = cb_counter
        return key

    # Pastas (armazenamos subpath no mapa e usamos id curto no callback)
    for folder in folders:
        fname = folder["name"][:40]
        subpath = f"{path}/{folder['name']}" if path else folder["name"]
        key = _store_cb(subpath)
        b.data_button(f"📁 {fname}", f"ant:{user_id}:navid:{key}")

    # Controles
    if parent is not None:
        # parent pode ser longo — usar cb_map
        if parent:
            pkey = _store_cb(parent)
            b.data_button("↩ Voltar", f"ant:{user_id}:navid:{pkey}")
        else:
            b.data_button("↩ Voltar", f"ant:{user_id}:back:results")
    b.data_button("🔍 Nova busca", f"ant:{user_id}:newsearch")
    b.data_button("❌ Cancelar",   f"ant:{user_id}:cancel")

    path_display = _truncate(path or "/", 60)
    msg = f"📂 <b>{path_display}</b>\n\n"
    
    if folders:
        msg += f"📁 <b>Pastas:</b> {len(folders)}\n"
    
    if docs:
        msg += f"🎬 <b>Arquivos:</b> {len(docs)}\n\n"
        # Lista os primeiros 15 arquivos como exemplo
        msg += "<u>Arquivos encontrados:</u>\n"
        for i, doc in enumerate(docs[:15], 1):
            fname = doc["name"][:50]
            msg += f"{i}. {fname}\n"
        if len(docs) > 15:
            msg += f"... e mais {len(docs) - 15}\n"
        msg += f"\n📌 <b>Digite o intervalo:</b> Ex: 1-5 · 10 · 1-{len(docs)} · todos"
    else:
        msg += "❌ Nenhum arquivo nesta pasta"
    
    return msg, b.build_menu(1)


def _file_actions_menu(user_id: int, filepaths: list[str], sizes: list[int]) -> tuple:
    """Menu de ações para um ou mais arquivos."""
    b = ButtonMaker()
    b.data_button("🔗 Mirror",  f"ant:{user_id}:act:mirror")
    b.data_button("📥 Leech",   f"ant:{user_id}:act:leech")
    b.data_button("↩ Voltar",   f"ant:{user_id}:back:folder")
    b.data_button("❌ Cancelar", f"ant:{user_id}:cancel")

    if len(filepaths) == 1:
        fname = os.path.basename(filepaths[0])[:60]
        size  = get_readable_file_size(sizes[0])
        msg = f"📄 <b>{fname}</b>\n\n💾 Tamanho: {size}"
    else:
        total_size = sum(sizes)
        msg = f"📦 <b>Selecionados {len(filepaths)} arquivo(s)</b>\n\n💾 Tamanho total: {get_readable_file_size(total_size)}"
    
    msg += "\n\n<b>Escolha a ação:</b>"
    return msg, b.build_menu(2)


# ─────────────────────────────────────────────
# Comando principal
# ─────────────────────────────────────────────

@new_task
async def anitsuleech(client, message):
    """Ponto de entrada: /anitsuleech"""
    from .. import user_data
    
    # Verifica se o cliente está disponível
    if not get_anitsu_client:
        LOGGER.error("[Anitsu] Client function não disponível - import falhou")
        await send_message(message, "❌ Anitsu client não configurado. Contate o admin.")
        return

    user = message.from_user
    if not user:
        LOGGER.warning("[Anitsu] Mensagem sem usuário")
        return
    user_id = user.id

    # Tenta obter arquivo de cookie do usuário se disponível
    user_cookie_file = None
    if user_id in user_data and "USER_COOKIE_FILE" in user_data[user_id]:
        user_cookie_file = user_data[user_id].get("USER_COOKIE_FILE")
        LOGGER.debug(f"[Anitsu] Cookie file do usuário encontrado: {user_cookie_file}")

    # Tenta instanciar o cliente
    try:
        LOGGER.info(f"[Anitsu] Inicializando cliente Anitsu para usuário {user_id}")
        ac = get_anitsu_client(cookie_file=user_cookie_file) if user_cookie_file else get_anitsu_client()
        LOGGER.info(f"[Anitsu] Cliente inicializado com sucesso de: {ac.cookie_file}")
    except FileNotFoundError as e:
        LOGGER.error(f"[Anitsu] Arquivo de cookies não encontrado: {e}")
        msg = (
            "❌ **Anitsu Cookie não configurado**\n\n"
            "Para usar este comando, você precisa configurar os cookies do Anitsu.\n\n"
            "**Opções:**\n"
            "1. Use `/bsettings` → **Private Files** → **Add/Delete File**\n"
            "2. Envie o arquivo `anitsu_cookies.txt` (exportado do navegador)\n\n"
            "**Como exportar cookies:**\n"
            "- Use uma extensão do navegador (ex: \"Cookie Editor\")\n"
            "- Exporte no formato Netscape (o padrão)\n"
            "- Envie via botset private"
        )
        await send_message(message, msg)
        return
    except RuntimeError as e:
        LOGGER.error(f"[Anitsu] Erro ao inicializar cliente: {e}")
        await send_message(message, f"❌ Erro ao inicializar Anitsu: {str(e)}")
        return
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro inesperado ao inicializar: {e}")
        await send_message(message, f"❌ Erro ao inicializar Anitsu: {str(e)}")
        return

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
        if action in ("nav", "navid"):
            await query.answer()
            real_param = param
            if action == "navid":
                real_param = state.get("cb_map", {}).get(param)
                if real_param is None:
                    LOGGER.warning(f"[Anitsu] Callback id não encontrado: {param}")
                    await query.answer("❌ Dados inválidos", show_alert=True)
                    return
            await _navigate_folder(query, cb_user_id, state, real_param)
            return

        # ── Ações após seleção de intervalo ──────
        if action == "act":
            await query.answer()
            await _handle_file_action(query, cb_user_id, state, param)
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
        ac = await _get_anitsu_client_for_user(user_id)
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
    state["folder_files"] = files  # Armazena lista de arquivos para seleção
    LOGGER.info(f"[Anitsu] Exibindo {len(files)} itens em {path}")
    txt, markup = _folder_menu(user_id, path, files, parent)
    await edit_message(loading, txt, markup)
    state["stage"] = "file_selection"  # Aguardando entrada do usuário


async def _handle_file_selection(query, user_id: int, state: dict, range_input: str):
    """Usuário selecionou um intervalo de arquivos."""
    files = state.get("folder_files", [])
    docs = [f for f in files if not f.get("is_directory")]
    
    if not docs:
        await edit_message(query.message, "❌ Nenhum arquivo na pasta.")
        return
    
    # Parse do intervalo
    if range_input.lower() == "todos":
        start_idx, end_idx = 0, len(docs) - 1
    else:
        start_idx, end_idx = parse_file_range(range_input)
        if start_idx is None or end_idx >= len(docs) or start_idx >= len(docs):
            await edit_message(
                query.message,
                f"❌ Intervalo inválido. Tente 1-{len(docs)}, ou uma número único."
            )
            return
    
    selected_files = docs[start_idx:end_idx + 1]
    path = state.get("current_path", "")
    
    # Constrói paths completos e obtém tamanhos
    filepaths = []
    sizes = []
    for doc in selected_files:
        fpath = f"{path}/{doc['name']}" if path else doc["name"]
        filepaths.append(fpath)
        sizes.append(doc.get("size", 0))
    
    LOGGER.info(f"[Anitsu] Usuário {user_id} selecionou {len(filepaths)} arquivo(s)")
    state["selected_files"] = filepaths
    state["selected_sizes"] = sizes
    state["stage"] = "file_action"
    
    txt, markup = _file_actions_menu(user_id, filepaths, sizes)
    await edit_message(query.message, txt, markup)


async def _handle_file_action(query, user_id: int, state: dict, action: str):
    """Processa ação de mirror/leech para múltiplos arquivos selecionados."""
    if action not in ("mirror", "leech"):
        return
    
    filepaths = state.get("selected_files", [])
    
    if not filepaths:
        await edit_message(query.message, "❌ Nenhum arquivo selecionado.")
        return
    
    LOGGER.info(f"[Anitsu] Iniciando {action.upper()} para {len(filepaths)} arquivo(s): {filepaths}")
    _clear(user_id)
    
    # Gera URLs para todos os arquivos
    try:
        ac = await _get_anitsu_client_for_user(user_id)
        urls = [ac.download_url(fpath) for fpath in filepaths]
        LOGGER.info(f"[Anitsu] {len(urls)} URL(s) gerada(s)")
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro ao gerar URLs: {e}")
        await edit_message(query.message, f"❌ Erro ao gerar URLs: {str(e)[:100]}")
        return
    
    # Cria comando com todas as URLs
    urls_text = " ".join(urls)
    if action == "mirror":
        fake_text = f"/mirror {urls_text}"
    else:
        fake_text = f"/leech {urls_text}"
    
    # Mostra resumo da ação
    file_list = "\n".join([os.path.basename(f) for f in filepaths[:5]])
    if len(filepaths) > 5:
        file_list += f"\n... e mais {len(filepaths) - 5}"
    
    await edit_message(
        query.message,
        f"🚀 <b>Iniciando {action.upper()}:</b>\n\n"
        f"📦 Arquivos:\n{file_list}\n\n"
        f"<i>Processando {len(filepaths)} arquivo(s)...</i>"
    )
    
    # Chama handlers nativos de mirror/leech
    try:
        from ..modules.mirror_leech import mirror, leech
        message = query.message
        message.text = fake_text
        
        LOGGER.debug(f"[Anitsu] Chamando handler de {action} com {len(urls)} URL(s)")
        if action == "mirror":
            await mirror(None, message)
        else:
            await leech(None, message)
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro ao chamar handler de {action}: {e}")
        await edit_message(query.message, f"❌ Erro ao iniciar {action}: {str(e)[:100]}")


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
        ac = await _get_anitsu_client_for_user(user_id)
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
    elif stage == "file_selection":
        LOGGER.debug(f"[Anitsu] Processando seleção de arquivos para {user_id}")
        try:
            range_input = message.text.strip() if message.text else ""
            if not range_input:
                await send_message(message, "❌ Digite um intervalo válido. Ex: 1-5 · 10 · todos")
                return
            # Cria um objeto query fake para compatibilidade com _handle_file_selection
            class FakeQuery:
                def __init__(self, msg):
                    self.message = msg
            fake_query = FakeQuery(message)
            await _handle_file_selection(fake_query, user_id, state, range_input)
        except Exception as e:
            LOGGER.exception(f"[Anitsu] Erro ao processar seleção de arquivos para {user_id}: {e}")
            await send_message(message, f"❌ Erro ao processar seleção: {str(e)[:100]}")
            _clear(user_id)
    else:
        LOGGER.debug(f"[Anitsu] Stage '{stage}' não é 'waiting_search' ou 'file_selection', ignorando mensagem")


async def _handle_search(client, message, user_id: int, state: dict):
    """Processa a busca digitada pelo usuário."""
    query = message.text.strip() if message.text else ""
    if not query:
        LOGGER.warning(f"[Anitsu] Usuário {user_id} enviou busca vazia")
        return

    LOGGER.info(f"[Anitsu] Buscando por: {query}")
    loading = await send_message(message, f"🔍 <b>Buscando:</b> {query}...")

    try:
        ac = await _get_anitsu_client_for_user(user_id)
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


# ─────────────────────────────────────────────
# Comando de Refresh de Cookies
# ─────────────────────────────────────────────

@new_task
async def anitsurefresh(client, message):
    """Recarrega cookies do Anitsu."""
    from .. import user_data
    
    user = message.from_user
    if not user:
        return
    user_id = user.id

    try:
        # Procura arquivo de cookie do usuário
        user_cookie_file = None
        if user_id in user_data and "USER_COOKIE_FILE" in user_data[user_id]:
            user_cookie_file = user_data[user_id].get("USER_COOKIE_FILE")

        # Recarrega cookies
        if get_anitsu_client:
            LOGGER.info(f"[Anitsu] Recarregando cookies para usuário {user_id}")
            refresh_anitsu_client(cookie_file=user_cookie_file)
            await send_message(message, "✅ Cookies do Anitsu recarregados com sucesso!")
        else:
            await send_message(message, "❌ Anitsu client não disponível")
    except Exception as e:
        LOGGER.exception(f"[Anitsu] Erro ao recarregar cookies: {e}")
        await send_message(
            message,
            f"❌ Erro ao recarregar cookies:\n\n<code>{str(e)}</code>\n\n"
            "Verifique se o arquivo de cookies existe e é válido."
        )

