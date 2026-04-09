"""
Capture audio depuis le microphone avec Voice Activity Detection (VAD).

Utilise sounddevice pour la capture et webrtcvad pour détecter
quand l'utilisateur parle/arrête de parler.
"""

import logging
import threading
import time
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger("perkysue.audio")


class AudioRecorder:
    """Enregistre l'audio du micro avec détection de silence."""

    def __init__(self, sample_rate: int = 16000, vad_aggressiveness: int = 2,
                 silence_timeout: float = 2.0, max_duration: float = 120.0,
                 on_input_level: Optional[Callable[[np.ndarray], None]] = None,
                 on_input_stop: Optional[Callable[[], None]] = None):
        """
        Args:
            sample_rate: Taux d'échantillonnage (16000 pour Whisper)
            vad_aggressiveness: Sensibilité VAD 1-3 (3 = strict)
            silence_timeout: Secondes de silence avant arrêt auto
            max_duration: Durée max d'listening (sécurité)
            on_input_level: Callback (mono float32) par bloc micro — ex. mètre GUI
            on_input_stop: Appelé à l'arrêt capture — ex. reset du mètre
        """
        self.sample_rate = sample_rate
        self.vad_aggressiveness = vad_aggressiveness
        self.silence_timeout = silence_timeout
        self.max_duration = max_duration
        self._on_input_level = on_input_level
        self._on_input_stop = on_input_stop

        self._recording = False
        self._audio_chunks: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()
        self._vad = None

    def _init_vad(self):
        """Initialise le VAD WebRTC."""
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
        """Détecte si un chunk audio contient de la parole."""
        if self._vad is None:
            return True  # Sans VAD, on considère tout comme parole

        # WebRTC VAD attend du int16, frames de 10/20/30ms
        audio_int16 = (audio_chunk * 32767).astype(np.int16)
        frame_duration_ms = 30
        frame_size = int(self.sample_rate * frame_duration_ms / 1000)

        speech_frames = 0
        total_frames = 0

        for i in range(0, len(audio_int16) - frame_size, frame_size):
            frame = audio_int16[i:i + frame_size].tobytes()
            try:
                if self._vad.is_speech(frame, self.sample_rate):
                    speech_frames += 1
                total_frames += 1
            except Exception:
                total_frames += 1

        if total_frames == 0:
            return False

        return (speech_frames / total_frames) > 0.3

    def start(self) -> None:
        """Démarre l'listening."""
        import sounddevice as sd

        self._init_vad()

        with self._lock:
            self._recording = True
            self._audio_chunks = []

        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Audio status: {status}")
            if self._recording:
                mono = indata[:, 0].copy()
                self._audio_chunks.append(mono)
                if self._on_input_level is not None:
                    try:
                        self._on_input_level(mono)
                    except Exception:
                        pass

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=int(self.sample_rate * 0.1),  # Blocs de 100ms
            callback=audio_callback,
        )
        self._stream.start()
        logger.info("🎙️ Listening...")

    def request_stop(self) -> None:
        """Demande l'arrêt de l'enregistrement (stop manuel, ex. clic avatar). La boucle record_until_silence sort au prochain tour."""
        with self._lock:
            self._recording = False

    def stop(self) -> np.ndarray:
        """
        Arrête l'listening et retourne l'audio capturé.

        Returns:
            Array numpy float32 mono, sample_rate=16000
        """
        with self._lock:
            self._recording = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

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
        """
        Enregistre jusqu'à ce que le silence soit détecté.
        Utile en mode "toggle" — on appuie une fois, on parle, ça s'arrête tout seul.

        Args:
            on_start: Callback appelé quand l'listening commence

        Returns:
            Array numpy float32 de l'audio capturé
        """
        self.start()
        if on_start:
            on_start()

        last_speech_time = time.time()
        start_time = time.time()

        try:
            while self._recording:
                time.sleep(0.1)

                # Vérifier timeout max
                if time.time() - start_time > self.max_duration:
                    logger.warning("Durée max atteinte")
                    break

                # Vérifier le silence
                if self._audio_chunks and self._vad:
                    recent = self._audio_chunks[-1] if self._audio_chunks else None
                    if recent is not None and self._is_speech(recent):
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
        """Liste les périphériques audio disponibles."""
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
            result.append({
                "id": i,
                "name": d["name"],
                "inputs": d["max_input_channels"],
                "is_default": (i == default_in),
            })
        return result
