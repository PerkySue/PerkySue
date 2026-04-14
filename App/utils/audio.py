"""
Capture audio : microphone, sortie système (WASAPI loopback via PyAudioWPatch, Windows), ou mix.

- ``sounddevice`` : micro (et liste des devices).
- ``system_only`` / ``mix`` : **PyAudioWPatch** (PortAudio patché) — ``WasapiSettings`` de sounddevice
  **ne** supporte **pas** loopback (pas de flag loopback dans le binding Python).

Sans PyAudioWPatch sur Windows, ``build_audio_recorder`` repasse en ``mic_only`` avec un avertissement.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

import numpy as np

logger = logging.getLogger("perkysue.audio")

# --- VAD sensitivity presets ---
# Each preset maps to (vad_aggressiveness: int, speech_ratio_threshold: float).
# vad_aggressiveness: WebRTC VAD 0 (most permissive) → 3 (most strict).
# speech_ratio_threshold: fraction of 30 ms frames in a ~100 ms chunk that must be
#   classified "speech" for the chunk to count as voice activity.
VAD_PRESETS: dict[str, tuple[int, float]] = {
    "quiet_room": (1, 0.20),
    "normal": (2, 0.30),
    "noisy": (3, 0.40),
}
VAD_DEFAULT_PRESET = "normal"


def _resolve_vad_sensitivity(raw_value: Any) -> tuple[int, float]:
    """Resolve vad_sensitivity config value → (vad_aggressiveness, speech_ratio_threshold).

    Accepts:
      - preset string: "quiet_room", "normal", "noisy"
      - raw int 0–3: legacy / advanced override (keeps ratio at 0.30)
      - None / missing: falls back to "normal"
    """
    if raw_value is None:
        return VAD_PRESETS[VAD_DEFAULT_PRESET]
    if isinstance(raw_value, bool):
        logger.warning("Invalid vad_sensitivity %r — using 'normal'", raw_value)
        return VAD_PRESETS[VAD_DEFAULT_PRESET]
    if isinstance(raw_value, (int, float)):
        agg = max(0, min(3, int(raw_value)))
        return (agg, 0.30)
    if isinstance(raw_value, str) and raw_value.strip().isdigit():
        agg = max(0, min(3, int(raw_value.strip())))
        return (agg, 0.30)
    key = str(raw_value).strip().lower()
    if key in VAD_PRESETS:
        return VAD_PRESETS[key]
    logger.warning("Unknown vad_sensitivity %r — using 'normal'", raw_value)
    return VAD_PRESETS[VAD_DEFAULT_PRESET]


def _linear_resample_mono(x: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Rééchantillonnage léger (float32 mono) sans scipy."""
    if src_sr <= 0 or dst_sr <= 0 or len(x) == 0:
        return x.astype(np.float32, copy=False)
    if src_sr == dst_sr:
        return x.astype(np.float32, copy=False)
    n_out = max(1, int(round(len(x) * float(dst_sr) / float(src_sr))))
    t_src = np.linspace(0.0, 1.0, num=len(x), endpoint=False, dtype=np.float64)
    t_dst = np.linspace(0.0, 1.0, num=n_out, endpoint=False, dtype=np.float64)
    return np.interp(t_dst, t_src, x.astype(np.float64)).astype(np.float32)


def _downmix_input_to_mono(indata: np.ndarray) -> np.ndarray:
    if indata.ndim == 1:
        return indata.copy()
    if indata.shape[1] == 1:
        return indata[:, 0].copy()
    return np.mean(indata, axis=1, dtype=np.float32)


def _get_pyaudio_wpatch():
    """Retourne le module ``pyaudiowpatch`` ou ``None`` (non Windows / pas installé)."""
    if sys.platform != "win32":
        return None
    try:
        import pyaudiowpatch as pa

        return pa
    except ImportError:
        return None


