import os
import time
import struct
import sys
import audio
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

def elevenlabs_stream(text: str, voice_id: str, api_key: str) -> Iterator[bytes]:
    headers = { "xi-api-key": api_key }
    query = { "optimize_streaming_latency": "4" }

    payload = {
        "model_id": "eleven_multilingual_v2",
        "output_format": "mp3_22050_32",
        "text": text,
    }

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

    response = requests.post(url, json=payload, headers=headers, params=query)
    chunks = response.iter_content(chunk_size=2048)

    return chunks

def play_audio_stream(chunks: Iterator[bytes]):
    """Play an audio bytestream using the mpv media player."""
    mpv_command = ["mpv", "--no-cache", "--no-terminal", "--", "fd://0"]
    mpv_proc = subprocess.Popen(
        mpv_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for chunk in chunks:
        mpv_proc.stdin.write(chunk)
        mpv_proc.stdin.flush()

    if mpv_proc.stdin:
        mpv_proc.stdin.close()

    mpv_proc.wait()


def generate_audio(text: str, voice_id: str, api_key:str) -> Iterator[bytes]:
    """Run speech synthesis via ElevenLabs API and return an MP3 bytestream."""
    headers = { "xi-api-key": api_key }
    query = { "optimize_streaming_latency": "4" }

    payload = {
        "model_id": "eleven_multilingual_v2",
        "output_format": "mp3_22050_32",
        "text": text,
    }

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

    log.debug(f"Generating audio", text=text)
    start = timeit.default_timer()
    response = requests.post(url, json=payload, headers=headers, params=query)
    end = timeit.default_timer()
    log.debug(f"Successfully generated audio", took=round(end - start, 2), text=text)
    chunks = response.iter_content(chunk_size=2048)

    return chunks

def generate_audio_parallel(segments: Sequence[str], voice_id: str, api_key:str) -> Iterator[bytes]:
    """Run speech synthesis for the given list of text segments in parallel and return an MP3 bytestream.
    The MP3 bytestream contains synthesiszed audio matching the order of the input text segments."""
    loop = asyncio.get_event_loop()

    futures = [
        loop.run_in_executor(None, generate_audio, segment, voice_id, api_key)
        for segment in segments
    ]

    before_first_audio = timeit.default_timer()

    for i, future in enumerate(futures):
        # Gracefully stop asyncio task when receiving system signals
        loop.add_signal_handler(signal.SIGINT, future.cancel)
        loop.add_signal_handler(signal.SIGTERM, future.cancel)

        # Wait for HTTP request to complete
        chunks = loop.run_until_complete(future)

        if i == 0:
            after_first_audio = timeit.default_timer()
            log.debug("Time to first audio", took=round(after_first_audio - before_first_audio, 2))

        yield from chunks

def split_text(text: str) -> list[str]:
    """Split text into multiple text segments that can be synthesized to audio separately."""
    sentences = []
    pattern = r"[\.?!]+"

    previous_end = 0

    for match in re.finditer(pattern, text):
        sentence = text[previous_end:match.end()]
        sentences.append(sentence.strip())
        previous_end = match.end()

    return sentences

def play_elevenlabs_audio(response_text: str):
    voice_id = CONFIG["elevenlabs_voice_id"]
    api_key = os.getenv('EL_API_KEY', "dummy_key")

    segments = split_text(response_text)
    stream = generate_audio_parallel(segments=segments, voice_id=voice_id, api_key=api_key)
    play_audio_stream(stream)

def handle_vf_response(vf: Voiceflow, vf_response: JSON):
    for item in vf_response:
        if item["type"] == "speak":
            payload = item["payload"]
            message = payload["message"]
            print("Response: " + message)
            if "src" in payload:
                audio.play(payload["src"])
            else:
                play_elevenlabs_audio(message)
        elif item["type"] == "end":
            print("-----END-----")
            vf.user_state.delete()
            return True 
    return False

# Setup
load_dotenv()
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

    # speech_start_timeout = duration_pb2.Duration(seconds=10)
    # speech_end_timeout = duration_pb2.Duration(seconds=10)
    # voice_activity_timeout = (
    #     speech.StreamingRecognitionConfig.VoiceActivityTimeout(
    #         speech_start_timeout=speech_start_timeout,
    #         speech_end_timeout=speech_end_timeout,
    #     )
    # )
    #TODO: if relevant attempt to use example for v2 (and in general google tts v2 from here: )
    #watch stackoverflow issues here: https://stackoverflow.com/questions/77828478/in-google-cloud-dotnet-voiceactivitytimeout-not-working-in-streamingrecognizereq, same as demonstrated

    streaming_config = speech.StreamingRecognitionConfig(
        config=google_asr_config, interim_results=False, #enable_voice_activity_events=True, voice_activity_timeout=voice_activity_timeout,
    )

    with audio.MicrophoneStream(RATE, CHUNK) as stream:
        while True:
            vf.user_id = uuid.uuid4()
            input("Press Enter to start the voice assistant...")
            end = False
            vf_response = vf.interact.launch()
            end = handle_vf_response(vf, vf_response)
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
                end = handle_vf_response(vf, vf_response)

if __name__ == "__main__":
    main()