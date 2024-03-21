from collections.abc import Iterator
import subprocess
from gtts import gTTS
import pyaudio
import queue
import base64
import os
import structlog
import time

SYS_BEEP_BEEP_PATH = os.path.join(os.path.dirname(__file__),"assets/beepbeep.wav")
SYS_BEEP_PATH = os.path.join(os.path.dirname(__file__),"assets/beep.wav")
SYS_TYPING_PATH = os.path.join(os.path.dirname(__file__), "assets/keyboard_typing.wav")

log = structlog.get_logger(__name__)


class MicrophoneStream(object):
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self, rate, chunk, timeout = 10):
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

class AudioPlayer():
    """
        Audio player for playing different formats of audio as subprocesses.
        Tracks the current audio process to stop it if needed (e.g. when playing a new audio or the program exits).
    """
    def __init__(self):
        self.audio_process = None

    def __del__(self):
        log.debug("[Audio]: Stopping AudioPlayer.")
        self.stop()

    def stop(self):
        if self.audio_process:
            self.audio_process.terminate()
            self.audio_process = None

    # Play audio/mpeg MIME content
    def play(self, encoding_str):
        filename = '/tmp/response.mp3'
        decode_bytes = base64.b64decode(encoding_str.split("data:audio/mpeg;base64,",1)[1])
        with open(filename, "wb") as wav_file:
            wav_file.write(decode_bytes)
        self.play_mp3(filename)

    def play_audio_stream(self, chunks: Iterator[bytes]):
        """Play an audio bytestream using the mpv media player."""
        mpv_command = ["mpv", "--no-cache", "--no-terminal", "--", "fd://0"]
        mpv_proc = subprocess.Popen(
            mpv_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Create first audio chunk from generator before stopping current audio.
        first_chunk = next(chunks)
        self.stop()
        self.audio_process = mpv_proc
        mpv_proc.stdin.write(first_chunk)
        mpv_proc.stdin.flush()

        for chunk in chunks:
            mpv_proc.stdin.write(chunk)
            mpv_proc.stdin.flush()

        if mpv_proc.stdin:
            mpv_proc.stdin.close()

        mpv_proc.wait()

    def play_mp3(self, filename):
        # Convert mp3 to wav
        # HACK: this is needed since playing the audio with mpg123 directly causes clicking at the beginning and end of playback
        subprocess.run(["mpg123", "-w", f"{filename}.wav", filename], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.play_wav(filename+'.wav')

    def play_wav(self, filename):
        self.stop()
        self.audio_process = subprocess.Popen(["aplay", filename], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Text-to-speech using Google TTS
    def speak(self, text):
        tts = gTTS(text=text, lang='en')
        filename = '/tmp/tts.mp3'
        tts.save(filename)
        self.play_mp3(filename)

    def beep(self):
        self.play_wav(SYS_BEEP_PATH)

    def beepbeep(self):
        self.play_wav(SYS_BEEP_BEEP_PATH)

    def async_waiting_tone(self):
        self.play_wav(os.getenv('WAIT_TONE_PATH', SYS_TYPING_PATH))

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
            log.debug("[Google ASR]: Got Utterance", transcript=transcript)
            return transcript