def loopback_capture_available() -> bool:
    """True si ``system_only`` / ``mix`` peuvent utiliser le loopback (Windows + PyAudioWPatch)."""
    return _get_pyaudio_wpatch() is not None


def _pawp_resolve_loopback(
    p: Any,
    pa: Any,
    *,
    sounddevice_output_index: Optional[int],
) -> dict[str, Any]:
    """
    Retourne un ``device_info`` PyAudio pour un périphérique d'**entrée** loopback WASAPI.

    ``sounddevice_output_index`` est l'index **sounddevice** de la sortie à écouter ; on aligne par **nom**
    car les index PortAudio diffèrent souvent entre hôtes / wrappers.
    """
    wasapi_info = p.get_host_api_info_by_type(pa.paWASAPI)
    default_out_idx = int(wasapi_info["defaultOutputDevice"])

    if sounddevice_output_index is None:
        if hasattr(p, "get_default_wasapi_loopback"):
            try:
                return p.get_default_wasapi_loopback()
            except LookupError:
                logger.debug("get_default_wasapi_loopback() indisponible, recherche par nom")
        default_speakers = p.get_device_info_by_index(default_out_idx)
    else:
        import sounddevice as sd

        target_name: Optional[str] = None
        try:
            target_name = str(sd.query_devices(int(sounddevice_output_index), "output")["name"])
        except Exception:
            target_name = None

        default_speakers = None
        if target_name:
            n = p.get_device_count()
            for i in range(n):
                info = p.get_device_info_by_index(i)
                if int(info.get("maxOutputChannels") or 0) <= 0:
                    continue
                if info.get("name") == target_name:
                    default_speakers = info
                    break
        if default_speakers is None:
            default_speakers = p.get_device_info_by_index(default_out_idx)

    if default_speakers.get("isLoopbackDevice"):
        return default_speakers

    for loopback in p.get_loopback_device_info_generator():
        if default_speakers["name"] in loopback["name"]:
            return loopback

    raise LookupError(
        f"Pas de loopback WASAPI pour la sortie {default_speakers.get('name')!r} — "
        "vérifiez PyAudioWPatch, la sortie par défaut Windows, ou essayez un autre loopback_device."
    )


def _int16_bytes_to_mono_float32(raw: bytes, channels: int) -> np.ndarray:
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels <= 1:
        return x
    n = len(x) // channels
    if n * channels != len(x):
        return x[: n * channels].reshape(-1, channels).mean(axis=1)
    return x.reshape(-1, channels).mean(axis=1)


class _PyAudioStreamAdapter:
    """Adapte ``stop_stream`` / ``close`` PyAudio à l'interface ``stop`` / ``close`` sounddevice."""

    def __init__(self, stream: Any):
        self._s = stream

    def stop(self) -> None:
        try:
            self._s.stop_stream()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._s.close()
        except Exception:
            pass


