import os
import random
import subprocess
import tempfile

import yt_dlp
from yt_dlp.utils import DownloadError


def download_media(link, i, min_dur, max_dur, temp_dir):
    yt_url = link
    cur_dur = random.randint(min_dur, max_dur)
    output = tempfile.NamedTemporaryFile(
        suffix=".flac", dir=temp_dir.name, delete=False
    )

    ydl_opts = {
        "format": "best",
        "noplaylist": True,
        "extractaudio": True,
        "quiet": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(yt_url, download=False)
            video = result["entries"][0] if "entries" in result else result
    except DownloadError:
        print("Bad link!")
        return

    url = video["url"]
    duration = video["duration"]

    try:
        cur_start = random.randint(0, duration - cur_dur)
    except ValueError:
        print("Live stream - returning")
        return

    # print("Downloading video '%s', starting at %ss for %ss" %(yt_url.split('v=')[-1], cur_start, cur_dur))
    command = [
        "resources/ffmpeg",
        "-hide_banner",
        "-ss",
        str(cur_start),
        "-t",
        str(cur_dur),
        "-loglevel",
        "quiet",
        "-i",
        url,
        "-map",
        "0:a",
        "-af",
        "aformat=s16:44100",
        "-y",
        output.name,
    ]
    subprocess.call(command)

    # print('Output %s' % output.name)
    # print('Size %s' % os.stat(output.name).st_size)
    return output, cur_dur


def choose_media(link_dict, player_num, min_dur, max_dur, q_dl, q_pyo):
    temp_dir = tempfile.TemporaryDirectory()
    old_files = []

    for i in range(len(link_dict)):
        rnd_link = random.choice(list(link_dict.items()))
        link, (seen, visited) = rnd_link
        del link_dict[link]

        try:
            output, cur_dur = download_media(link, i, min_dur, max_dur, temp_dir)
        except Exception:
            continue

        player = random.randint(0, player_num - 1)
        q_dl.put((output.name, seen, visited, player))

        if q_pyo.empty():
            continue

        old_files.append(q_pyo.get())
        cleanup_used(old_files)


def cleanup_used(old_files):
    if os.path.exists(old_files[-1][0]):
        old_players = [old[1] for old in old_files[:-1]]
        if old_files[-1][1] in old_players:
            i = old_players.index(old_files[-1][1])
            os.remove(old_files[i][0])
            del old_files[i]
