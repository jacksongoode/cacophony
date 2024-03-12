import logging
import os
import random
import subprocess
import tempfile

import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(message)s")


def choose_media(link_dict, player_num, min_dur, max_dur, q_dl, q_pyo):
    temp_dir = tempfile.TemporaryDirectory()
    old_files = []

    for _ in range(len(link_dict)):
        rnd_link = random.choice(list(link_dict.items()))
        link, (seen, visited) = rnd_link
        del link_dict[link]

        try:
            output, cur_dur = download_media(link, min_dur, max_dur, temp_dir)
            if output is None:
                continue
        except Exception:
            continue

        player = random.randint(0, player_num - 1)
        q_dl.put((output.name, seen, visited, player))

        if q_pyo.empty():
            continue

        old_files.append(q_pyo.get())
        cleanup_used(old_files)


def download_media(link, min_dur, max_dur, temp_dir):
    yt_url = link
    short_url = yt_url.split("?v=")[-1]
    cur_dur = random.randint(min_dur, max_dur)

    logging.info(f"Downloading {short_url}...")
    output = tempfile.NamedTemporaryFile(
        suffix=".flac", dir=temp_dir.name, delete=False
    )

    ydl_opts = {
        "format": "bestaudio",
        "noplaylist": True,
        "extractaudio": True,
        "quiet": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(yt_url, download=False)
            video = result["entries"][0] if "entries" in result else result
    except yt_dlp.DownloadError as e:
        logging.error(f"Bad link {yt_url}: {e}")
        return
    except Exception as e:
        logging.error(f"Unexpected error when processing {yt_url}: {e}")
        return

    duration = video.get("duration")
    if duration is None or duration < cur_dur:
        logging.warning(f"Live stream or short video {yt_url} - skipping")
        return

    cur_start = random.randint(0, duration - cur_dur)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-ss",
        str(cur_start),
        "-t",
        str(cur_dur),
        "-loglevel",
        "quiet",
        "-i",
        video["url"],
        "-map",
        "0:a",
        "-y",
        output.name,
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        logging.info(f"Downloaded {short_url}")
    except subprocess.TimeoutExpired:
        logging.error(f"Timeout expired while downloading {short_url}")
        return
    except subprocess.CalledProcessError as e:
        logging.error(f"Error downloading {short_url}: {e}")
        return

    return output, cur_dur


def cleanup_used(old_files):
    if os.path.exists(old_files[-1][0]):
        old_players = [old[1] for old in old_files[:-1]]
        if old_files[-1][1] in old_players:
            i = old_players.index(old_files[-1][1])
            os.remove(old_files[i][0])
            del old_files[i]
