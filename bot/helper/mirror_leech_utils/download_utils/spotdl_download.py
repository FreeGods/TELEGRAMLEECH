from logging import getLogger
from os import path as ospath, makedirs, listdir, walk
from secrets import token_hex
from contextlib import suppress
from shutil import move

from spotdl import Spotdl
from spotdl.types.song import Song

from .... import task_dict_lock, task_dict
from ....core.config_manager import BinConfig, Config
from ...ext_utils.bot_utils import sync_to_async, async_to_sync
from ...ext_utils.task_manager import (
    check_running_tasks,
    stop_duplicate_check,
    limit_checker,
)
from ...mirror_leech_utils.status_utils.queue_status import QueueStatus
from ...telegram_helper.message_utils import send_status_message
from ..status_utils.spotdl_status import SpotdlStatus

LOGGER = getLogger(__name__)


def get_ffmpeg_path():
    """Get FFmpeg path - tries imageio-ffmpeg first, then system ffmpeg"""
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg_path = get_ffmpeg_exe()
        LOGGER.info(f"Using FFmpeg from imageio-ffmpeg: {ffmpeg_path}")
        return ffmpeg_path
    except ImportError:
        LOGGER.warning("imageio-ffmpeg not found, trying system ffmpeg")
        return BinConfig.FFMPEG_NAME if hasattr(BinConfig, 'FFMPEG_NAME') else 'ffmpeg'


class MyLogger:
    def __init__(self, obj, listener):
        self._obj = obj
        self._listener = listener

    def debug(self, msg):
        LOGGER.debug(msg)

    def info(self, msg):
        LOGGER.info(msg)

    def warning(self, msg):
        LOGGER.warning(msg)

    def error(self, msg):
        if msg != "ERROR: Cancelling...":
            LOGGER.error(msg)


