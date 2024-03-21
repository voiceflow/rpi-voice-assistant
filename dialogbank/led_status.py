from multiprocessing import shared_memory
import socket
from blinkt import set_pixel, show

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
        'WHITE': (0, 0, 0),
        'PINK': (255, 105, 180),
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
        #LED #Status #Color
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
             LISTENING: 'PINK'},
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
            self.status.shm.unlink()