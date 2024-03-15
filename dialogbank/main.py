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

import tty, sys, termios

from blinkt import set_pixel, show
import socket

class LEDStatusManager():

    NO_DATA = 0
    WIFI_OFF = 1
    WIFI_ON = 2
    BOOTING = 1
    WAITING = 2
    CONVERSATION_RUNNING = 3
    UNSUCCESSFUL_REQUEST = 1
    SUCCESSFUL_REQUEST = 2
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
             WAITING: 'BLUE',
             CONVERSATION_RUNNING: 'GREEN'},
        2 : {NO_DATA: 'WHITE',
             UNSUCCESSFUL_REQUEST: 'RED',
             SUCCESSFUL_REQUEST: 'GREEN'},
        3 : {NO_DATA: 'WHITE',
             UNSUCCESSFUL_REQUEST: 'RED',
             SUCCESSFUL_REQUEST: 'GREEN'},
        4 : {NO_DATA: 'WHITE',
             UNSUCCESSFUL_REQUEST: 'RED',
             SUCCESSFUL_REQUEST: 'GREEN'},
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
        
    def check_internet_availability(self, host="8.8.8.8", port=53, timeout=3):
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
        
    def __del__(self):
        self.status.shm.close()
        if self.main_process:
            #TODO: a bit hacky?
            self.status.shm.unlink()

#TODO: somewhat hacky keyboard input but works without sudo, check if better options.
filedescriptors = termios.tcgetattr(sys.stdin)
tty.setcbreak(sys.stdin)
x = 0

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

def run_dialogbench(voiceflow_client: Voiceflow, google_asr_client: speech.SpeechClient, google_streaming_config: speech.StreamingRecognitionConfig, elevenlabs_client: ElevenLabs, audio_player: audio.AudioPlayer, shared_status_list: shared_memory.ShareableList):
    led_status_manager = LEDStatusManager(shared_status_list)
    led_status_manager.update('APPLICATION', LEDStatusManager.CONVERSATION_RUNNING)

    with audio.MicrophoneStream(RATE, CHUNK) as stream:
        # Each loop iteration represents one interaction of one user with the voice assistant
        end = False
        audio_player.async_waiting_tone() #signal processing to user

        log.debug("[Voiceflow]: Requesting first voiceflow interaction.", voiceflow_user_id=voiceflow_client.user_id)
        vf_response = voiceflow_client.interact.launch()
        end = handle_vf_response(voiceflow_client, vf_response, elevenlabs_client, audio_player)

        set_pixel(7,255,0,0)
        show()
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

def wait_for_start_signal(led_status_manager):
    #Busy wait is necessary as a simple way to continue polling WIFI status.
    #TODO: Perhaps move to WIFI updating process.
    while True:
        led_status_manager.update_wifi_availability()
        userText, timedOut = timedKey("Press any key to start the voice assistant", timeout=5)
        if (not timedOut):
            return

def main():
    led_status_manager = LEDStatusManager()
    led_status_manager.update_wifi_availability()

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
        wait_for_start_signal(led_status_manager)
        p = Process(target=run_dialogbench, args=(voiceflow_client, google_asr_client, google_streaming_config, elevenlabs_client, audio_player, led_status_manager.status))
        p.start()
        while True:  # making a loop
            x = sys.stdin.read(1)[0]
            led_status_manager.update_wifi_availability()
            if (x == 'q'):
                p.terminate()
                log.debug("Terminated process due to keyboard input.")
                break

#TODO on exit kill all processes!
                
if __name__ == "__main__":
    main()