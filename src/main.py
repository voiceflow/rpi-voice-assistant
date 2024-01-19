import os
import time
import struct
import sys
import audio
import subprocess
import requests
import timeit
import yaml

from collections.abc import Iterator
from pathlib import Path
from dotenv import load_dotenv

from typing import Dict, Any
JSON = Dict[str, Any]

from google.cloud import speech_v1 as speech
from google.protobuf import duration_pb2

grandparent_dir = Path(__file__).parents[1]
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), grandparent_dir)))
from voiceflow_python.src.voiceflow import Voiceflow

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

def playback_stream(chunks: Iterator[bytes]):
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

def play_elevenlabs_audio(response_text: str):
    voice_id = CONFIG["elevenlabs_voice_id"]
    api_key = os.getenv('EL_API_KEY', "dummy_key")
    stream = elevenlabs_stream(text=response_text, voice_id=voice_id, api_key=api_key)
    playback_stream(stream)

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

def main():
    #Voiceflow setup using python package from pip
    vf = Voiceflow(
        api_key=os.getenv('VF_API_KEY', "dummy_key"),
        user_id='abc123'
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