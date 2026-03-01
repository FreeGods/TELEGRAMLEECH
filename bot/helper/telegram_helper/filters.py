from pyrogram.filters import create
from pyrogram.enums import ChatType

from ... import auth_chats, sudo_users, user_data
from ...core.config_manager import Config
from .tg_utils import chat_info


class CustomFilters:
    async def owner_filter(self, _, update):
        user = update.from_user or update.sender_chat
        return user.id == Config.OWNER_ID

    owner = create(owner_filter)

    async def authorized_user(self, _, update):
        uid = (update.from_user or update.sender_chat).id
        chat_id = update.chat.id
        thread_id = update.message_thread_id if update.is_topic_message else None
        return bool(
            uid == Config.OWNER_ID
            or (
                uid in user_data
                and (
                    user_data[uid].get("AUTH", False)
                    or user_data[uid].get("SUDO", False)
                )
            )
            or (
                chat_id in user_data
                and user_data[chat_id].get("AUTH", False)
                and (
                    thread_id is None
                    or thread_id in user_data[chat_id].get("thread_ids", [])
                )
            )
            or uid in sudo_users
            or uid in auth_chats
            or chat_id in auth_chats
            and (
                auth_chats[chat_id]
                and thread_id
                and thread_id in auth_chats[chat_id]
                or not auth_chats[chat_id]
            )
        )

    authorized = create(authorized_user)

    async def authorized_usetting(self, _, update):
        uid = (update.from_user or update.sender_chat).id
        is_exists = False
        if await CustomFilters.authorized("", update):
            is_exists = True
        elif update.chat.type == ChatType.PRIVATE:
            for channel_id in user_data:
                if not (
                    user_data[channel_id].get("is_auth")
                    and str(channel_id).startswith("-100")
                ):
                    continue
                try:
                    if await (await chat_info(str(channel_id))).get_member(uid):
                        is_exists = True
                        break
                except Exception:
                    continue
        return is_exists

    authorized_uset = create(authorized_usetting)

    async def sudo_user(self, _, update):
        user = update.from_user or update.sender_chat
        uid = user.id
        return bool(
            uid == Config.OWNER_ID
            or uid in user_data
            and user_data[uid].get("SUDO")
            or uid in sudo_users
        )

    sudo = create(sudo_user)
    async def anitsu_session_active(self, _, update):
        """Filter que retorna True apenas se há uma sessão ativa do anitsu para o usuário"""
        from ...modules.anitsuleech import anitsu_user_state
        user_id = (update.from_user or update.sender_chat).id
        return user_id in anitsu_user_state

    anitsu_session = create(anitsu_session_active)

    async def manga_session_active(self, _, update):
        """Filter que retorna True apenas se há uma sessão ativa do mangaleech para o usuário"""
        from ...modules.mangaleech import manga_user_state
        user_id = (update.from_user or update.sender_chat).id
        return user_id in manga_user_state

    manga_session = create(manga_session_active)

    async def novel_session_active(self, _, update):
        """Filter que retorna True apenas se há uma sessão ativa do novelleech para o usuário"""
        from ...modules.novelleech import novel_user_state
        user_id = (update.from_user or update.sender_chat).id
        return user_id in novel_user_state

    novel_session = create(novel_session_active)