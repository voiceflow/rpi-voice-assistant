from multiprocessing import Process, shared_memory
import os

import structlog
import sys
import uuid

from dotenv import load_dotenv
from google.cloud import speech_v1 as speech
from pytimedinput import timedKey

from . import audio
from .voiceflow import Voiceflow
from .elevenlabs import ElevenLabs
from .led_status import LEDStatusManager

from typing import Dict, Any
JSON = Dict[str, Any]

# Setup
load_dotenv()

# Google ASR Config Values
RATE = 16000
CHUNK = 128
language_code = "de-DE"  #BCP-47 language tag
FAILED_REQUEST = -1

log = structlog.get_logger(__name__)

def generate_and_play_elevenlabs_audio(el: ElevenLabs, message: str, led_status_manager: LEDStatusManager, audio_player: audio.AudioPlayer) -> bool:
    """
        Generates audio using the Elevenlabs API and plays it back.
    """
    try:
        led_status_manager.update('ELEVENLABS_API', LEDStatusManager.RUNNING_REQUEST)
        stream = el.generate_audio_stream(message)
        audio_player.play_audio_stream(stream)
    except Exception as e:
        log.error("Error in Elevenlabs interaction", error=str(e))
        led_status_manager.update('ELEVENLABS_API', LEDStatusManager.UNSUCCESSFUL_REQUEST)
        sys.exit(1)
    led_status_manager.update('ELEVENLABS_API', LEDStatusManager.SUCCESSFUL_REQUEST)

def handle_vf_response(vf: Voiceflow, vf_response: JSON) -> tuple[bool, str | None]:
    messages = []
    for item in vf_response:
        if item["type"] == "speak":
            message = item["payload"]["message"]
            log.debug("[Voiceflow]: Got response", response=message)
            messages.append(message)
        elif item["type"] == "end":
            log.debug("[Voiceflow]: Got end of interaction.")
            log.debug("[Voice Assistant]: =========END OF INTERACTION=========")
            vf.user_state.delete()
            return True, None 
    if messages:
        return False, ".".join(messages)
    #Fallback: If no text message returned from Voiceflow, end interaction
    log.error("[Voiceflow]: No speak or end type in response.")
    return True, None

def is_successful_vf_response(response: JSON) -> bool:
    for item in response:
        if "type" in item:
            return True
    return False

def run_voiceflow_launch_request(voiceflow_client: Voiceflow, led_status_manager: LEDStatusManager) -> dict:
    try:    
        log.debug("[Voiceflow]: Requesting first voiceflow interaction.", voiceflow_user_id=voiceflow_client.user_id)
        led_status_manager.update('VOICEFLOW_API', LEDStatusManager.RUNNING_REQUEST)
        vf_response = voiceflow_client.interact.launch()
        if not is_successful_vf_response(vf_response):
            log.error("Unsuccessful Voiceflow API request.", error=str(e))
            led_status_manager.update('VOICEFLOW_API', LEDStatusManager.UNSUCCESSFUL_REQUEST)
            sys.exit(1)
        led_status_manager.update('VOICEFLOW_API', LEDStatusManager.SUCCESSFUL_REQUEST)
    except Exception as e:
        log.error("Error in voiceflow interaction", error=str(e))
        led_status_manager.update('VOICEFLOW_API', LEDStatusManager.UNSUCCESSFUL_REQUEST)
        sys.exit(1)
    return vf_response

def run_voiceflow_interact_request(voiceflow_client: Voiceflow, led_status_manager: LEDStatusManager, utterance: str) -> dict:
    try:    
        log.debug("[Voiceflow]: Requesting voiceflow text interaction.", voiceflow_user_id=voiceflow_client.user_id)
        led_status_manager.update('VOICEFLOW_API', LEDStatusManager.RUNNING_REQUEST)
        vf_response = voiceflow_client.interact.text(user_input=utterance)
        if not is_successful_vf_response(vf_response):
            log.error("Unsuccessful Voiceflow API request.", error=str(e))
            led_status_manager.update('VOICEFLOW_API', LEDStatusManager.UNSUCCESSFUL_REQUEST)
            sys.exit(1)        
        led_status_manager.update('VOICEFLOW_API', LEDStatusManager.SUCCESSFUL_REQUEST)
    except Exception as e:
        log.error("Error in voiceflow interaction", error=str(e))
        led_status_manager.update('VOICEFLOW_API', LEDStatusManager.UNSUCCESSFUL_REQUEST)
        sys.exit(1)
    return vf_response

