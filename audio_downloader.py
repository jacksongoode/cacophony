import random
import subprocess
import tempfile
import threading
import time

import yt_dlp
from yt_dlp.utils import DownloadError

from runtime_logger import LogColors, setup_logger

logger_dl = setup_logger("file2_logger", color_code=LogColors.DIM)


def preload_media(link, seen, visited, player, min_dur, max_dur, temp_dir, q_dl):
    try:
        output, cur_dur = download_media(link, min_dur, max_dur, temp_dir)
        time.sleep(random.randint(1, 3))
        if output is not None:
            q_dl.put((output.name, seen, visited, player))
            logger_dl.info(f"✓ Completed: {link}")
    except Exception as e:
        logger_dl.error(f"Error preloading media: {e}")


def choose_media(link_dict, player_num, min_dur, max_dur, q_dl, q_pyo):
    temp_dir = tempfile.TemporaryDirectory()
    preload_threads = []
    max_concurrency = 3

    try:
        while len(link_dict) > 0:
            # Throttle the thread creation based on the maximum allowed concurrent downloads
            active_downloads = sum([1 for t in preload_threads if t.is_alive()])

            if active_downloads < max_concurrency and q_dl.qsize() < 5:
                rnd_link = random.choice(list(link_dict.items()))
                link, (seen, visited) = rnd_link
                del link_dict[link]
                player = random.randint(0, player_num - 1)

                # Start preload in a new thread
                thread = threading.Thread(
                    target=preload_media,
                    args=(
                        link,
                        seen,
                        visited,
                        player,
                        min_dur,
                        max_dur,
                        temp_dir,
                        q_dl,
                    ),
                )
                thread.start()
                preload_threads.append(thread)

                # Brief sleep to prevent immediate re-check and thread spawning; adjust as needed.
                time.sleep(0.1)
            else:
                # Give some time for active threads to possibly finish
                time.sleep(1)

    finally:
        # Wait for all remaining preload threads to complete before shutdown
        for thread in preload_threads:
            thread.join()


def download_media(link, min_dur, max_dur, temp_dir):
    if "youtube.com/watch?v=" not in link:
        logger_dl.error("Invalid YouTube video link.")
        return None, None

    cur_dur = random.randint(min_dur, max_dur)

    logger_dl.info(f"↓ Downloading: {link}")

    # Use yt-dlp to fetch video info only, no immediate download
    ydl_opts = {
        "format": "bestaudio",
        "extractaudio": True,
        # "audioformat": "flac",
        "noplaylist": True,
        "quiet": True,
        "audioquality": 0,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(link, download=False)
            if "entries" in info_dict:  # Verify it's not a playlist
                logger_dl.error("Playlists are not supported.")
                return None, None

            if info_dict.get("is_live"):
                logger_dl.error("Live streams cannot be processed.")
                return None, None

            duration = info_dict.get("duration")
            if not duration or duration < min_dur:
                logger_dl.warning(
                    "The video is too short or is a live stream; skipping."
                )
                return None, None

            cur_start = random.randint(0, max(0, duration - cur_dur))
            download_url = info_dict["url"]

    except DownloadError as e:
        logger_dl.error(f"Failed to download {link}: {e}")
        return None, None
    except Exception as e:
        logger_dl.error(f"Unexpected error {e} when processing {link}.")
        return None, None

    output = tempfile.NamedTemporaryFile(
        suffix=".flac", dir=temp_dir.name, delete=False
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
        subprocess.run(command, check=True)

    except subprocess.CalledProcessError as e:
        logger_dl.error(f"Error processing audio: {e}")
        output.close()
        return None, None

    return output, cur_dur
