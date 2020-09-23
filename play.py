from __future__ import unicode_literals
import os
import io
import sys
import random
import subprocess
import multiprocessing as mp
import time
import math
import argparse
import tempfile

import orjson
import youtube_dl
from youtube_dl.utils import DownloadError
from pyo import *
from sr import audio2text

import librosa
import torch
import panns_inference
from panns_inference import AudioTagging, SoundEventDetection, labels,  print_audio_tagging_result

def pann(filepath):
    (audio, _) = librosa.core.load(filepath, sr=32000, mono=True)
    audio = audio[None, :]  # (batch_size, segment_samples)

    at = AudioTagging(checkpoint_path='/Users/jacksongoode/panns_data/MobileNetV2_mAP=0.383.pth',
                        device='cuda', model='MobileNet')
    (clipwise_output, embedding) = at.inference(audio)
    print_audio_tagging_result(clipwise_output[0], 1)

def download_media(link, i, min_dur, max_dur, temp_dir):
    yt_url = link
    cur_dur = random.randint(min_dur, max_dur)

    # total_dur += cur_dur
    # start_time = time.time()
    # time_list.append(start_time + total_dur)

    # output = 'sounds/sound_%s.flac' % i
    output = tempfile.NamedTemporaryFile(suffix='.flac', dir=temp_dir.name, delete=False)

    ydl_opts = {
        'format': 'best',
        'noplaylist': True,
        'extractaudio': True,
        'quiet': True
    }

    try:
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(yt_url, download = False)
            video = result['entries'][0] if 'entries' in result else result
    except DownloadError as e:
        print('Error!\n')   
        return # ? YoutTube blocking download?
    
    url = video['url']
    duration = video['duration']

    try:
        cur_start = random.randint(0, duration - cur_dur)
    except ValueError:
        print('Live stream - returning')
        return # should return with new link

    # print("Downloading video '%s', starting at %ss for %ss" %(yt_url.split('v=')[-1], cur_start, cur_dur))
    # recreates: ffmpeg -ss 60 -i $(youtube-dl -x -g 'https://www.youtube.com/watch?v=LzsldXHY2u8') -map 0:a -t 25 -y test.flac  
    command = [
        'resources/ffmpeg',
        '-hide_banner',
        '-ss', str(cur_start),
        '-t', str(cur_dur),
        '-loglevel', 'quiet',
        '-i', url,
        '-map', '0:a',
        '-af', 'aformat=s16:44100',
        '-y',
        output.name]
    subprocess.call(command)

    # print('Output %s' % output.name)
    # print('Size %s' % os.stat(output.name).st_size)
    return output, cur_dur

def choose_media(link_dict, player_num, min_dur, max_dur, q_dl, q_pyo):
    
    temp_dir = tempfile.TemporaryDirectory()
    old_files = []

    for i in range(len(link_dict)):
        # Choose random link then delete it
        rnd_link = random.choice(list(link_dict.items()))
        del link_dict[rnd_link[0]]
        
        seen = rnd_link[1][0]
        visited = rnd_link[1][1]

        try:
            output, cur_dur = download_media(rnd_link[0], i, min_dur, max_dur, temp_dir)
        except Exception as e:
            print('Bad link...')
            continue
        
        player = random.randint(0, player_num - 1)
        q_dl.put((output.name, seen, visited, player)) # name, seen count, visited (url), player to use
        
        # audio2text(output.name) # Google STT
        pann(output.name) # Classification

        if q_pyo.empty() is True:
            continue

        # Cleanup files that have been played by pyo
        old_files.append(q_pyo.get())
        cleanup_used(old_files)

