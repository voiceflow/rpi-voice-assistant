from gtts import gTTS
import pyaudio
import queue
import base64
import os

SYS_BEEP_BEEP_PATH = os.path.join(os.getcwd(),"assets/beepbeep.wav")
SYS_BEEP_PATH = os.path.join(os.getcwd(),"assets/beep.wav")

class MicrophoneStream(object):
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self, rate, chunk):
        self._rate = rate
        self._chunk = chunk

        # Create a thread-safe buffer of audio data
        self._buff = queue.Queue()
        self.cur_frame = []
        self.closed = True
        self.enabled = False

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            # The API currently only supports 1-channel (mono) audio
            # https://goo.gl/z757pE
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            # Run the audio stream asynchronously to fill the buffer object.
            # This is necessary so that the input device's buffer doesn't
            # overflow while the calling thread makes network requests, etc.
            stream_callback=self._fill_buffer,
        )

        self.closed = False

        return self

    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        """Continuously collect data from the audio stream, into the buffer if enabled"""
        if self.enabled:
            self._buff.put(in_data)
        self.cur_frame = in_data    # Update the current frame for wakeword detection
        return None, pyaudio.paContinue

    # Synchronously get 1 chunk from the audio stream
    def get_sync_frame(self):
        self.start_buf()
        chunk = self._buff.get()    # Blocking get
        self.stop_buf()
        return chunk

    def start_buf(self):
        self._buff = queue.Queue() # Create a new queue (clear), otherwise there might be remanents of the old queue data for the sync get chunk
        self.enabled = True

    def stop_buf(self):
        self.enabled = False

    def generator(self):
        while not self.closed:
            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]

            # Now consume whatever other data's still buffered.
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break

            yield b"".join(data)


# Process response from Google ASR
def process(responses):
    for response in responses:
        if not response.results:
            continue

        # The `results` list is consecutive. For streaming, we only care about
        # the first result being considered, since once it's `is_final`, it
        # moves on to considering the next utterance.
        result = response.results[0]
        if not result.alternatives:
            continue

        # Display the transcription of the top alternative.
        transcript = result.alternatives[0].transcript

        if result.is_final:
            print("Utterance: " + transcript)
            return transcript

# Play audio/mpeg MIME content
def play(encoding_str):
    filename = '/tmp/response.mp3'
    decode_bytes = base64.b64decode(encoding_str.split("data:audio/mpeg;base64,",1)[1])
    with open(filename, "wb") as wav_file:
        wav_file.write(decode_bytes)
    mp3_play(filename)

# Text-to-speech using Google TTS
def speak(text):
    tts = gTTS(text=text, lang='en')
    filename = '/tmp/tts.mp3'
    tts.save(filename)
    mp3_play(filename)

def beep():
    wav_play(SYS_BEEP_PATH)

def beepbeep():
    wav_play(SYS_BEEP_BEEP_PATH)

def mp3_play(filename):
    # Convert mp3 to wav
    # HACK: this is needed since playing the audio with mpg123 directly causes clicking at the beginning and end of playback
    os.system('mpg123 -w ' + filename+'.wav ' + filename + '>/dev/null 2>&1')
    wav_play(filename+'.wav')

def wav_play(filename):
    os.system('aplay ' + filename + '>/dev/null 2>&1')
