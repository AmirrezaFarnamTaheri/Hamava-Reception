"""Bounded PCM turns and WAV conversion, independent of carrier transports."""
from __future__ import annotations

import audioop
import io
import wave
from dataclasses import dataclass, field


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    if len(pcm) % 2 or not 8000 <= sample_rate <= 192000:
        raise ValueError("Expected aligned PCM at a supported sample rate")
    result = io.BytesIO()
    with wave.open(result, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)
    return result.getvalue()


def decode_wav(audio: bytes, target_rate: int = 8000) -> bytes:
    if not 8000 <= target_rate <= 48000 or len(audio) > 8_000_000:
        raise ValueError("WAV output exceeds supported limits")
    try:
        with wave.open(io.BytesIO(audio), "rb") as stream:
            rate, frames, channels = stream.getframerate(), stream.getnframes(), stream.getnchannels()
            if (stream.getsampwidth() != 2 or channels not in {1, 2} or not 8000 <= rate <= 192000
                    or not 0 < frames <= rate * 60):
                raise ValueError("Expected bounded signed 16-bit mono/stereo WAV")
            pcm = stream.readframes(frames)
            if len(pcm) != frames * channels * 2:
                raise ValueError("Truncated WAV")
            if channels == 2:
                pcm = audioop.tomono(pcm, 2, .5, .5)
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid WAV") from exc
    if rate != target_rate:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, target_rate, None)
    return pcm


@dataclass
class TurnBuffer:
    """Energy endpointing baseline. Tune on phone audio; no emotion inference.

    The long silence window deliberately retains hesitant digit strings.
    A calibrated speech VAD can replace this interface without touching bookings.
    """
    sample_rate: int = 8000
    threshold: int = 400
    end_silence_seconds: float = 1.0
    max_seconds: float = 20.0
    min_speech_seconds: float = 0.12
    _frames: bytearray = field(default_factory=bytearray)
    _leading: bytearray = field(default_factory=bytearray)
    _speech_samples: int = 0
    _silent_samples: int = 0
    speaking: bool = False

    def reset(self) -> None:
        self._frames.clear()
        self._leading.clear()
        self._speech_samples = self._silent_samples = 0
        self.speaking = False

    def push(self, pcm: bytes) -> tuple[bytes | None, bool]:
        if len(pcm) % 2:
            raise ValueError("Unaligned PCM frame")
        if not pcm:
            return None, False
        speech = audioop.rms(pcm, 2) >= self.threshold
        started = False
        count = len(pcm) // 2
        if speech:
            self._speech_samples += count
            self._silent_samples = 0
            if not self.speaking:
                self._leading.extend(pcm)
                if self._speech_samples >= self.sample_rate * self.min_speech_seconds:
                    self.speaking = started = True
                    self._frames.extend(self._leading)
                    self._leading.clear()
            else:
                self._frames.extend(pcm)
        elif self.speaking:
            self._silent_samples += count
            self._frames.extend(pcm)
        else:
            self._speech_samples = 0
            self._leading.extend(pcm)
            maximum = int(self.sample_rate * .2) * 2
            if len(self._leading) > maximum:
                del self._leading[:-maximum]
        finished = self.speaking and (self._silent_samples >= self.sample_rate * self.end_silence_seconds
                                      or len(self._frames) >= self.sample_rate * self.max_seconds * 2)
        if finished:
            pcm = bytes(self._frames)
            output_rate = min(16000, self.sample_rate)
            if self.sample_rate != output_rate:
                pcm, _ = audioop.ratecv(pcm, 2, 1, self.sample_rate, output_rate, None)
            result = wav_bytes(pcm, output_rate)
            self.reset()
            return result, started
        return None, started