def recognize_user_input(google_asr_client: speech.SpeechClient, google_streaming_config: speech.StreamingRecognitionConfig, led_status_manager: LEDStatusManager, stream) -> str:
    log.debug("[Voice Assistant]: Start listening.")
    led_status_manager.update('LISTENING', LEDStatusManager.LISTENING)
    stream.start_buf()

    audio_generator = stream.generator()
    requests = (
        speech.StreamingRecognizeRequest(audio_content=content)
        for content in audio_generator
    )

    try:
        led_status_manager.update('GOOGLE_ASR_API', LEDStatusManager.RUNNING_REQUEST)
        responses = google_asr_client.streaming_recognize(google_streaming_config, requests)
        led_status_manager.update('GOOGLE_ASR_API', LEDStatusManager.SUCCESSFUL_REQUEST)
        utterance = audio.process(responses)
        log.debug("[Google ASR]: Recognized utterance", utterance=utterance)
    except Exception as e:
        log.error("Error in Google ASR interaction", error=str(e))
        led_status_manager.update('GOOGLE_ASR_API', LEDStatusManager.UNSUCCESSFUL_REQUEST)
        sys.exit(1)
    
    stream.stop_buf()
    log.debug("[Voice Assistant]: Stop listening.")
    led_status_manager.update('LISTENING', LEDStatusManager.NO_DATA)
    return utterance

def wait_for_start_signal(led_status_manager):
    #Busy wait is necessary as a simple way to continue polling WIFI status.
    #TODO: Perhaps move to WIFI updating process.
    while True:
        led_status_manager.update_wifi_availability()
        userText, timedOut = timedKey("Press s to start the voice assistant. \n", allowCharacters="s", timeout=5)
        if (not timedOut):
            return

def run_dialogbench(voiceflow_client: Voiceflow, google_asr_client: speech.SpeechClient, google_streaming_config: speech.StreamingRecognitionConfig, elevenlabs_client: ElevenLabs, audio_player: audio.AudioPlayer, shared_status_list: shared_memory.ShareableList):
    led_status_manager = LEDStatusManager(shared_status_list)
    led_status_manager.update('APPLICATION', LEDStatusManager.CONVERSATION_RUNNING)

    with audio.MicrophoneStream(RATE, CHUNK) as stream:
        # Each loop iteration represents one interaction of one user with the voice assistant
        audio_player.async_waiting_tone() #signal processing to user

        vf_response = run_voiceflow_launch_request(voiceflow_client, led_status_manager)
        
        end, message = handle_vf_response(voiceflow_client, vf_response)

        while not end:
            generate_and_play_elevenlabs_audio(elevenlabs_client, message, led_status_manager, audio_player)
            
            audio_player.beep() #signal start of listening to user
            utterance = recognize_user_input(google_asr_client, google_streaming_config, led_status_manager, stream)
            
            audio_player.async_waiting_tone() #signal processing to user
            vf_response = run_voiceflow_interact_request(voiceflow_client, led_status_manager, utterance)

            end, message = handle_vf_response(voiceflow_client, vf_response)
            log.debug("Voiceflow generated message", message=message)
        
def main():
    #Run setup for Dialogbench Loop
    led_status_manager = LEDStatusManager()
    led_status_manager.update_wifi_availability()
    led_status_manager.update('APPLICATION', LEDStatusManager.BOOTING)

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

    while True:
        voiceflow_client.user_id = uuid.uuid4()
        audio_player.stop()
        log.debug("[Voice Assistant]: Starting voice assistant", voiceflow_user_id=voiceflow_client.user_id)
        led_status_manager.update('APPLICATION', LEDStatusManager.READY)

        wait_for_start_signal(led_status_manager)
        p = Process(target=run_dialogbench, args=(voiceflow_client, google_asr_client, google_streaming_config, elevenlabs_client, audio_player, led_status_manager.status))
        p.start()
        
        log.debug("[Dialogbench]: Running busy waiting loop to listen for interrupt signal.")
        while p.is_alive():
            led_status_manager.update_wifi_availability()
            userText, timedOut = timedKey(allowCharacters="q", timeout=3)
            if (not timedOut):
                p.terminate()
                log.debug("[Dialogbench]: Terminating process due to user interrupt.")
                break
                
if __name__ == "__main__":
    main()