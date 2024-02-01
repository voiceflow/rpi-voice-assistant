import os
import audio
import hashlib
import pathlib
import subprocess
import requests
import timeit
import yaml

import asyncio
from collections.abc import Sequence, Iterator
import re
import structlog
import signal
import uuid

from elevenlabs import ElevenLabs


from collections.abc import Iterator
from pathlib import Path
from dotenv import load_dotenv

from typing import Dict, Any
JSON = Dict[str, Any]

from google.cloud import speech_v1 as speech
from google.protobuf import duration_pb2

from voiceflow import Voiceflow

def load_config(config_file="config.yaml"):
    with open(config_file) as file:
        # The FullLoader parameter handles the conversion from YAML
        # scalar values to Python the dictionary format
        return yaml.load(file, Loader=yaml.FullLoader)

def play_elevenlabs_audio(response_text: str, el: ElevenLabs):
    stream = el.generate_audio_stream(response_text)
    audio.play_audio_stream(stream)

def handle_vf_response(vf: Voiceflow, vf_response: JSON, el: ElevenLabs):
    for item in vf_response:
        if item["type"] == "speak":
            payload = item["payload"]
            message = payload["message"]
            print("Response: " + message)
            if "src" in payload:
                audio.play(payload["src"])
            else:
                play_elevenlabs_audio(message, el)
        elif item["type"] == "end":
            print("-----END-----")
            vf.user_state.delete()
            return True 
    return False

# Setup
load_dotenv()
ELEVENLABS_API_KEY = os.getenv('EL_API_KEY', "dummy_key")
RATE = 16000
CHUNK = 128
language_code = "de-DE"  #BCP-47 language tag
CONFIG = load_config()

log = structlog.get_logger(__name__)


def main():
    #Voiceflow setup using python package from pip
    vf = Voiceflow(
        api_key=os.getenv('VF_API_KEY', "dummy_key"),
        user_id=uuid.uuid4()
    )

    #Start from beginning of voice assistant
    vf.user_state.delete()

    # Google ASR setup
    google_asr_client = speech.SpeechClient()
    google_asr_config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code=language_code,
    )

    # Use a directory relative to the current working directory to cache audio files.
    # Might make sense to use a temporary directory to ensure the cache is cleaned up
    # after the application is terminated.
    elevenlabs_client = ElevenLabs(api_key=os.getenv('EL_API_KEY', "dummy_key"), voice_id=CONFIG["elevenlabs_voice_id"])

    streaming_config = speech.StreamingRecognitionConfig(
        config=google_asr_config, interim_results=False, #enable_voice_activity_events=True, voice_activity_timeout=voice_activity_timeout,
    )

    with audio.MicrophoneStream(RATE, CHUNK) as stream:
        while True:
            vf.user_id = uuid.uuid4()
            input("Press Enter to start the voice assistant...")
            end = False
            vf_response = vf.interact.launch()
            end = handle_vf_response(vf, vf_response, elevenlabs_client)
            while not end:
                audio.beep()
                stream.start_buf()

                audio_generator = stream.generator()
                requests = (
                    speech.StreamingRecognizeRequest(audio_content=content)
                    for content in audio_generator
                )

                responses = google_asr_client.streaming_recognize(streaming_config, requests)
                utterance = audio.process(responses)
                stream.stop_buf()
                
                vf_response = vf.interact.text(user_input=utterance)
                end = handle_vf_response(vf, vf_response, elevenlabs_client)

if __name__ == "__main__":
    main()