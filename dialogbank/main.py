import os
import structlog
import uuid

from dotenv import load_dotenv
from google.cloud import speech_v1 as speech
from multiprocessing import Process, shared_memory

from . import audio
from .voiceflow import Voiceflow
from .elevenlabs import ElevenLabs
from pytimedinput import timedKey

from typing import Dict, Any
JSON = Dict[str, Any]

from blinkt import set_pixel, show
import socket

class LEDStatusManager():

    NO_DATA = 0
    WIFI_OFF = 1
    WIFI_ON = 2
    BOOTING = 1
    READY = 2
    CONVERSATION_RUNNING = 3
    UNSUCCESSFUL_REQUEST = 1
    SUCCESSFUL_REQUEST = 2
    RUNNING_REQUEST = 3
    LISTENING = 1

    colors = {
        'RED' : (255, 0, 0),
        'GREEN' : (0, 255, 0),
        'BLUE' : (0, 0, 255),
        'YELLOW': (255, 255, 0),
        'WHITE': (0, 0, 0)
    }

    #cheap bimap to allow easy access
    leds = {
        0 : 'WIFI',
        1 : 'APPLICATION',
        2 : 'GOOGLE_ASR_API',
        3 : 'VOICEFLOW_API',
        4 : 'ELEVENLABS_API',
        5 : 'LISTENING',
        'WIFI' : 0,
        'APPLICATION' : 1,
        'GOOGLE_ASR_API' : 2,
        'VOICEFLOW_API' : 3,
        'ELEVENLABS_API' : 4,
        'LISTENING' : 5
    }

    config = {
        #LED #Status #Color #Interpretation
        0 : {NO_DATA: 'WHITE',
             WIFI_OFF: 'RED', 
             WIFI_ON: 'GREEN'},
        1 : {NO_DATA: 'WHITE',
             BOOTING: 'YELLOW',
             READY: 'GREEN',
             CONVERSATION_RUNNING: 'BLUE'},
        2 : {NO_DATA: 'WHITE',
             UNSUCCESSFUL_REQUEST: 'RED',
             SUCCESSFUL_REQUEST: 'GREEN',
             RUNNING_REQUEST: 'BLUE'},
        3 : {NO_DATA: 'WHITE',
             UNSUCCESSFUL_REQUEST: 'RED',
             SUCCESSFUL_REQUEST: 'GREEN',
             RUNNING_REQUEST: 'BLUE'},
        4 : {NO_DATA: 'WHITE',
             UNSUCCESSFUL_REQUEST: 'RED',
             SUCCESSFUL_REQUEST: 'GREEN',
             RUNNING_REQUEST: 'BLUE'},
        5 : {NO_DATA: 'WHITE',
             LISTENING: 'BLUE'},
    }

    def __init__(self, shared_list=None):
        self.main_process = False

        if not shared_list:
            shared_list = shared_memory.ShareableList([0, 0, 0, 0, 0, 0, 0, 0])
            self.main_process = True

        self.status = shared_list


    def show(self):
        for led, value in self.config.items():
            cur_status = value[self.status[led]]
            set_pixel(led, *self.colors[cur_status])
        show()

    def update(self, context, status):
        led = self.leds[context]
        self.status[led] = status
        self.show()

    def update_wifi_availability(self):
        if self.check_internet_availability():
            self.update('WIFI', self.WIFI_ON)
        else:
            self.update('WIFI', self.WIFI_OFF)
        
    def check_internet_availability(self, host="8.8.8.8", port=53, timeout=2):
        """
        Host: 8.8.8.8 (google-public-dns-a.google.com)
        OpenPort: 53/tcp
        Service: domain (DNS/TCP)
        """
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            return True
        except socket.error as ex:
            print(ex)
            return False
        
    def turn_off_leds(self):
        for led in self.config:
            print(led)
            set_pixel(led, 0, 0, 0)
        show()
        
    def __del__(self):
        self.status.shm.close()
        if self.main_process:
            #TODO: a bit hacky?
            self.status.shm.unlink()

# Setup
load_dotenv()

# Google ASR Config Values
RATE = 16000
CHUNK = 128
language_code = "de-DE"  #BCP-47 language tag

log = structlog.get_logger(__name__)