class BaseAudioCapture(ABC):
    """Base : VAD, silence, stop, record_until_silence."""

    def __init__(
        self,
        sample_rate: int = 16000,
        vad_aggressiveness: int = 2,
        speech_ratio_threshold: float = 0.30,
        silence_timeout: float = 2.0,
        max_duration: float = 120.0,
        on_input_level: Optional[Callable[[np.ndarray], None]] = None,
        on_input_stop: Optional[Callable[[], None]] = None,
        use_vad: bool = True,
    ):
        self.sample_rate = sample_rate
        self.vad_aggressiveness = vad_aggressiveness
        self.speech_ratio_threshold = speech_ratio_threshold
        self.silence_timeout = silence_timeout
        self.max_duration = max_duration
        self._on_input_level = on_input_level
        self._on_input_stop = on_input_stop
        self._use_vad = use_vad

        self._recording = False
        self._audio_chunks: list[np.ndarray] = []
        self._stream = None
        self._streams: list[Any] = []
        self._lock = threading.Lock()
        self._vad = None
        # Smoothing: require majority of last N chunks to be "speech" before
        # resetting the silence timer. Reduces false positives from transients.
        self._speech_ring: list[bool] = []
        self._speech_ring_size: int = 3  # ~300 ms at 100 ms chunks

    def _init_vad(self) -> None:
        if not self._use_vad:
            self._vad = None
            return
        if self._vad is not None:
            return
        try:
            import webrtcvad

            self._vad = webrtcvad.Vad(self.vad_aggressiveness)
            logger.debug("VAD WebRTC initialisé")
        except ImportError:
            logger.warning("webrtcvad non installé — pas de détection de silence auto")
            self._vad = None

    def _is_speech(self, audio_chunk: np.ndarray) -> bool:
        if self._vad is None:
            return True
        audio_int16 = (audio_chunk * 32767).astype(np.int16)
        frame_duration_ms = 30
        frame_size = int(self.sample_rate * frame_duration_ms / 1000)

        speech_frames = 0
        total_frames = 0

        for i in range(0, len(audio_int16) - frame_size, frame_size):
            frame = audio_int16[i : i + frame_size].tobytes()
            try:
                if self._vad.is_speech(frame, self.sample_rate):
                    speech_frames += 1
                total_frames += 1
            except Exception:
                total_frames += 1

        if total_frames == 0:
            return False

        return (speech_frames / total_frames) > self.speech_ratio_threshold

    def _is_speech_smoothed(self, audio_chunk: np.ndarray) -> bool:
        """Smoothed speech detection: majority vote over last 3 chunks (~300 ms)."""
        raw = self._is_speech(audio_chunk)
        self._speech_ring.append(raw)
        if len(self._speech_ring) > self._speech_ring_size:
            self._speech_ring.pop(0)
        need = self._speech_ring_size // 2 + 1
        return sum(self._speech_ring) >= need

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    def request_stop(self) -> None:
        with self._lock:
            self._recording = False

    def _close_streams(self) -> None:
        for s in self._streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._streams.clear()
        self._stream = None

    def stop(self) -> np.ndarray:
        with self._lock:
            self._recording = False

        self._close_streams()

        if self._on_input_stop is not None:
            try:
                self._on_input_stop()
            except Exception:
                pass

        if not self._audio_chunks:
            logger.warning("Aucun audio capturé")
            return np.array([], dtype=np.float32)

        audio = np.concatenate(self._audio_chunks)
        duration = len(audio) / self.sample_rate
        logger.info(f"🛑 Listening stopped: {duration:.1f}s")

        return audio

    def record_until_silence(self, on_start: Optional[Callable] = None) -> np.ndarray:
        try:
            self.start()
        except Exception:
            with self._lock:
                self._recording = False
            try:
                self._close_streams()
            except Exception:
                pass
            raise
        if on_start:
            try:
                on_start()
            except Exception:
                pass

        self._speech_ring.clear()
        last_speech_time = time.time()
        start_time = time.time()

        try:
            while self._recording:
                time.sleep(0.1)

                if time.time() - start_time > self.max_duration:
                    logger.warning("Durée max atteinte")
                    break

                if self._audio_chunks and self._vad:
                    recent = self._audio_chunks[-1] if self._audio_chunks else None
                    if recent is not None and self._is_speech_smoothed(recent):
                        last_speech_time = time.time()
                    elif time.time() - last_speech_time > self.silence_timeout:
                        logger.info("Silence detected — auto-stop")
                        break
        except KeyboardInterrupt:
            pass

        return self.stop()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @staticmethod
    def list_devices() -> list[dict]:
        import sounddevice as sd

        devices = sd.query_devices()
        try:
            default_in, _ = sd.default.device
        except Exception:
            default_in = None
        result = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] <= 0:
                continue
            result.append(
                {
                    "id": i,
                    "name": d["name"],
                    "inputs": d["max_input_channels"],
                    "is_default": (i == default_in),
                }
            )
        return result


