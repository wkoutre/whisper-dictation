import sys
import json
import threading
import time
from typing import Optional

from .core import load_whisper_model, SpeechTranscriber, Recorder


class ServerState:
    def __init__(self):
        self.model = None
        self.transcriber: Optional[SpeechTranscriber] = None
        self.recorder: Optional[Recorder] = None
        self.language: Optional[str] = None
        self.running = False
        self._lock = threading.Lock()

    def to_status(self):
        return {
            "running": self.running,
            "language": self.language,
            "model_loaded": self.model is not None,
        }


state = ServerState()

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def handle_load(args):
    model_name = args.get("model_name", "small.en")
    send({"event": "loading", "model_name": model_name})
    try:
        with state._lock:
            state.model = load_whisper_model(model_name)
            state.transcriber = SpeechTranscriber(state.model)
        send({"event": "loaded", "model_name": model_name})
    except Exception as e:
        # Ensure failure is visible to the client
        with state._lock:
            state.model = None
            state.transcriber = None
        send({"event": "error", "error": f"load_failed: {str(e)}"})


def _on_done_event():
    # Notify that transcription finished (sound is handled in CLI app, not here)
    send({"event": "transcribed"})


def handle_start(args):
    language = args.get("language")
    with state._lock:
        if not state.transcriber:
            raise RuntimeError("Model not loaded")
        if state.running:
            return
        def on_done_wrapper():
            _on_done_event()
        def on_text_wrapper(text: str):
            send({"event": "transcript", "text": text, "language": language})
        state.recorder = Recorder(state.transcriber, on_done=on_done_wrapper, on_text=on_text_wrapper)
        state.language = language
        state.running = True
        state.recorder.start(language)
    send({"event": "started", "language": language})


def handle_stop(_args):
    with state._lock:
        if not state.running or not state.recorder:
            return
        rec = state.recorder
        state.running = False
        # Stopping here triggers transcription in the recorder thread
        rec.stop()

    # Busy-wait a short time until the recorder thread has transcribed.
    # In a more advanced design, we'd pipe partials; for now, we just wait
    # briefly and ask the client to listen for a follow-up "transcript" event.
    # We can't get the text out of Recorder directly, so we instead have the
    # client call "flush" which re-runs VAD+transcribe on the buffered audio.
    send({"event": "stopped"})


def handle_flush(args):
    # Optional: accept raw PCM base64 to transcribe, but for simplicity here
    # we do nothing. A future iteration can store frames inside Recorder and
    # expose them. For now, this is a no-op placeholder.
    send({"event": "noop"})


def handle_status(_args):
    send({"event": "status", "data": state.to_status()})


def main():
    send({"event": "ready"})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            cmd = msg.get("cmd")
            args = msg.get("args", {})
            if cmd == "load":
                handle_load(args)
            elif cmd == "start":
                handle_start(args)
            elif cmd == "stop":
                handle_stop(args)
            elif cmd == "flush":
                handle_flush(args)
            elif cmd == "status":
                handle_status(args)
            elif cmd == "quit":
                send({"event": "bye"})
                break
            else:
                send({"event": "error", "error": f"unknown cmd: {cmd}"})
        except Exception as e:
            send({"event": "error", "error": str(e)})


if __name__ == "__main__":
    main()
