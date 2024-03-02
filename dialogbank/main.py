import os
import structlog
import uuid

from dotenv import load_dotenv
from google.cloud import speech_v1 as speech

from . import audio
from .voiceflow import Voiceflow
from .elevenlabs import ElevenLabs

from typing import Dict, Any
JSON = Dict[str, Any]

# Setup
load_dotenv()

# Google ASR Config Values
RATE = 16000
CHUNK = 128
language_code = "de-DE"  #BCP-47 language tag

log = structlog.get_logger(__name__)

def handle_vf_response(vf: Voiceflow, vf_response: JSON, el: ElevenLabs, audio_player: audio.AudioPlayer):
    for item in vf_response:
        if item["type"] == "speak":

            payload = item["payload"]
            message = payload["message"]
            log.debug("Voiceflow: Got response", response=message)

            if "src" in payload:
                #play voiceflow generated audio, for using voiceflow set config={"tts" : True} in the interact calls
                audio_player.play(payload["src"])
            else:
                stream = el.generate_audio_stream(message)
                audio_player.play_audio_stream(stream)

        elif item["type"] == "end":
            log.debug("[Voiceflow]: Got end of interaction.")
            log.debug("[Voice Assistant]: =========END OF INTERACTION=========")
            vf.user_state.delete()
            return True 
    return False

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

    audio_player = audio.AudioPlayer()

    with audio.MicrophoneStream(RATE, CHUNK) as stream:
        # Each loop iteration represents one interaction of one user with the voice assistant
        while True:
            voiceflow_client.user_id = uuid.uuid4()
            log.debug("[Voice Assistant]: Starting voice assistant", voiceflow_user_id=voiceflow_client.user_id)
            input("Press Enter to start the voice assistant...")

            end = False
            audio_player.async_waiting_tone() #signal processing to user

            log.debug("[Voiceflow]: Requesting first voiceflow interaction.", voiceflow_user_id=voiceflow_client.user_id)
            vf_response = voiceflow_client.interact.launch()
            end = handle_vf_response(voiceflow_client, vf_response, elevenlabs_client, audio_player)

            while not end:
                audio_player.beep() #signal start of listening to user
                log.debug("[Voice Assistant]: Start listening.")
                stream.start_buf()

                audio_generator = stream.generator()
                requests = (
                    speech.StreamingRecognizeRequest(audio_content=content)
                    for content in audio_generator
                )

                responses = google_asr_client.streaming_recognize(google_streaming_config, requests)
                utterance = audio.process(responses)
                
                log.debug("[Google ASR]: Recognized utterance", utterance=utterance)
                stream.stop_buf()
                log.debug("[Voice Assistant]: Stop listening.")
                
                audio_player.async_waiting_tone() #signal processing to user
                vf_response = voiceflow_client.interact.text(user_input=utterance)
                end = handle_vf_response(voiceflow_client, vf_response, elevenlabs_client, audio_player)

if __name__ == "__main__":
    main()