import os
import time
import threading
import numpy as np
import pyaudio
from faster_whisper import WhisperModel
from AppKit import NSSound
import subprocess


def load_whisper_model(model_name: str):
    try:
        model = WhisperModel(model_name, device="auto", compute_type="float16")
        print(f"{model_name} model loaded with faster-whisper (device=auto, compute_type=float16)")
        return model
    except Exception as e:
        print("Hardware-accelerated backend initialization failed (" + str(e) + "). Falling back to CPU.")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print(f"{model_name} model loaded with faster-whisper (device=cpu, compute_type=int8)")
        return model


class SpeechTranscriber:
    def __init__(self, model):
        self.model = model

    def transcribe(self, audio_data, language=None) -> str:
        segments, info = self.model.transcribe(
            audio_data,
            language=language,
            vad_filter=True,
        )
        text = "".join(segment.text for segment in segments)
        return text


class Recorder:
    def __init__(self, transcriber, on_done=None, on_text=None):
        self.recording = False
        self.transcriber = transcriber
        self.on_done = on_done
        self.on_text = on_text

    def start(self, language=None):
        thread = threading.Thread(target=self._record_impl, args=(language,))
        thread.start()

    def stop(self):
        self.recording = False

    def _record_impl(self, language):
        self.recording = True
        frames_per_buffer = 2048
        sample_rate = 16000
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            frames_per_buffer=frames_per_buffer,
            input=True,
        )
        frames = []

        while self.recording:
            try:
                data = stream.read(frames_per_buffer, exception_on_overflow=False)
            except OSError:
                time.sleep(0.01)
                continue
            frames.append(data)

        try:
            stream.stop_stream()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass
        try:
            p.terminate()
        except Exception:
            pass

        audio_data = np.frombuffer(b"".join(frames), dtype=np.int16)
        if audio_data.size == 0:
            return
        audio_data_fp32 = audio_data.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(audio_data_fp32)))) if audio_data_fp32.size else 0.0
        if rms < 0.002:
            return

        emitted = self.transcriber.transcribe(audio_data_fp32, language)
        if emitted and emitted.strip():
            if callable(self.on_text):
                try:
                    self.on_text(emitted)
                except Exception:
                    pass
            if callable(self.on_done):
                try:
                    self.on_done()
                except Exception:
                    pass


class SoundPlayer:
    def __init__(
        self,
        start_name: str = "Ping",
        stop_name: str = "Bottle",
        transcribed_name: str = "Blow",
        start_file: str | None = None,
        stop_file: str | None = None,
        transcribed_file: str | None = None,
        sounds_dir: str | None = None,
    ):
        self.start_name = start_name
        self.stop_name = stop_name
        self.transcribed_name = transcribed_name
        self.start_file = os.path.expanduser(start_file) if start_file else None
        self.stop_file = os.path.expanduser(stop_file) if stop_file else None
        self.transcribed_file = os.path.expanduser(transcribed_file) if transcribed_file else None
        self.sounds_dir = os.path.expanduser(sounds_dir) if sounds_dir else None

    def _system_sound_path(self, name: str) -> str | None:
        if not name:
            return None
        candidates = [
            f"/System/Library/Sounds/{name}.aiff",
            f"/System/Library/Sounds/{name}.caf",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def _user_sound_path(self, name: str) -> str | None:
        if not name or not self.sounds_dir:
            return None
        exts = [".aiff", ".caf", ".wav", ".mp3", ".m4a"]
        for ext in exts:
            p = os.path.join(self.sounds_dir, name + ext)
            if os.path.exists(p):
                return p
        return None

    def _play_named_or_file(self, name: str | None, file_path: str | None):
        if file_path and os.path.exists(file_path):
            try:
                subprocess.Popen(["afplay", file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass
        upath = self._user_sound_path(name) if name else None
        if upath:
            try:
                subprocess.Popen(["afplay", upath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass
        spath = self._system_sound_path(name) if name else None
        if spath:
            try:
                subprocess.Popen(["afplay", spath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass
        if name:
            try:
                snd = NSSound.soundNamed_(name)
                if snd:
                    snd.stop()
                    snd.play()
            except Exception:
                pass

    def play_start(self):
        self._play_named_or_file(self.start_name, self.start_file)

    def play_stop(self):
        self._play_named_or_file(self.stop_name, self.stop_file)

    def play_transcribed(self):
        self._play_named_or_file(self.transcribed_name, self.transcribed_file)

