import os
import time
import struct
import sys
import audio

from google.cloud import speech_v1 as speech
from voiceflow import Voiceflow
from dotenv import load_dotenv

load_dotenv()
RATE = 16000
CHUNK = 512
language_code = "de-DE"  #BCP-47 language tag

def handle_vf_response(vf, vf_response):
    for item in vf_response:
        if item["type"] == "speak":
            payload = item["payload"]
            message = payload["message"]
            print("Response: " + message)
            audio.play(payload["src"])
        elif item["type"] == "end":
            print("-----END-----")
            vf.user_state.delete()
            audio.beep()
            return True 
    return False

def main():

    #Voiceflow setup using python package from pip
    vf = Voiceflow(
        api_key=os.getenv('VF_API_KEY'),
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
    streaming_config = speech.StreamingRecognitionConfig(
        config=google_asr_config, interim_results=True
    )

    with audio.MicrophoneStream(RATE, CHUNK) as stream:
        while True:
            input("Press Enter to start the voice assistant...")
            audio.beep()
            end = False

            vf_response = vf.interact.launch(config={'tts': True})
            end = handle_vf_response(vf, vf_response)

            while not end: 
                stream.start_buf()
                audio_generator = stream.generator()
                requests = (
                    speech.StreamingRecognizeRequest(audio_content=content)
                    for content in audio_generator
                )

                responses = google_asr_client.streaming_recognize(streaming_config, requests)
                utterance = audio.process(responses)
                stream.stop_buf()

                vf_response = vf.interact.text(user_input=utterance, config={'tts': True})
                end = handle_vf_response(vf, vf_response)


if __name__ == "__main__":
    main()