class AudioRecorder(BaseAudioCapture):
    """Microphone seul (défaut)."""

    def __init__(
        self,
        sample_rate: int = 16000,
        vad_aggressiveness: int = 2,
        speech_ratio_threshold: float = 0.30,
        silence_timeout: float = 2.0,
        max_duration: float = 120.0,
        on_input_level: Optional[Callable[[np.ndarray], None]] = None,
        on_input_stop: Optional[Callable[[], None]] = None,
        device: Optional[int] = None,
    ):
        super().__init__(
            sample_rate=sample_rate,
            vad_aggressiveness=vad_aggressiveness,
            speech_ratio_threshold=speech_ratio_threshold,
            silence_timeout=silence_timeout,
            max_duration=max_duration,
            on_input_level=on_input_level,
            on_input_stop=on_input_stop,
            use_vad=True,
        )
        self._input_device = device

    def start(self) -> None:
        import sounddevice as sd

        self._init_vad()

        with self._lock:
            self._recording = True
            self._audio_chunks = []
        self._speech_ring.clear()

        blocksize = int(self.sample_rate * 0.1)

        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Audio status: {status}")
            if self._recording:
                mono = _downmix_input_to_mono(indata)
                self._audio_chunks.append(mono)
                if self._on_input_level is not None:
                    try:
                        self._on_input_level(mono)
                    except Exception:
                        pass

        kwargs: dict[str, Any] = dict(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            callback=audio_callback,
        )
        if self._input_device is not None:
            kwargs["device"] = self._input_device

        self._stream = sd.InputStream(**kwargs)
        self._streams = [self._stream]
        self._stream.start()
        logger.info("🎙️ Listening (mic)...")

    @staticmethod
    def list_devices() -> list[dict]:
        return BaseAudioCapture.list_devices()


class SystemLoopbackRecorder(BaseAudioCapture):
    """Windows : sortie système via PyAudioWPatch (loopback WASAPI)."""

    def __init__(
        self,
        sample_rate: int = 16000,
        vad_aggressiveness: int = 2,
        speech_ratio_threshold: float = 0.30,
        silence_timeout: float = 2.0,
        max_duration: float = 120.0,
        on_input_level: Optional[Callable[[np.ndarray], None]] = None,
        on_input_stop: Optional[Callable[[], None]] = None,
        loopback_output_device: Optional[int] = None,
    ):
        super().__init__(
            sample_rate=sample_rate,
            vad_aggressiveness=vad_aggressiveness,
            speech_ratio_threshold=speech_ratio_threshold,
            silence_timeout=silence_timeout,
            max_duration=max_duration,
            on_input_level=on_input_level,
            on_input_stop=on_input_stop,
            use_vad=True,
        )
        self._loopback_output_device = loopback_output_device
        self._pawp_pa: Any = None

    def _close_streams(self) -> None:
        super()._close_streams()
        if self._pawp_pa is not None:
            try:
                self._pawp_pa.terminate()
            except Exception:
                pass
            self._pawp_pa = None

    def start(self) -> None:
        pa = _get_pyaudio_wpatch()
        if pa is None:
            raise RuntimeError("PyAudioWPatch requis pour system_only (pip install PyAudioWPatch)")

        self._init_vad()

        with self._lock:
            self._recording = True
            self._audio_chunks = []
        self._speech_ring.clear()

        p = None
        try:
            p = pa.PyAudio()
            dev = _pawp_resolve_loopback(
                p,
                pa,
                sounddevice_output_index=self._loopback_output_device,
            )
            ch = int(dev.get("maxInputChannels") or 2)
            if ch <= 0:
                ch = 2
            rate = int(dev.get("defaultSampleRate") or self.sample_rate)
            if rate <= 0:
                rate = self.sample_rate
            chunk = max(int(rate * 0.1), 1024)
            dev_index = int(dev["index"])
            capture_self = self

            def callback(in_data, frame_count, time_info, status):
                if not capture_self._recording:
                    return (None, pa.paComplete)
                if status:
                    logger.warning("PyAudioWPatch loopback status: %s", status)
                mono = _int16_bytes_to_mono_float32(in_data, ch)
                mono = _linear_resample_mono(mono, rate, capture_self.sample_rate)
                capture_self._audio_chunks.append(mono)
                if capture_self._on_input_level is not None:
                    try:
                        capture_self._on_input_level(mono)
                    except Exception:
                        pass
                return (None, pa.paContinue)

            stream = p.open(
                format=pa.paInt16,
                channels=ch,
                rate=rate,
                frames_per_buffer=chunk,
                input=True,
                input_device_index=dev_index,
                stream_callback=callback,
            )
            stream.start_stream()
            self._pawp_pa = p
            p = None
            self._streams = [_PyAudioStreamAdapter(stream)]
            self._stream = stream
            logger.info(
                "🎙️ Listening (system loopback, PyAudioWPatch) — device #%s %s native_sr=%s → %s",
                dev_index,
                dev.get("name", "?"),
                rate,
                self.sample_rate,
            )
        finally:
            if p is not None:
                try:
                    p.terminate()
                except Exception:
                    pass


