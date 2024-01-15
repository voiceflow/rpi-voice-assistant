import audio
import pvporcupine
import struct

RATE = 16000
CHUNK = 512

porcupine = pvporcupine.create(os.getenv('PVPORCUPINE_KEY', "dummy_key"), keywords=["computer"])
CHUNK = porcupine.frame_length  # 512 entries

with audio.MicrophoneStream(RATE, CHUNK) as stream:
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
            audio.beep()
            exit(0)