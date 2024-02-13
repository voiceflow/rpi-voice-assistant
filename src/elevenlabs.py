import asyncio
from pathlib import Path
import hashlib
import re
import signal
import timeit
import requests
import structlog
from collections.abc import Sequence, Iterator

log = structlog.get_logger(__name__)

class Cache:
    def __init__(self, cache_dir: Path):
        self.dir = cache_dir
        # The default directory currently uses a directory relative to the current working
        # directory to cache audio files.
        # Might make sense to use a temporary directory to ensure the cache is cleaned up
        # after the application is terminated.
        self.dir.mkdir(parents=True, exist_ok=True)
        log.debug("[Elevenlabs]: Initializing file system cache", path=str(self.dir))

    def set(self, key: Sequence[str], data: bytes):
        file = self.get_file(key)
        file.write_bytes(data)

    def get(self, key: Sequence[str]) -> bytes | None:
        file = self.get_file(key)

        if not file.is_file():
            log.debug("[Elevenlabs]: Cache miss", key=self.get_hash(key))
            return None

        log.debug("[Elevenlabs]: Cache hit", key=self.get_hash(key))
        return file.read_bytes()

    def get_file(self, key: Sequence[str]):
        return self.dir.joinpath(self.get_hash(key))

    def get_hash(self, key: Sequence[str]) -> str:
        encoding = "utf-8"
        digest = hashlib.sha256()
        
        for item in key:
            digest.update(item.encode(encoding))

        return digest.hexdigest()

class ElevenLabs:
    """A wrapper class to access the ElevenLabs API with caching."""
    def __init__(self, api_key: str, voice_id: str, cache_dir=Path.cwd().joinpath("cache")):
        self.api_key = api_key
        self.voice_id = voice_id
        self.cache = Cache(cache_dir)

    def generate_audio_stream(self, text: str) -> Iterator[bytes]:
        segments = self.split_text(text)
        return self.generate_audio_parallel(segments=segments)
    
    def generate_audio_elevenlabs(self, text: str) -> Iterator[bytes]:
        """Run speech synthesis via ElevenLabs API and return an MP3 bytestream."""
        headers = { "xi-api-key": self.api_key }
        query = { "optimize_streaming_latency": "4" }

        payload = {
            "model_id": "eleven_multilingual_v2",
            "output_format": "mp3_22050_32",
            "text": text,
        }

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream"

        log.debug(f"[Elevenlabs]: Generating audio", text=text)
        start = timeit.default_timer()
        response = requests.post(url, json=payload, headers=headers, params=query)
        end = timeit.default_timer()
        log.debug(f"[Elevenlabs]: Successfully generated audio", took=round(end - start, 2), text=text)

        chunks = response.iter_content(chunk_size=2048)

        return chunks
    
    def generate_audio(self, text: str) -> Iterator[bytes]:
        cache_key = (text, self.voice_id)

        if self.cache:
            cached_audio = self.cache.get(cache_key)

            if cached_audio:
                yield cached_audio
                return

        chunks = self.generate_audio_elevenlabs(text=text)
        buffer = bytearray()

        # Yield the individual audio chunks, but also add them to a buffer to cache the whole audio
        for chunk in chunks:
            if self.cache:
                buffer.extend(chunk)

            yield chunk

        if self.cache and len(buffer) > 0:
            self.cache.set(cache_key, buffer)
    
    def generate_audio_parallel(self, segments: Sequence[str]) -> Iterator[bytes]:
        """Run speech synthesis for the given list of text segments in parallel and return an MP3 bytestream.
        The MP3 bytestream contains synthesiszed audio matching the order of the input text segments."""
        loop = asyncio.get_event_loop()

        futures = [
            loop.run_in_executor(None, self.generate_audio, segment)
            for segment in segments
        ]

        # I don't understand exactly why, but waiting for the first audio generation request has to happen
        # outside of the loop, otherwise time measurements are incorrect
        first_future = futures.pop(0)
        before_first_audio = timeit.default_timer()
        chunks = self._sync_wait_for_future(loop, first_future)
        yield from chunks
        after_first_audio = timeit.default_timer()
        log.debug("[Elevenlabs]: Time to first audio", took=round(after_first_audio - before_first_audio, 2))

        for future in futures:
            chunks = self._sync_wait_for_future(loop, future)
            yield from chunks
    
    def split_text(self, text: str) -> list[str]:
        """Split text into multiple text segments that can be synthesized to audio separately."""
        sentences = []
        pattern = r"[\.?!]+"

        previous_end = 0

        for match in re.finditer(pattern, text):
            sentence = text[previous_end:match.end()]
            sentences.append(sentence.strip())
            previous_end = match.end()

        return sentences
    
    def _sync_wait_for_future(self, loop: asyncio.AbstractEventLoop, future: asyncio.Future):
        # Gracefully stop asyncio task when receiving system signals
        loop.add_signal_handler(signal.SIGINT, future.cancel)
        loop.add_signal_handler(signal.SIGTERM, future.cancel)
        return loop.run_until_complete(future)


    

    