class MixedDualInputRecorder(BaseAudioCapture):
    """Mix micro (sounddevice) + loopback (PyAudioWPatch). VAD sur le signal mixé (auto-stop silence)."""

    def __init__(
        self,
        sample_rate: int = 16000,
        vad_aggressiveness: int = 2,
        speech_ratio_threshold: float = 0.30,
        silence_timeout: float = 2.0,
        max_duration: float = 120.0,
        on_input_level: Optional[Callable[[np.ndarray], None]] = None,
        on_input_stop: Optional[Callable[[], None]] = None,
        mic_device: Optional[int] = None,
        loopback_output_device: Optional[int] = None,
        mix_mic_gain: float = 1.0,
        mix_loopback_gain: float = 0.8,
    ):
        super().__init__(
            sample_rate=sample_rate,
            vad_aggressiveness=vad_aggressiveness,
            speech_ratio_threshold=speech_ratio_threshold,
            silence_timeout=silence_timeout,
            max_duration=max_duration,
            on_input_level=on_input_level,
            on_input_stop=on_input_stop,
            use_vad=True,
        )
        self._mic_device = mic_device
        self._loopback_output_device = loopback_output_device
        self._mix_mic_gain = float(mix_mic_gain)
        self._mix_loopback_gain = float(mix_loopback_gain)
        self._mic_q: queue.Queue[Optional[np.ndarray]] = queue.Queue(maxsize=64)
        self._lb_q: queue.Queue[Optional[np.ndarray]] = queue.Queue(maxsize=64)
        self._mixer_thread: Optional[threading.Thread] = None
        self._mic_native_sr = sample_rate
        self._lb_native_sr = sample_rate
        self._pawp_pa: Any = None
        self._mic_chunks: list[np.ndarray] = []
        self._lb_chunks: list[np.ndarray] = []
        self._last_split_capture: Optional[dict[str, Any]] = None

    def _pawp_start_loopback_queue(self, lb_q: queue.Queue) -> tuple[int]:
        """Démarre le loopback vers ``lb_q`` ; définit ``self._pawp_pa`` et ajoute l'adaptateur à ``self._streams``."""
        pa = _get_pyaudio_wpatch()
        if pa is None:
            raise RuntimeError("PyAudioWPatch requis pour mix (pip install PyAudioWPatch)")

        p = pa.PyAudio()
        try:
            dev = _pawp_resolve_loopback(
                p,
                pa,
                sounddevice_output_index=self._loopback_output_device,
            )
            ch = int(dev.get("maxInputChannels") or 2)
            if ch <= 0:
                ch = 2
            rate = int(dev.get("defaultSampleRate") or self.sample_rate)
            if rate <= 0:
                rate = self.sample_rate
            chunk = max(int(rate * 0.1), 1024)
            dev_index = int(dev["index"])
            capture_self = self

            def callback(in_data, frame_count, time_info, status):
                if not capture_self._recording:
                    return (None, pa.paComplete)
                if status:
                    logger.warning("PyAudioWPatch loopback status: %s", status)
                mono = _int16_bytes_to_mono_float32(in_data, ch)
                mono = _linear_resample_mono(mono, rate, capture_self.sample_rate)
                try:
                    lb_q.put_nowait(mono)
                except queue.Full:
                    pass
                return (None, pa.paContinue)

            stream = p.open(
                format=pa.paInt16,
                channels=ch,
                rate=rate,
                frames_per_buffer=chunk,
                input=True,
                input_device_index=dev_index,
                stream_callback=callback,
            )
            stream.start_stream()
            self._pawp_pa = p
            self._streams.append(_PyAudioStreamAdapter(stream))
            return rate
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass
            raise

    def _close_streams(self) -> None:
        with self._lock:
            self._recording = False
        try:
            self._mic_q.put_nowait(None)
        except Exception:
            pass
        try:
            self._lb_q.put_nowait(None)
        except Exception:
            pass
        if self._mixer_thread and self._mixer_thread.is_alive():
            self._mixer_thread.join(timeout=2.0)
        self._mixer_thread = None
        super()._close_streams()
        if self._pawp_pa is not None:
            try:
                self._pawp_pa.terminate()
            except Exception:
                pass
            self._pawp_pa = None

    def start(self) -> None:
        import sounddevice as sd

        pa = _get_pyaudio_wpatch()
        if pa is None:
            raise RuntimeError("PyAudioWPatch requis pour mix")

        self._init_vad()

        with self._lock:
            self._recording = True
            self._audio_chunks = []
            self._mic_chunks = []
            self._lb_chunks = []
            self._last_split_capture = None
        self._speech_ring.clear()

        self._mic_q = queue.Queue(maxsize=64)
        self._lb_q = queue.Queue(maxsize=64)

        mic_block = int(self.sample_rate * 0.1)

        def mic_cb(indata, frames, time_info, status):
            if status:
                logger.warning(f"Mic status: {status}")
            if not self._recording:
                return
            mono = _downmix_input_to_mono(indata)
            mono = _linear_resample_mono(mono, self._mic_native_sr, self.sample_rate)
            try:
                self._mic_q.put_nowait(mono)
            except queue.Full:
                pass

        mic_kwargs: dict[str, Any] = dict(
            samplerate=self._mic_native_sr,
            channels=1,
            dtype="float32",
            blocksize=mic_block,
            callback=mic_cb,
        )
        if self._mic_device is not None:
            mic_kwargs["device"] = self._mic_device

        mic_stream = sd.InputStream(**mic_kwargs)
        try:
            self._lb_native_sr = self._pawp_start_loopback_queue(self._lb_q)
        except Exception:
            try:
                mic_stream.close()
            except Exception:
                pass
            raise

        def mixer_loop():
            while self._recording:
                try:
                    m = self._mic_q.get(timeout=0.25)
                except queue.Empty:
                    continue
                if m is None:
                    break
                try:
                    lb = self._lb_q.get(timeout=0.5)
                except queue.Empty:
                    lb = np.zeros_like(m)
                if lb is None:
                    break
                n = min(len(m), len(lb))
                if n <= 0:
                    continue
                m_cut = m[:n].astype(np.float32, copy=False)
                lb_cut = lb[:n].astype(np.float32, copy=False)
                self._mic_chunks.append(m_cut)
                self._lb_chunks.append(lb_cut)
                mix = self._mix_mic_gain * m_cut + self._mix_loopback_gain * lb_cut
                self._audio_chunks.append(mix.astype(np.float32, copy=False))
                if self._on_input_level is not None:
                    try:
                        self._on_input_level(mix.astype(np.float32, copy=False))
                    except Exception:
                        pass

        self._mixer_thread = threading.Thread(target=mixer_loop, daemon=True)
        self._mixer_thread.start()

        mic_stream.start()
        self._streams.insert(0, mic_stream)
        self._stream = mic_stream
        logger.info(
            "🎙️ Listening (mix mic+system, PyAudioWPatch) mic_gain=%s loopback_gain=%s",
            self._mix_mic_gain,
            self._mix_loopback_gain,
        )

    def record_until_silence(self, on_start: Optional[Callable] = None) -> np.ndarray:
        import sounddevice as sd

        pa = _get_pyaudio_wpatch()
        if pa is None:
            raise RuntimeError("PyAudioWPatch requis pour mix")

        self._init_vad()
        with self._lock:
            self._recording = True
            self._audio_chunks = []
            self._mic_chunks = []
            self._lb_chunks = []
            self._last_split_capture = None
        self._speech_ring.clear()

        self._mic_q = queue.Queue(maxsize=64)
        self._lb_q = queue.Queue(maxsize=64)
        mic_block = int(self.sample_rate * 0.1)

        def mic_cb(indata, frames, time_info, status):
            if status:
                logger.warning(f"Mic status: {status}")
            if not self._recording:
                return
            mono = _downmix_input_to_mono(indata)
            mono = _linear_resample_mono(mono, self._mic_native_sr, self.sample_rate)
            try:
                self._mic_q.put_nowait(mono)
            except queue.Full:
                pass

        mic_kwargs: dict[str, Any] = dict(
            samplerate=self._mic_native_sr,
            channels=1,
            dtype="float32",
            blocksize=mic_block,
            callback=mic_cb,
        )
        if self._mic_device is not None:
            mic_kwargs["device"] = self._mic_device

        mic_stream: Any = None
        try:
            mic_stream = sd.InputStream(**mic_kwargs)
            self._lb_native_sr = self._pawp_start_loopback_queue(self._lb_q)

            def mixer_loop():
                while self._recording:
                    try:
                        m = self._mic_q.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    if m is None:
                        break
                    try:
                        lb = self._lb_q.get(timeout=0.5)
                    except queue.Empty:
                        lb = np.zeros_like(m)
                    if lb is None:
                        break
                    n = min(len(m), len(lb))
                    if n <= 0:
                        continue
                    m_cut = m[:n].astype(np.float32, copy=False)
                    lb_cut = lb[:n].astype(np.float32, copy=False)
                    self._mic_chunks.append(m_cut)
                    self._lb_chunks.append(lb_cut)
                    mix = self._mix_mic_gain * m_cut + self._mix_loopback_gain * lb_cut
                    self._audio_chunks.append(mix.astype(np.float32, copy=False))
                    if self._on_input_level is not None:
                        try:
                            self._on_input_level(mix.astype(np.float32, copy=False))
                        except Exception:
                            pass

            self._mixer_thread = threading.Thread(target=mixer_loop, daemon=True)
            self._mixer_thread.start()
            mic_stream.start()
            self._streams = [mic_stream] + [s for s in self._streams if s is not mic_stream]
            self._stream = mic_stream

            if on_start:
                try:
                    on_start()
                except Exception:
                    pass

            last_speech_time = time.time()
            start_time = time.time()

            try:
                while self._recording:
                    time.sleep(0.1)
                    if time.time() - start_time > self.max_duration:
                        logger.warning("Durée max atteinte")
                        break
                    # Même logique que ``BaseAudioCapture`` : VAD sur le dernier bloc = signal **mixé** (micro + système).
                    if self._audio_chunks and self._vad:
                        recent = self._audio_chunks[-1]
                        if recent is not None and self._is_speech_smoothed(recent):
                            last_speech_time = time.time()
                        elif time.time() - last_speech_time > self.silence_timeout:
                            logger.info("Silence detected (mix) — auto-stop")
                            break
            except KeyboardInterrupt:
                pass

            return self.stop()
        except Exception:
            with self._lock:
                self._recording = False
            try:
                if mic_stream is not None:
                    mic_stream.stop()
                    mic_stream.close()
            except Exception:
                pass
            try:
                self._close_streams()
            except Exception:
                pass
            raise

    def stop(self) -> np.ndarray:
        mixed = super().stop()
        mic = np.concatenate(self._mic_chunks).astype(np.float32, copy=False) if self._mic_chunks else np.array([], dtype=np.float32)
        system = np.concatenate(self._lb_chunks).astype(np.float32, copy=False) if self._lb_chunks else np.array([], dtype=np.float32)
        self._last_split_capture = {
            "mic": mic,
            "system": system,
            "mixed": mixed,
            "sample_rate": self.sample_rate,
        }
        return mixed

    def get_last_split_capture(self) -> Optional[dict[str, Any]]:
        """Return last mix capture tracks (mic/system/mixed) after stop()."""
        return self._last_split_capture


