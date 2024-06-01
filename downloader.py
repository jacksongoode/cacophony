import asyncio
import os
import random
import subprocess
import tempfile

import yt_dlp
from yt_dlp.utils import DownloadError

from runtime_logger import LogColors, setup_logger
from visual import download_thumbnail

logger_dl = setup_logger("file2_logger", color_code=LogColors.DIM)

DOWNLOAD_DELAY = 5
MAX_CONCURRENCY = 5


async def choose_media(link_dict, player_num, min_dur, max_dur, q_dl, q_pyo):
    temp_dir = tempfile.TemporaryDirectory()

    async def preload_media_async(link, seen, visited, player):
        try:
            await asyncio.sleep(random.random() * DOWNLOAD_DELAY)
            logger_dl.info(f"↓ Downloading: {link}")
            output, cur_dur, thumb_data = await download_media(
                link, min_dur, max_dur, temp_dir
            )

            if output is not None:
                info_dict = {"link": link}
                await q_dl.put(
                    (output.name, seen, visited, player, thumb_data, info_dict)
                )
                logger_dl.info(f"✓ Completed: {link}")
        except Exception as e:
            logger_dl.error(f"✗ Error preloading media: {e}")

    tasks = []
    while len(link_dict) > 0:
        if len(tasks) < MAX_CONCURRENCY and q_dl.qsize() < 5:
            rnd_link = random.choice(list(link_dict.items()))
            link, (seen, visited) = rnd_link
            del link_dict[link]
            player = random.randint(0, player_num - 1)
            task = asyncio.create_task(preload_media_async(link, seen, visited, player))
            tasks.append(task)
        else:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            tasks = list(pending)
            await asyncio.sleep(0.1)

    await asyncio.gather(*tasks)
    temp_dir.cleanup()


async def download_media(link, min_dur, max_dur, temp_dir):
    if "youtube.com/watch?v=" not in link:
        logger_dl.error("✗ Invalid YouTube video link.")
        return None, None, None

    cur_dur = random.randint(min_dur, max_dur)

    # Use yt-dlp to fetch video info only, no immediate download
    audio_format = "opus"
    ydl_opts = {
        "format": "bestaudio",
        "extractaudio": True,
        "noplaylist": True,
        "quiet": True,
        "audioformat": audio_format,
    }

    def extract_info_sync(ydl_opts, link):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(link, download=False)
        except DownloadError as e:
            logger_dl.error(f"✗ DownloadError in extracting info: {e}")
            return None
        except Exception as e:
            logger_dl.error(f"✗ Unexpected error in extracting info: {e}")
            return None

    info_dict = await asyncio.to_thread(extract_info_sync, ydl_opts, link)
    if info_dict is None:
        return None, None, None

    if "entries" in info_dict:  # Verify it's not a playlist
        logger_dl.error("Playlists are not supported.")
        return None, None, None

    if info_dict.get("is_live"):
        logger_dl.error("Live streams cannot be processed.")
        return None, None, None

    duration = info_dict.get("duration")
    if not duration or duration < min_dur:
        logger_dl.warning("The video is too short or is a live stream; skipping.")
        return None, None, None

    cur_start = random.randint(0, max(0, duration - cur_dur))

    download_url = info_dict.get("url")
    if not download_url:
        logger_dl.warning("No direct download URL found, attempting DASH audio stream.")
        for format_info in info_dict.get("formats", []):
            if (
                format_info.get("acodec") != "none"
                and format_info.get("vcodec") == "none"
            ):
                download_url = format_info.get("url")
                break

    if not download_url:
        logger_dl.error("No suitable audio URL found.")
        return None, None, None

    # Download the thumbnail
    thumb_data = None
    thumbnail_url = info_dict.get("thumbnail", None)
    if thumbnail_url:
        # thumbnail_url = "/".join(thumbnail_url.rsplit("/", 1)[:-1]) + "/hqdefault.jpg"
        thumb_data = await download_thumbnail(thumbnail_url)

    output = tempfile.NamedTemporaryFile(
        suffix=f".{audio_format}", dir=temp_dir.name, delete=False
    )

    # Directly download and trim the audio with FFmpeg
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "quiet",
        "-y",
        "-ss",
        str(cur_start),
        "-t",
        str(cur_dur),
        "-i",
        download_url,
        "-map",
        "0:a",
        output.name,
    ]

    try:
        process = await asyncio.create_subprocess_exec(*command)
        await process.wait()
    except subprocess.CalledProcessError as e:
        logger_dl.error(f"Error processing audio: {e}")
        output.close()
        return None, None, None

    file_size = round(os.path.getsize(output.name) / (1024 * 1024), 2)
    logger_dl.info(f"=> {file_size}mb")
    return output, cur_dur, thumb_data