def pyo_look(arg):
    global switch

    # print('\nLooking!')

    if q_dl.empty() is True:
        print('Queue empty!')
        return # if file is empty error, skip (shouldn't happen unless files are loaded too quickly)
    
    # Get any new files downloaded
    sound_queue.append(q_dl.get())
    output, seen, visited, player = sound_queue.pop()

    # Fade old sound in .5s
    panners[player].set('mul', 0, .5)

    # rand_pan = random.random()
    # verbs(player).set(attr='inpos', value=rand_pan, port=0.5)
    # print('New pan: %s' % rand_pan)
    
    # New fade out for player (if played through)
    dur = sndinfo(output)[1]

    # Set new sound after fade has finished
    def switch_sound():
        players[player].setPath(output)

        # sign = random.choice([-1, 1])
        rand_speed = random.uniform(.85, 1.15)
        print('Playback: %s' % rand_speed)
        players[player].setSpeed(rand_speed)
        new_dur = dur / abs(rand_speed)

        adsrs[player].setDur(new_dur)
        adsrs[player].setRelease(new_dur * 0.25) # release dependent on dur

        players[player].play()
        adsrs[player].play()

        # Use seen and visited vals to calculate amp of sound (and verb?)
        mul_range = 0.5
        mul_min = 0.5

        if visited == 0:
            eval_seen = (math.log(seen + 1, max_seen) * mul_range) + mul_min # range and min
            panners[player].set(attr='mul', value=eval_seen, port=0.5)
            print('Amp: %s' % eval_seen)
        else:
            eval_visit = (math.log(visited + 1, max_visit) * mul_range) + mul_min
            panners[player].set(attr='mul', value=eval_visit, port=0.5)
            print('Amp: %s' % eval_visit)
        
        # print('Pan: %s' % rand_pan)
        # Tell subprocess, old file is ready for deletion
        q_pyo.put((output, player))

    switch = CallAfter(switch_sound, .5)

    print( '\n--- Now playing %s on player %s for %ss ---' % (output, player, dur))

    # Set new time to look for file
    switch_dur = ((dur - min_dur) / max_dur * 8) + 2
    pat.set('time', switch_dur) # 2 - 10s
    print('Switch dur: %s' % switch_dur)

def shutdown():
    print('Shutting down')
    s.stop()
    s.shutdown()
    p.join()

# def cleanup():
#     for old_file in os.listdir(src):
#         if old_file.startswith('sound_'):
#             os.remove(src + old_file)
#     print('Cleaned up!')

def cleanup_used(old_files):
    # Delete last file if player occurs twice (recycled)
    if os.path.exists(old_files[-1][0]): # check if file has been downloaded
        old_players = [old[1] for old in old_files[:-1]] # make a list of the players in use except most recently added
        if old_files[-1][1] in old_players: # see if the last player is in the old player list (its safe to delete)
            i = old_players.index(old_files[-1][1])
            os.remove(old_files[i][0]) # remove file associated with old player
            del old_files[i] # delete entry from list

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--players', type=int, default='16',
                        help='number of concurrent players')
    args = parser.parse_args()

    # Variables to pass through to triggers
    player_num = args.players # how many concurrent players (panners, faders) # TODO: make arg
    min_dur = 8
    warm_up = 5
    max_dur = 24
    src='./sounds/'
    sound_queue = []
    switch = None

    adsrs = [None] * player_num
    players = [None] * player_num
    panners = [None] * player_num
    verbs = [None] * player_num
    eq = [None]
    pan_vals = []
    bi_vals = []

    link_dict = {}
    link_list = []
    value_list = []
    max_seen = 0
    max_visit = 0

    # Load links from json made by browser.py
    with open('resources/links.json', 'rb') as f:
        link_dict = orjson.loads(f.read())
    
    value_list = list(link_dict.values())
    sum_seen = sum(i for i, _ in value_list)
    max_seen = max(i for i, _ in value_list)
    sum_visit = sum(i for _, i in value_list)
    max_visit = max(i for _, i in value_list)
    
    # Create pan vals
    for i in range(player_num):
        pan_vals.append(i / player_num + (1 / (2 * player_num))) # stereo pan equal distance apart
        # bi_vals.append((i / player_num * 360) - 180 + (1 / (2 * player_num) * 360)) # binaural pan equal distance apart (-180 to 180)
    
    # Start youtube-dl/ffmpeg
    q_dl = mp.Queue()
    q_pyo = mp.Queue()
    p = mp.Process(target=choose_media, args=(link_dict, player_num, min_dur, max_dur, q_dl, q_pyo))
    p.daemon = True
    p.start()

    # * --- pyo ---
    s = Server(buffersize=512)
    s.deactivateMidi()
    s.boot()
    print('Player on!')

    # Create players and panners
    for i in range(player_num):
        adsrs[i] = Adsr(attack=0.75, decay=0, sustain=1, release=3)
        players[i] = SfPlayer(src + 'empty.flac', speed=1, mul=adsrs[i])
        panners[i] = Pan(players[i], pan=pan_vals[i])
    verbs = STRev(panners, inpos=pan_vals, revtime=1.2, cutoff=6000, bal=0.5, roomSize=2, firstRefGain=-24)
    # verbs = Freeverb(panners, size=0.5, damp=0.75)
    eq = EQ(verbs, freq=180, boost=-12.0, type=1).out()
    # bin = Binaural(players, azimuth=bi_vals).mix(2).out()
    
    print('Warming up...')
    time.sleep(warm_up)

    try:
        pat = Pattern(function=pyo_look, arg=(q_dl, q_pyo)).play()
        s.start()
        print('Started!')
        # s.gui(locals())
        while True:
            time.sleep(3600)

    except:
        shutdown()
    
    # finally:
    #     cleanup()