def build_audio_recorder(
    *,
    sample_rate: int = 16000,
    vad_sensitivity: Any = "normal",
    silence_timeout: float = 2.0,
    max_duration: float = 120.0,
    capture_mode: str = "mic_only",
    mic_device: Optional[int] = None,
    loopback_device: Optional[int] = None,
    mix_mic_gain: float = 1.0,
    mix_loopback_gain: float = 0.8,
    on_input_level: Optional[Callable[[np.ndarray], None]] = None,
    on_input_stop: Optional[Callable[[], None]] = None,
) -> BaseAudioCapture:
    """
    Fabrique l'enregistreur selon ``capture_mode``:
    - ``mic_only`` : micro (défaut)
    - ``system_only`` / ``mix`` : loopback Windows via **PyAudioWPatch** ; sinon repli sur ``mic_only``.
    """
    mode = (capture_mode or "mic_only").strip().lower()
    if mode not in ("mic_only", "system_only", "mix"):
        logger.warning("Unknown audio.capture_mode %r — using mic_only", capture_mode)
        mode = "mic_only"

    if mode in ("system_only", "mix") and not loopback_capture_available():
        logger.warning(
            "capture_mode=%s nécessite PyAudioWPatch sur Windows (pip install PyAudioWPatch) — "
            "repli sur mic_only",
            mode,
        )
        mode = "mic_only"

    vad_aggressiveness, speech_ratio_threshold = _resolve_vad_sensitivity(vad_sensitivity)

    if mode == "mic_only":
        return AudioRecorder(
            sample_rate=sample_rate,
            vad_aggressiveness=vad_aggressiveness,
            speech_ratio_threshold=speech_ratio_threshold,
            silence_timeout=silence_timeout,
            max_duration=max_duration,
            on_input_level=on_input_level,
            on_input_stop=on_input_stop,
            device=mic_device,
        )

    if mode == "system_only":
        return SystemLoopbackRecorder(
            sample_rate=sample_rate,
            vad_aggressiveness=vad_aggressiveness,
            speech_ratio_threshold=speech_ratio_threshold,
            silence_timeout=silence_timeout,
            max_duration=max_duration,
            on_input_level=on_input_level,
            on_input_stop=on_input_stop,
            loopback_output_device=loopback_device,
        )

    return MixedDualInputRecorder(
        sample_rate=sample_rate,
        vad_aggressiveness=vad_aggressiveness,
        speech_ratio_threshold=speech_ratio_threshold,
        silence_timeout=silence_timeout,
        max_duration=max_duration,
        on_input_level=on_input_level,
        on_input_stop=on_input_stop,
        mic_device=mic_device,
        loopback_output_device=loopback_device,
        mix_mic_gain=mix_mic_gain,
        mix_loopback_gain=mix_loopback_gain,
    )
