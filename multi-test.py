#!.venv/bin/python

from pyo import *

# Channel 3 is the subwoofer
# s = Server(nchnls=5, buffersize=1024, duplex=0)
# s.boot()

# a = FM(carrier=440, ratio=[1.51, 1.49], index=6, mul=0.3)
# lfo = Sine(freq=0.05, mul=0.5, add=0.5)
# p = Pan(a, outs=5, spread=0, pan=lfo).out()


srv = Server(nchnls=5, buffersize=1024, duplex=0).boot()
audio_file = "uncut.mp3"
adsr = Adsr(attack=0.75, decay=0, sustain=1, release=3)

player = SfPlayer(audio_file, speed=1, mul=adsr)
adsr.play()

panner = Pan(player, outs=5, pan=0.4, spread=0.25)
eq = EQ(panner, freq=800, boost=-8.0).out()

srv.gui(locals())
