import speech_recognition as sr
from speech_recognition import UnknownValueError
import os
import time

r = sr.Recognizer()

def audio2text(path):
    # src = 'sounds/'
    # for i in sorted(os.listdir(src)):
    #     if i.startswith('sound'):
    #         print(i)
    sf = sr.AudioFile(path)

    with sf as source:
        try:
            r.adjust_for_ambient_noise(source)
            audio = r.record(source)
            result = r.recognize_google(audio, language='en-US') # only eng
        except UnknownValueError: # no words recognized
            result = "\nUnintelligible..."
            pass

        print('\n %s' % result)