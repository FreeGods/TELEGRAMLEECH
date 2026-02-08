from logging import getLogger
from os import path as ospath, listdir
from secrets import token_hex
from contextlib import suppress

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


class MyLogger:
    def __init__(self, obj, listener):
        self._obj = obj
        self._listener = listener

    def debug(self, msg):
        LOGGER.debug(msg)

    def info(self, msg):
        LOGGER.info(msg)
        if "Downloaded" in msg:
            self._obj.playlist_count += 1

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
        
        # Spotdl settings
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
        return self._progress

    @property
    def eta(self):
        return self._eta

    def _on_download_progress(self, progress_handler):
        """Callback for download progress"""
        if self._listener.is_cancelled:
            raise ValueError("Cancelling...")
        
        current = progress_handler.overall_completed_tasks
        total = progress_handler.overall_total_tasks
        
        if total > 0:
            self._progress = (current / total) * 100
            
        # Estimate download speed and bytes (spotdl doesn't provide this directly)
        if self.is_playlist:
            self.playlist_count = current

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
            # Initialize Spotdl client
            settings = {
                'audio_providers': ['youtube-music'],
                'lyrics_providers': ['genius', 'musixmatch', 'azlyrics'],
                'ffmpeg': BinConfig.FFMPEG_NAME or 'ffmpeg',
                'bitrate': '320k',
                'format': 'mp3',
                'threads': 4,
            }
            
            self.spotdl_client = Spotdl(client_id=None, client_secret=None, **settings)
            
            # Get songs from link
            songs = self.spotdl_client.search([link])
            
            if not songs:
                raise ValueError("No songs found in Spotify link")
            
            # Check if playlist
            if len(songs) > 1:
                self.is_playlist = True
                self.playlist_count = len(songs)
                
            # Calculate total size (estimate: 320kbps * duration)
            total_size = 0
            for song in songs:
                if hasattr(song, 'duration') and song.duration:
                    # 320kbps = 40KB/s, convert seconds to bytes
                    total_size += int(song.duration * 40000)
            
            self._listener.size = total_size
            
            if not self._listener.name:
                if self.is_playlist:
                    # Get playlist name from first song's album/playlist
                    if hasattr(songs[0], 'album_name'):
                        self._listener.name = songs[0].album_name
                    else:
                        self._listener.name = f"Spotify_Playlist_{self.playlist_count}_songs"
                else:
                    # Single song
                    song = songs[0]
                    self._listener.name = f"{song.artist} - {song.name}.mp3"
                    
            return songs
            
        except Exception as e:
            self._on_download_error(str(e))
            return None

    def _download(self, path, songs):
        """Download songs using spotdl"""
        try:
            if not songs:
                raise ValueError("No songs to download")
            
            # Create output path
            output_path = path
            if self.is_playlist:
                output_path = ospath.join(path, self._listener.name)
            
            # Download songs
            results = self.spotdl_client.download_songs(songs, output=output_path)
            
            # Check for errors
            failed = [r for r in results if r is None or isinstance(r, Exception)]
            if failed and not self._listener.is_cancelled:
                LOGGER.warning(f"Failed to download {len(failed)} songs")
            
            if self._listener.is_cancelled:
                return
                
            async_to_sync(self._listener.on_download_complete)
            
        except Exception as e:
            if not self._listener.is_cancelled:
                self._on_download_error(str(e))
        finally:
            if self.spotdl_client:
                with suppress(Exception):
                    self.spotdl_client = None

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

        if limit_exceeded := await limit_checker(self._listener, self.playlist_count):
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
        await self._listener.on_download_error("Stopped by User!")