class SpotdlHelper:
    def __init__(self, listener):
        self._last_downloaded = 0
        self._progress = 0
        self._downloaded_bytes = 0
        self._download_speed = 0
        self._eta = "-"
        self._listener = listener
        self._gid = ""
        self.is_playlist = False
        self.playlist_count = 0
        self.total_songs = 0
        
        # Spotdl client
        self.spotdl_client = None
        
    @property
    def download_speed(self):
        return self._download_speed

    @property
    def downloaded_bytes(self):
        return self._downloaded_bytes

    @property
    def size(self):
        return self._listener.size

    @property
    def progress(self):
        try:
            if self.total_songs > 0:
                return (self.playlist_count / self.total_songs) * 100
            return self._progress
        except:
            return 0

    @property
    def eta(self):
        return self._eta

    async def _on_download_start(self, from_queue=False):
        async with task_dict_lock:
            task_dict[self._listener.mid] = SpotdlStatus(self._listener, self, self._gid)
        if not from_queue:
            await self._listener.on_download_start()
            if self._listener.multi <= 1:
                await send_status_message(self._listener.message)

    def _on_download_error(self, error):
        self._listener.is_cancelled = True
        async_to_sync(self._listener.on_download_error, error)

    def _extract_meta_data(self, link):
        """Extract metadata from Spotify link"""
        try:
            ffmpeg_path = get_ffmpeg_path()
            
            # ✅ Criar NOVO cliente para cada download
            self.spotdl_client = Spotdl(
                client_id=None,
                client_secret=None,
                headless=True,
                downloader_settings={
                    'ffmpeg': ffmpeg_path,
                    'bitrate': '320k',
                    'format': 'mp3',
                    'threads': 4,
                }
            )
            
            # Get songs from link
            songs = self.spotdl_client.search([link])
            
            if not songs:
                raise ValueError("No songs found in Spotify link")
            
            # Contagem correta
            self.total_songs = len(songs)
            self.playlist_count = 0
            
            # Check if playlist
            if len(songs) > 1:
                self.is_playlist = True
                
            # Calculate total size
            total_size = 0
            for song in songs:
                if hasattr(song, 'duration') and song.duration:
                    total_size += int(song.duration * 40000)
            
            self._listener.size = total_size if total_size > 0 else 1024 * 1024
            
            if not self._listener.name:
                if self.is_playlist:
                    if hasattr(songs[0], 'album_name') and songs[0].album_name:
                        self._listener.name = songs[0].album_name
                    elif hasattr(songs[0], 'list_name') and songs[0].list_name:
                        self._listener.name = songs[0].list_name
                    else:
                        self._listener.name = f"Spotify_Playlist_{self.total_songs}_songs"
                else:
                    song = songs[0]
                    artist = song.artist if hasattr(song, 'artist') else 'Unknown'
                    name = song.name if hasattr(song, 'name') else 'Unknown'
                    self._listener.name = f"{artist} - {name}.mp3"
                    
            return songs
            
        except Exception as e:
            LOGGER.error(f"Error extracting metadata: {e}")
            self._on_download_error(str(e))
            return None

    def _download(self, path, songs):
        """Download songs using spotdl"""
        try:
            if not songs:
                raise ValueError("No songs to download")
            
            # ✅ CORREÇÃO CRÍTICA: Criar diretório ANTES
            if not ospath.exists(path):
                makedirs(path, exist_ok=True)
                LOGGER.info(f"Created download directory: {path}")
            
            # ✅ CORREÇÃO: spotdl usa diretório atual por padrão
            # Precisamos definir output explicitamente
            
            LOGGER.info(f"Download path: {path}")
            LOGGER.info(f"Downloading {len(songs)} song(s)")
            
            # ✅ Download usando método correto
            downloaded_files = []
            
            for idx, song in enumerate(songs, 1):
                if self._listener.is_cancelled:
                    LOGGER.info(f"Download cancelled by user at {idx}/{len(songs)}")
                    break
                    
                try:
                    LOGGER.info(f"[{idx}/{len(songs)}] Downloading: {song.name} - {song.artist}")
                    
                    # ✅ CORREÇÃO: Baixar diretamente para o path correto
                    # spotdl salva no diretório de trabalho atual, precisamos setar output
                    self.spotdl_client.downloader.settings['output'] = path
                    
                    # Download individual song
                    result, error = self.spotdl_client.downloader.download_song(song)
                    
                    if result:
                        self.playlist_count += 1
                        # ✅ Registrar arquivo baixado
                        if ospath.exists(result):
                            downloaded_files.append(result)
                            LOGGER.info(f"✅ [{self.playlist_count}/{len(songs)}] Downloaded: {result}")
                        else:
                            LOGGER.warning(f"⚠️ File reported as downloaded but not found: {result}")
                    else:
                        LOGGER.error(f"❌ Failed to download {song.name}: {error}")
                    
                except Exception as e:
                    LOGGER.error(f"❌ Error downloading {song.name}: {e}")
                    continue
            
            if self._listener.is_cancelled:
                return
            
            LOGGER.info(f"Download complete: {self.playlist_count}/{len(songs)} songs")
            LOGGER.info(f"Downloaded files: {downloaded_files}")
            
            # ✅ VERIFICAÇÃO: Listar o que realmente está no diretório
            if ospath.exists(path):
                actual_files = []
                for root, dirs, files in walk(path):
                    for file in files:
                        if file.endswith('.mp3'):
                            full_path = ospath.join(root, file)
                            actual_files.append(full_path)
                
                LOGGER.info(f"Actual files in {path}: {actual_files}")
                
                # Se temos arquivos mas spotdl não retornou paths, usar os encontrados
                if actual_files and not downloaded_files:
                    downloaded_files = actual_files
                    self.playlist_count = len(actual_files)
                    LOGGER.info(f"Using discovered files: {len(actual_files)} files")
            
            # ✅ Chamar on_download_complete SOMENTE se baixou algo
            if self.playlist_count > 0:
                async_to_sync(self._listener.on_download_complete)
            else:
                self._on_download_error("No songs were downloaded successfully")
            
        except Exception as e:
            LOGGER.error(f"Download error: {e}", exc_info=True)
            if not self._listener.is_cancelled:
                self._on_download_error(str(e))
        finally:
            # Limpar cliente
            if self.spotdl_client:
                with suppress(Exception):
                    self.spotdl_client = None
                    LOGGER.info("Spotdl client cleaned up")

    async def add_download(self, path):
        self._gid = token_hex(5)

        await self._on_download_start()

        # Extract metadata
        songs = await sync_to_async(self._extract_meta_data, self._listener.link)
        if not songs or self._listener.is_cancelled:
            return

        # Check for duplicates and limits
        msg, button = await stop_duplicate_check(self._listener)
        if msg:
            await self._listener.on_download_error(msg, button)
            return

        if limit_exceeded := await limit_checker(self._listener, self.total_songs):
            await self._listener.on_download_error(limit_exceeded, is_limit=True)
            return

        # Check if should queue
        add_to_queue, event = await check_running_tasks(self._listener)
        if add_to_queue:
            LOGGER.info(f"Added to Queue/Download: {self._listener.name}")
            async with task_dict_lock:
                task_dict[self._listener.mid] = QueueStatus(
                    self._listener, self._gid, "dl"
                )
            await event.wait()
            if self._listener.is_cancelled:
                return
            LOGGER.info(f"Start Queued Download from Spotify: {self._listener.name}")
            await self._on_download_start(True)

        if not add_to_queue:
            LOGGER.info(f"Download from Spotify: {self._listener.name}")

        # Start download
        await sync_to_async(self._download, path, songs)

    async def cancel_task(self):
        self._listener.is_cancelled = True
        LOGGER.info(f"Cancelling Spotify Download: {self._listener.name}")
        
        # Cleanup client
        if self.spotdl_client:
            with suppress(Exception):
                self.spotdl_client = None
        
        await self._listener.on_download_error("Stopped by User!")
