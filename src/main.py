import os
import structlog
import uuid

from dotenv import load_dotenv
from google.cloud import speech_v1 as speech

import audio
from voiceflow import Voiceflow
from elevenlabs import ElevenLabs

from typing import Dict, Any
JSON = Dict[str, Any]
    
def handle_vf_response(vf: Voiceflow, vf_response: JSON, el: ElevenLabs):
    for item in vf_response:
        if item["type"] == "speak":

            payload = item["payload"]
            message = payload["message"]
            print("Response: " + message)

            if "src" in payload:
                #play voiceflow generated audio
                audio.play(payload["src"])
            else:
                stream = el.generate_audio_stream(message)
                audio.play_audio_stream(stream)

        elif item["type"] == "end":
            print("-----END-----")
            vf.user_state.delete()
            return True 
    return False

# Setup
load_dotenv()

# Google ASR Config Values
RATE = 16000
CHUNK = 128
language_code = "de-DE"  #BCP-47 language tag

log = structlog.get_logger(__name__)

def main():

    voiceflow_client = Voiceflow(
        api_key=os.getenv('VF_API_KEY', "dummy_key"),
        user_id=uuid.uuid4()
    )
    # Remove any potential user state to always start from beginning of voice assistant
    voiceflow_client.user_state.delete()

    google_asr_client = speech.SpeechClient()
    google_asr_config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code=language_code,
    )
    google_streaming_config = speech.StreamingRecognitionConfig(
        config=google_asr_config, interim_results=False
    )

    elevenlabs_client = ElevenLabs(
            api_key=os.getenv('EL_API_KEY', "dummy_key"), 
            voice_id=os.getenv('EL_VOICE_ID', "dummy_key"))

    with audio.MicrophoneStream(RATE, CHUNK) as stream:
        # Each loop iteration represents one interaction of one user with the voice assistant
        while True:
            voiceflow_client.user_id = uuid.uuid4()
            input("Press Enter to start the voice assistant...")

            end = False
            vf_response = voiceflow_client.interact.launch()
            end = handle_vf_response(voiceflow_client, vf_response, elevenlabs_client)

            while not end:
                audio.beep()
                stream.start_buf()

                audio_generator = stream.generator()
                requests = (
                    speech.StreamingRecognizeRequest(audio_content=content)
                    for content in audio_generator
                )

                responses = google_asr_client.streaming_recognize(google_streaming_config, requests)
                utterance = audio.process(responses)
                stream.stop_buf()
                
                vf_response = voiceflow_client.interact.text(user_input=utterance)
                end = handle_vf_response(voiceflow_client, vf_response, elevenlabs_client)

if __name__ == "__main__":
    main()