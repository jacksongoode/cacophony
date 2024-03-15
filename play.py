from __future__ import unicode_literals

import argparse
import io
import logging
import math
import os
import random
import threading
import time
from queue import Queue

import orjson
from pyo import EQ, Adsr, CallAfter, Pan, Pattern, Server, SfPlayer, STRev, sndinfo

from audio_downloader import choose_media

logging.basicConfig(level=logging.INFO, format="%(message)s")


class AudioPlayer:
    def __init__(self, player_count, min_duration, max_duration, source_dir):
        self.q_dl = Queue()
        self.q_pyo = Queue()
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
        self.server = Server(nchnls=2, buffersize=1024, duplex=0)

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
        logging.info("Player on!")

        # Create players, panners, and set up effects
        for i in range(self.player_count):
            self.pan_vals.append(i / self.player_count + (1 / (2 * self.player_count)))

            adsr = Adsr(attack=0.75, decay=0, sustain=1, release=3)
            self.adsrs.append(adsr)

            player = SfPlayer(self.source_dir + "empty.wav", speed=1, mul=adsr)
            self.players.append(player)

            panner = Pan(player, pan=self.pan_vals[i], spread=0.25)
            self.panners.append(panner)

        self.verbs = STRev(
            self.panners,
            inpos=self.pan_vals,
            revtime=2.1,
            cutoff=6000,
            bal=0.5,
            roomSize=3,
            firstRefGain=-18,
        )
        self.eq = EQ(self.verbs, freq=180, boost=-12.0, type=1).out()

    def play_audio(self):
        logging.info("Warming up...")
        time.sleep(self.warm_up_duration)
        self.server.start()
        logging.info("Started!")

    def shutdown(self):
        logging.info("Shutting down")
        self.server.stop()
        self.server.shutdown()

    def pyo_look(self):
        def handle_sound_info(output):
            try:
                file_info = sndinfo(output)
                if file_info is None:
                    raise ValueError("Failed to get sound info.")
                return file_info[1]
            except Exception as e:
                logging.error(f"Error getting sound info: {e}")
                return None

        def calculate_amplitude(seen, visited):
            # Ensuring base for logarithm is always greater than 1
            base, interact = (
                (seen, self.max_seen) if visited == 0 else (visited, self.max_visit)
            )
            # Apply max to ensure base is at least 2, making the log function valid
            interact = max(1, interact)
            mul_range, mul_min = 0.5, 0.5

            return (math.log(base + 1, interact) * mul_range) + mul_min

        if self.q_dl.empty():
            print(".", end="", flush=True)
            return

        self.sound_queue.append(self.q_dl.get())
        output, seen, visited, player = self.sound_queue.pop()

        if not os.path.exists(output):
            logging.warning(f"File does not exist: {output}")
            return

        self.panners[player].set("mul", 0, 0.5)  # Fading old sound

        dur = handle_sound_info(output)
        if dur is None:  # Handling failure directly
            return

        def switch_sound():
            self.players[player].setPath(output)
            rand_speed = random.uniform(0.75, 1.25)
            self.players[player].setSpeed(rand_speed)
            logging.info(f"Playback: {rand_speed}")
            new_dur = dur / abs(rand_speed)

            self.adsrs[player].setDur(new_dur)
            self.adsrs[player].setRelease(
                new_dur * 0.25
            )  # Release dependent on duration

            amp = calculate_amplitude(seen, visited)
            self.panners[player].set(attr="mul", value=amp, port=0.5)
            logging.info(f"Amp: {amp}")

            self.players[player].play()
            self.adsrs[player].play()

            self.q_pyo.put(
                (output, player)
            )  # Indicating old file's readiness for deletion

        self.switch = CallAfter(switch_sound, 0.5)
        logging.info(f"\n⏵ Now playing on player {player} ({dur}s)")

        switch_dur = ((dur - self.min_duration) / self.max_duration * 2) + 2
        self.pat.set("time", switch_dur)
        logging.info(f"Switch dur: {switch_dur}")

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

    download_thread = threading.Thread(
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
    download_thread.daemon = True  # Allows thread to exit when main program exits
    download_thread.start()

    # Start the player
    audio_player.run()


if __name__ == "__main__":
    main()
