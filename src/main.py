import os
import time
import struct
import sys
import yaml
import pvporcupine
from google.cloud import speech_v1 as speech

import audio
from pixels import Pixels
from voiceflow import Voiceflow

RATE = 16000
language_code = "en-US"  # a BCP-47 language tag

def load_config(config_file="config.yaml"):
    with open(config_file) as file:
        # The FullLoader parameter handles the conversion from YAML
        # scalar values to Python the dictionary format
        return yaml.load(file, Loader=yaml.FullLoader)


def main():
    config = load_config()
    leds = Pixels()
    leds.wakeup()

    # Wakeword setup
    porcupine = pvporcupine.create(keywords=config["wakewords"])
    CHUNK = porcupine.frame_length  # 512 entries

    # Voiceflow setup
    vf = Voiceflow(os.getenv('VF_API_KEY', "dummy_key"), config["vf_VersionID"])

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
        leds.off()
        print("Starting voice assistant!")
        while True:
            pcm = stream.get_sync_frame()
            if len(pcm) == 0:
                # Protects against empty frames
                continue
            pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)
            keyword_index = porcupine.process(pcm)

            if keyword_index >= 0:
                print("Wakeword Detected")
                leds.wakeup()
                audio.beep()
                end = False
                while not end: 
                    if vf.state_uninitialized(): 
                        # First session
                        print("Initializing first session")
                        leds.think()
                        response = vf.init_state()
                    else:
                        stream.start_buf()  # Only start the stream buffer when we detect the wakeword
                        audio_generator = stream.generator()
                        requests = (
                            speech.StreamingRecognizeRequest(audio_content=content)
                            for content in audio_generator
                        )

                        responses = google_asr_client.streaming_recognize(streaming_config, requests)

                        # Now, put the transcription responses to use.
                        utterance = audio.process(responses)
                        stream.stop_buf()

                        # Send request to VF service and get response
                        leds.think()
                        response = vf.interact(utterance)                    
                    
                    for item in response["trace"]:
                        if item["type"] == "speak":
                            payload = item["payload"]
                            message = payload["message"]
                            print("Response: " + message)
                            leds.speak()
                            audio.play(payload["src"])
                            leds.off()
                        elif item["type"] == "end":
                            print("-----END-----")
                            vf.clear_state()
                            end = True
                            audio.beep()
                            leds.off()

if __name__ == "__main__":
    main()
