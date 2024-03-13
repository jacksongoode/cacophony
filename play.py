from __future__ import unicode_literals

import argparse
import io
import logging
import math
import multiprocessing as mp
import os
import random
import time

import orjson
from pyo import EQ, Adsr, CallAfter, Pan, Pattern, Server, SfPlayer, STRev, sndinfo

from audio_downloader import choose_media

# Setup basic logging
logging.basicConfig(level=logging.INFO)


class AudioPlayer:
    def __init__(self, player_count, min_duration, max_duration, source_dir):
        self.q_dl = mp.Queue()
        self.q_pyo = mp.Queue()
        self.player_count = player_count
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.source_dir = source_dir
        self.sound_queue = []
        self.switch = None
        self.adsrs = []
        self.players = []
        self.panners = []
        self.verbs = None
        self.eq = None
        self.pan_vals = []
        self.max_seen = 0
        self.max_visit = 0
        self.warm_up_duration = 5
        self.server = Server(nchnls=8, buffersize=256)

    def load_links(self, filename):
        with open(filename, "rb") as f:
            link_dict = orjson.loads(f.read())
        value_list = list(link_dict.values())
        self.max_seen = max(i for i, _ in value_list)
        self.max_visit = max(i for _, i in value_list)
        return link_dict

    def setup_audio_environment(self):
        self.server.deactivateMidi()
        self.server.boot()
        print("Player on!")

        # Create players, panners, and set up effects
        for i in range(self.player_count):
            self.pan_vals.append(i / self.player_count + (1 / (2 * self.player_count)))

            adsr = Adsr(attack=0.75, decay=0, sustain=1, release=3)
            self.adsrs.append(adsr)

            player = SfPlayer(self.source_dir + "empty.flac", speed=1, mul=adsr)
            self.players.append(player)

            panner = Pan(player, pan=self.pan_vals[i])
            self.panners.append(panner)

        self.verbs = STRev(
            self.panners,
            inpos=self.pan_vals,
            revtime=2.1,
            cutoff=6000,
            bal=0.5,
            roomSize=3,
            firstRefGain=-24,
        )
        self.eq = EQ(self.verbs, freq=180, boost=-12.0, type=1).out()

    def play_audio(self):
        print("Warming up...")
        time.sleep(self.warm_up_duration)
        self.server.start()
        print("Started!")

    def shutdown(self):
        print("Shutting down")
        self.server.stop()
        self.server.shutdown()

    def pyo_look(self):
        try:
            if self.q_dl.empty() is True:
                print(".", end="", flush=True)
                return

            self.sound_queue.append(self.q_dl.get())
            output, seen, visited, player = self.sound_queue.pop()

            if not os.path.exists(output):
                logging.warning(f"File does not exist: {output}")
                return

            # Fade old sound in 0.5s
            self.panners[player].set("mul", 0, 0.5)

            try:
                file_info = sndinfo(output)
                if file_info is None:
                    raise Exception("Failed to get sound info.")
                dur = file_info[1]
            except Exception as e:
                logging.error(f"Error getting sound info: {e}")
                return

            # New fade out for player (if played through)
            dur = file_info[1]

            def switch_sound():
                self.players[player].setPath(output)

                rand_speed = random.uniform(0.85, 1.15)

                print(f"Playback: {rand_speed}")
                self.players[player].setSpeed(rand_speed)
                new_dur = dur / abs(rand_speed)

                self.adsrs[player].setDur(new_dur)
                self.adsrs[player].setRelease(
                    new_dur * 0.25
                )  # release dependent on dur

                self.players[player].play()
                self.adsrs[player].play()

                # Use seen and visited vals to calculate amp of sound (and verb?)
                mul_range = 0.5
                mul_min = 0.5

                # Ensure base is greater than 1
                max_seen_t = max(2, self.max_seen)
                max_visit_t = max(2, self.max_visit)

                if visited == 0:
                    amp = (math.log(seen + 1, max_seen_t) * mul_range) + mul_min
                else:
                    amp = (math.log(visited + 1, max_visit_t) * mul_range) + mul_min

                self.panners[player].set(attr="mul", value=amp, port=0.5)
                print(f"Amp: {amp}\n")

                # Tell subprocess, old file is ready for deletion
                self.q_pyo.put((output, player))

            self.switch = CallAfter(switch_sound, 0.5)
            print(f"\n--- Now playing on player {player} for {dur}s ---")

            # Set new time to look for file
            switch_dur = ((dur - self.min_duration) / self.max_duration * 4) + 2
            self.pat.set("time", switch_dur)
            print(f"Switch dur: {switch_dur}")

        except Exception as e:
            logging.error(f"An error occurred in pyo_look: {e}")

    def run(self):
        self.setup_audio_environment()
        self.play_audio()
        self.pat = Pattern(
            function=self.pyo_look
        ).play()  # Start the Pattern to call pyo_look
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            self.shutdown()
        finally:
            self.process.join()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p", "--players", type=int, default=16, help="number of concurrent players"
    )
    args = parser.parse_args()

    audio_player = AudioPlayer(
        player_count=args.players,
        min_duration=8,
        max_duration=32,
        source_dir="./sounds/",
    )

    link_dict = audio_player.load_links("resources/links.json")

    # Start youtube-dl/ffmpeg

    process = mp.Process(
        target=choose_media,
        args=(
            link_dict,
            args.players,
            audio_player.min_duration,
            audio_player.max_duration,
            audio_player.q_dl,
            audio_player.q_pyo,
        ),
    )
    process.daemon = True
    process.start()

    # Start the player
    audio_player.run()


if __name__ == "__main__":
    main()
