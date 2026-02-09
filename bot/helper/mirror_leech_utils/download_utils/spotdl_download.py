from logging import getLogger
from os import path as ospath, makedirs, remove, listdir
from secrets import token_hex
from contextlib import suppress
from shutil import rmtree
import gc

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
        
        # Spotdl client - será criado em cada download
        self.spotdl_client = None
        self.download_path = None
        
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

    def _cleanup_client(self):
        """Force cleanup of Spotdl client and reset singleton"""
        if self.spotdl_client:
            try:
                # Limpar downloader
                if hasattr(self.spotdl_client, 'downloader'):
                    self.spotdl_client.downloader = None
                
                # Limpar client_id e client_secret
                if hasattr(self.spotdl_client, 'client_id'):
                    self.spotdl_client.client_id = None
                if hasattr(self.spotdl_client, 'client_secret'):
                    self.spotdl_client.client_secret = None
                
                # ✅ CRÍTICO: Reset do singleton do Spotdl
                # O Spotdl usa uma variável de classe _instance para singleton
                if hasattr(Spotdl, '_instance'):
                    Spotdl._instance = None
                
                # Remover referência
                self.spotdl_client = None
                
                # Forçar garbage collection
                gc.collect()
                
                LOGGER.info("✅ Spotdl client cleaned up successfully")
            except Exception as e:
                LOGGER.error(f"Error cleaning up Spotdl client: {e}")

    def _on_download_progress(self, progress_handler):
        """Callback for download progress"""
        if self._listener.is_cancelled:
            raise ValueError("Cancelling...")

    async def _on_download_start(self, from_queue=False):
        async with task_dict_lock:
            task_dict[self._listener.mid] = SpotdlStatus(self._listener, self, self._gid)
        if not from_queue:
            await self._listener.on_download_start()
            if self._listener.multi <= 1:
                await send_status_message(self._listener.message)

    def _on_download_error(self, error):
        self._listener.is_cancelled = True
        self._cleanup_client()  # Cleanup ao dar erro
        async_to_sync(self._listener.on_download_error, error)

    def _extract_meta_data(self, link):
        """Extract metadata from Spotify link"""
        try:
            # ✅ Limpar cliente anterior antes de criar novo
            self._cleanup_client()
            
            ffmpeg_path = get_ffmpeg_path()
            
            # ✅ Criar NOVO cliente
            LOGGER.info("Creating new Spotdl client...")
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
            LOGGER.info("✅ Spotdl client created successfully")
            
            # Get songs from link
            LOGGER.info(f"Searching Spotify link: {link}")
            songs = self.spotdl_client.search([link])
            
            if not songs:
                raise ValueError("No songs found in Spotify link")
            
            # Contagem correta
            self.total_songs = len(songs)
            self.playlist_count = 0
            
            LOGGER.info(f"Found {self.total_songs} song(s)")
            
            # Check if playlist
            if len(songs) > 1:
                self.is_playlist = True
                
            # Calculate total size (estimate: 320kbps * duration)
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
            
            # Criar diretório se não existir
            if not ospath.exists(path):
                makedirs(path, exist_ok=True)
                LOGGER.info(f"Created download directory: {path}")
            
            # Create output path for playlist
            if self.is_playlist:
                output_path = ospath.join(path, self._listener.name)
                makedirs(output_path, exist_ok=True)
            else:
                output_path = path
            
            self.download_path = output_path
            
            LOGGER.info(f"Downloading {len(songs)} song(s) to: {output_path}")
            
            # Download songs one by one
            for idx, song in enumerate(songs, 1):
                if self._listener.is_cancelled:
                    LOGGER.info(f"Download cancelled by user at {idx}/{len(songs)}")
                    break
                    
                try:
                    LOGGER.info(f"[{idx}/{len(songs)}] Downloading: {song.name}")
                    
                    # Download individual song
                    result, error = self.spotdl_client.downloader.download_song(song)
                    
                    if result:
                        self.playlist_count += 1
                        LOGGER.info(f"✅ [{self.playlist_count}/{len(songs)}] Downloaded: {song.name}")
                    else:
                        LOGGER.error(f"❌ Failed to download {song.name}: {error}")
                    
                except Exception as e:
                    LOGGER.error(f"❌ Error downloading {song.name}: {e}")
                    continue
            
            if self._listener.is_cancelled:
                return
            
            LOGGER.info(f"Download complete: {self.playlist_count}/{len(songs)} songs downloaded")
            
            # Chamar on_download_complete SOMENTE se baixou algo
            if self.playlist_count > 0:
                async_to_sync(self._listener.on_download_complete)
            else:
                self._on_download_error("No songs were downloaded successfully")
            
        except Exception as e:
            LOGGER.error(f"Download error: {e}")
            if not self._listener.is_cancelled:
                self._on_download_error(str(e))
        finally:
            # ✅ SEMPRE limpar cliente após download
            self._cleanup_client()

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
        self._cleanup_client()
        
        await self._listener.on_download_error("Stopped by User!")
