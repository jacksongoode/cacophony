#!.venv/bin/python

from __future__ import unicode_literals

import argparse
import asyncio
import io
import logging
import math
import os
import random
import time

import orjson
from pyo import Adsr, Pan, Server, SfPlayer, sndinfo

from downloader import choose_media
from visual import display_thumbnail

logging.basicConfig(level=logging.INFO, format="%(message)s")


class AudioPlayer:
    def __init__(self, player_count, min_duration, max_duration, source_dir):
        # Input parameters
        self.player_count = player_count
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.source_dir = source_dir

        # Queues
        self.q_dl = asyncio.Queue()
        self.q_pyo = asyncio.Queue()

        # Sound queue and related properties
        self.sound_queue = []
        self.switch = None
        self.last_duration = 0

        # Audio properties
        self.adsrs = []
        self.players = []
        self.panners = []
        self.pan_vals = []
        self.verbs = None
        self.eq = None
        self.currently_playing = {}

        # Server properties
        self.server = Server(nchnls=5, buffersize=1024, duplex=0)

        # Tracking properties
        self.max_seen = 0
        self.max_visit = 0

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
            pan_val = i / self.player_count + (1 / (2 * self.player_count))
            pan_val = pan_val * 0.8

            self.pan_vals.append(pan_val)

            # Fade in/out
            adsr = Adsr(attack=0.75, decay=0, sustain=1, release=3)
            self.adsrs.append(adsr)

            # Player
            player = SfPlayer(self.source_dir + "empty.wav", speed=1, mul=self.adsrs[i])
            self.players.append(player)

            # Panner
            panner = Pan(self.players[i], outs=5, pan=self.pan_vals[i], spread=0.15)
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

    def get_available_player(self):
        available_players = [
            p for p in range(self.player_count) if p not in self.currently_playing
        ]

        if available_players:
            return random.choice(available_players)

        # If no available players, get the player with the oldest end time
        oldest_player = min(self.currently_playing, key=self.currently_playing.get)
        return oldest_player

    def play_audio(self):
        self.server.start()
        logging.info("Started!")

    def shutdown(self):
        logging.info("Shutting down...")
        self.server.stop()
        self.server.shutdown()

    async def pyo_look(self):
        def handle_sound_info(output):
            try:
                file_info = sndinfo(output, raise_on_failure=True)
                return file_info[1]
            except Exception as e:
                logging.error(f"Error getting sound info: {e}")
                return None

        def calculate_amplitude(seen, visited):
            # Ensuring base for logarithm is always greater than 1
            base, interact = (
                (seen, self.max_seen) if visited == 0 else (visited, self.max_visit)
            )
            interact = max(1, interact)  # Catch in case
            mul_range, mul_min = 0.5, 0.5

            return (math.log(base + 1, interact) * mul_range) + mul_min

        if self.q_dl.empty():
            print(".", end="", flush=True)
            return

        self.sound_queue.append(await self.q_dl.get())
        sound_path, seen, visited, _, thumb_data, info_dict = self.sound_queue.pop()
        player = self.get_available_player()

        if not os.path.exists(sound_path):
            logging.warning(f"File does not exist: {sound_path}")
            return

        self.panners[player].set("mul", 0, 0.5)  # Fading old sound

        if (dur := handle_sound_info(sound_path)) is None:
            return False
        self.last_duration = dur

        stop_event = asyncio.Event()

        async def switch_sound():
            self.players[player].setPath(sound_path)
            rand_speed = random.uniform(0.75, 1.25)
            self.players[player].setSpeed(rand_speed)
            logging.info(f"Playback: {rand_speed}")
            new_dur = dur / abs(rand_speed)

            self.adsrs[player].setDur(new_dur)
            # Release dependent on duration
            self.adsrs[player].setRelease(new_dur * 0.25)

            amp = calculate_amplitude(seen, visited)
            self.panners[player].set(attr="mul", value=amp, port=0.5)
            logging.info(f"Amp: {amp}")
            logging.info(f"Pan: {self.panners[player]._pan}")

            self.players[player].play()
            self.adsrs[player].play()

            # Play audio file
            await self.q_pyo.put((sound_path, player))

            # Add player and duration when starting sound
            end_time = time.time() + new_dur
            self.currently_playing[player] = end_time

            # Show thumbnail
            asyncio.create_task(display_thumbnail(thumb_data, info_dict, stop_event))

        if self.switch and not self.switch.done():
            stop_event.set()
            await self.switch

        self.switch = asyncio.create_task(switch_sound())
        logging.info(f"\n⏵ Now playing on player {player} ({dur}s)")
        return True

    async def run(self):
        try:
            self.setup_audio_environment()
            self.play_audio()
        except Exception as e:
            raise Exception("Pyo server couldn't start") from e

        try:
            while True:
                sound_played = await self.pyo_look()
                if sound_played:
                    switch_dur = (
                        (self.last_duration - self.min_duration) / self.max_duration * 4
                    ) + 2
                    logging.info(f"Switch duration: {switch_dur}")
                else:
                    switch_dur = 0.5

                await asyncio.sleep(switch_dur)  # Wait for the computed interval
        except KeyboardInterrupt:
            logging.info("Keyboard interrupt received, shutting down...")
            self.shutdown()
        except Exception as e:
            logging.error(f"An error occurred: {e}")
            self.shutdown()
        finally:
            if hasattr(self, "process"):
                self.process.join()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p", "--players", type=int, default=16, help="Number of concurrent players"
    )
    parser.add_argument(
        "-l",
        "--links",
        type=str,
        help="Filename of links to load (base of .json)",
    )
    args = parser.parse_args()

    audio_player = AudioPlayer(
        player_count=args.players,
        min_duration=12,
        max_duration=36,
        source_dir="./sounds/",
    )

    link_dict = audio_player.load_links(f"resources/{args.links}.json")

    audio_player_task = asyncio.create_task(audio_player.run())
    download_task = asyncio.create_task(
        choose_media(
            link_dict,
            args.players,
            audio_player.min_duration,
            audio_player.max_duration,
            audio_player.q_dl,
            audio_player.q_pyo,
        )
    )

    try:
        await asyncio.gather(audio_player_task, download_task)
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received, shutting down...")
        audio_player_task.cancel()
        download_task.cancel()
    finally:
        # Wait for the tasks to be cancelled, ignoring any CancelledError exceptions
        await asyncio.gather(audio_player_task, download_task, return_exceptions=True)
        audio_player.shutdown()
        logging.info("Shutdown completed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # This should not be necessary, but it's a safeguard
        # in case the KeyboardInterrupt is not caught by the main() coroutine.
        logging.info("Keyboard interrupt received, exiting...")