def handle_vf_response(vf: Voiceflow, vf_response: JSON, el: ElevenLabs, audio_player: audio.AudioPlayer, led_status_manager: LEDStatusManager):
    for item in vf_response:
        if item["type"] == "speak":

            payload = item["payload"]
            message = payload["message"]
            log.debug("Voiceflow: Got response", response=message)

            if "src" in payload:
                #play voiceflow generated audio, for using voiceflow set config={"tts" : True} in the interact calls
                audio_player.play(payload["src"])
            else:
                try:
                    led_status_manager.update('ELEVENLABS_API', LEDStatusManager.RUNNING_REQUEST)
                    stream = el.generate_audio_stream(message)
                    led_status_manager.update('ELEVENLABS_API', LEDStatusManager.SUCCESSFUL_REQUEST)
                except Exception as e:
                    log.error("Error in Elevenlabs interaction", error=str(e))
                    led_status_manager.update('ELEVENLABS_API', LEDStatusManager.UNSUCCESSFUL_REQUEST)
                    return True #TODO: Should we rather fail completely?
                audio_player.play_audio_stream(stream)

        elif item["type"] == "end":
            log.debug("[Voiceflow]: Got end of interaction.")
            log.debug("[Voice Assistant]: =========END OF INTERACTION=========")
            vf.user_state.delete()
            return True 
    return False

def run_dialogbench(voiceflow_client: Voiceflow, google_asr_client: speech.SpeechClient, google_streaming_config: speech.StreamingRecognitionConfig, elevenlabs_client: ElevenLabs, audio_player: audio.AudioPlayer, shared_status_list: shared_memory.ShareableList):
    led_status_manager = LEDStatusManager(shared_status_list)
    led_status_manager.update('APPLICATION', LEDStatusManager.CONVERSATION_RUNNING)

    with audio.MicrophoneStream(RATE, CHUNK) as stream:
        # Each loop iteration represents one interaction of one user with the voice assistant
        end = False
        audio_player.async_waiting_tone() #signal processing to user

        #TODO: Extract to method
        try:    
            log.debug("[Voiceflow]: Requesting first voiceflow interaction.", voiceflow_user_id=voiceflow_client.user_id)
            led_status_manager.update('VOICEFLOW_API', LEDStatusManager.RUNNING_REQUEST)
            vf_response = voiceflow_client.interact.launch()
            #TODO: Check if response success -> if not, handle error
            led_status_manager.update('VOICEFLOW_API', LEDStatusManager.SUCCESSFUL_REQUEST)
        except Exception as e:
            log.error("Error in voiceflow interaction", error=str(e))
            led_status_manager.update('VOICEFLOW_API', LEDStatusManager.UNSUCCESSFUL_REQUEST)
            return

        end = handle_vf_response(voiceflow_client, vf_response, elevenlabs_client, audio_player, led_status_manager)

        while not end:
            audio_player.beep() #signal start of listening to user
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
                return
            

            stream.stop_buf()
            log.debug("[Voice Assistant]: Stop listening.")
            led_status_manager.update('LISTENING', LEDStatusManager.NO_DATA)
            
            audio_player.async_waiting_tone() #signal processing to user

            try:    
                log.debug("[Voiceflow]: Requesting first voiceflow interaction.", voiceflow_user_id=voiceflow_client.user_id)
                led_status_manager.update('VOICEFLOW_API', LEDStatusManager.RUNNING_REQUEST)
                vf_response = voiceflow_client.interact.text(user_input=utterance)
                #TODO: Check if response success -> if not, handle error
                led_status_manager.update('VOICEFLOW_API', LEDStatusManager.SUCCESSFUL_REQUEST)
            except Exception as e:
                log.error("Error in voiceflow interaction", error=str(e))
                led_status_manager.update('VOICEFLOW_API', LEDStatusManager.UNSUCCESSFUL_REQUEST)
                return
    
            end = handle_vf_response(voiceflow_client, vf_response, elevenlabs_client, audio_player, led_status_manager)

def wait_for_start_signal(led_status_manager):
    #Busy wait is necessary as a simple way to continue polling WIFI status.
    #TODO: Perhaps move to WIFI updating process.
    while True:
        led_status_manager.update_wifi_availability()
        userText, timedOut = timedKey("Press any key to start the voice assistant", timeout=5)
        if (not timedOut):
            return
        
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

#TODO: At exit also kill child processes
                
if __name__ == "__main__":
    main()