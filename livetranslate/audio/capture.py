"""WASAPI loopback capture of what the PC is playing, delivered as 16 kHz mono float32."""

import logging
import queue

import numpy as np
import pyaudiowpatch as pyaudio
import soxr

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


def _find_default_loopback(pa: pyaudio.PyAudio) -> dict:
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    speakers = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if speakers.get("isLoopbackDevice"):
        return speakers
    for loopback in pa.get_loopback_device_info_generator():
        if speakers["name"] in loopback["name"]:
            return loopback
    raise RuntimeError(f"No loopback device found for default output '{speakers['name']}'")


def list_loopback_devices() -> list[dict]:
    pa = pyaudio.PyAudio()
    try:
        default = _find_default_loopback(pa)
        devices = list(pa.get_loopback_device_info_generator())
        for d in devices:
            d["isDefault"] = d["index"] == default["index"]
        return devices
    finally:
        pa.terminate()


class LoopbackCapture:
    """Captures system audio and pushes 16 kHz mono float32 chunks onto `out_queue`.

    With `raw=True` (music mode) it pushes the device's own stereo at its native rate
    instead, wrapped in `RawAudio`, because the vocal separator needs the full-quality signal.

    WASAPI loopback only delivers data while something is playing, so the queue
    simply goes quiet during silence.
    """

    def __init__(self, out_queue: "queue.Queue[np.ndarray]", device_index: int | None = None,
                 raw: bool = False):
        self.out_queue = out_queue
        self.raw = raw
        self._rate = 0
        self.device_index = device_index
        self.device_name = ""
        self._pa: pyaudio.PyAudio | None = None
        self._stream = None
        self._resampler: soxr.ResampleStream | None = None
        self._channels = 0

    def start(self) -> None:
        self._pa = pyaudio.PyAudio()
        if self.device_index is None:
            dev = _find_default_loopback(self._pa)
        else:
            dev = self._pa.get_device_info_by_index(self.device_index)
        self.device_name = dev["name"]
        rate = int(dev["defaultSampleRate"])
        self._rate = rate
        self._channels = int(dev["maxInputChannels"])
        self._resampler = soxr.ResampleStream(rate, SAMPLE_RATE, 1, dtype="float32", quality="HQ")
        log.info("Capturing '%s' (%d Hz, %d ch)", self.device_name, rate, self._channels)
        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self._channels,
            rate=rate,
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=rate // 50,  # 20 ms
            stream_callback=self._callback,
        )
        self._stream.start_stream()

    def _callback(self, in_data, frame_count, time_info, status):
        frames = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self._channels)
        if self.raw:
            from .separator import RawAudio
            self.out_queue.put(RawAudio(frames.copy(), self._rate))
            return (None, pyaudio.paContinue)
        mono = frames.mean(axis=1)
        out = self._resampler.resample_chunk(mono)
        if out.size:
            self.out_queue.put(out)
        return (None, pyaudio.paContinue)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None
