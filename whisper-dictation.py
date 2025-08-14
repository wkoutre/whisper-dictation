import argparse
import time
import threading
import platform
import rumps
from pynput import keyboard

# Use the refactored core package
from whisper_dictation_core.core import SpeechTranscriber, Recorder, SoundPlayer, load_whisper_model


class GlobalKeyListener:
    def __init__(self, app, key_combination):
        self.app = app
        self.key1, self.key2 = self.parse_key_combination(key_combination)
        self.key1_pressed = False
        self.key2_pressed = False

    def parse_key_combination(self, key_combination):
        key1_name, key2_name = key_combination.split('+')
        key1 = getattr(keyboard.Key, key1_name, keyboard.KeyCode(char=key1_name))
        key2 = getattr(keyboard.Key, key2_name, keyboard.KeyCode(char=key2_name))
        return key1, key2

    def on_key_press(self, key):
        if key == self.key1:
            self.key1_pressed = True
        elif key == self.key2:
            self.key2_pressed = True

        if self.key1_pressed and self.key2_pressed:
            self.app.toggle()

    def on_key_release(self, key):
        if key == self.key1:
            self.key1_pressed = False
        elif key == self.key2:
            self.key2_pressed = False


class DoubleCommandKeyListener:
    def __init__(self, app):
        self.app = app
        self.key = keyboard.Key.cmd_r
        self.pressed = 0
        self.last_press_time = 0

    def on_key_press(self, key):
        is_listening = self.app.started
        if key == self.key:
            current_time = time.time()
            if not is_listening and current_time - self.last_press_time < 0.5:  # Double click to start listening
                self.app.toggle()
            elif is_listening:  # Single click to stop listening
                self.app.toggle()
            self.last_press_time = current_time

    def on_key_release(self, key):
        pass


class StatusBarApp(rumps.App):
    def __init__(self, recorder, languages=None, max_time=None, sound_player: SoundPlayer | None = None):
        super().__init__("whisper", "⏯")
        self.languages = languages
        self.current_language = languages[0] if languages is not None else None
        self.sound_player = sound_player

        menu = [
            'Start Recording',
            'Stop Recording',
            None,
        ]

        if languages is not None:
            for lang in languages:
                callback = self.change_language if lang != self.current_language else None
                menu.append(rumps.MenuItem(lang, callback=callback))
            menu.append(None)

        self.menu = menu
        self.menu['Stop Recording'].set_callback(None)

        self.started = False
        self.recorder = recorder
        self.max_time = max_time
        self.timer = None
        self.elapsed_time = 0

    def change_language(self, sender):
        self.current_language = sender.title
        for lang in self.languages:
            self.menu[lang].set_callback(self.change_language if lang != self.current_language else None)

    @rumps.clicked('Start Recording')
    def start_app(self, _):
        if self.sound_player:
            self.sound_player.play_start()
        print('Listening...')
        self.started = True
        self.menu['Start Recording'].set_callback(None)
        self.menu['Stop Recording'].set_callback(self.stop_app)
        self.recorder.start(self.current_language)

        if self.max_time is not None:
            self.timer = threading.Timer(self.max_time, lambda: self.stop_app(None))
            self.timer.start()

        self.start_time = time.time()
        self.update_title()

    @rumps.clicked('Stop Recording')
    def stop_app(self, _):
        if not self.started:
            return

        if self.timer is not None:
            self.timer.cancel()

        if self.sound_player:
            self.sound_player.play_stop()
        print('Transcribing...')
        self.title = "⏯"
        self.started = False
        self.menu['Stop Recording'].set_callback(None)
        self.menu['Start Recording'].set_callback(self.start_app)
        self.recorder.stop()
        print('Done.\n')

    def update_title(self):
        if self.started:
            self.elapsed_time = int(time.time() - self.start_time)
            minutes, seconds = divmod(self.elapsed_time, 60)
            self.title = f"({minutes:02d}:{seconds:02d}) 🔴"
            threading.Timer(1, self.update_title).start()

    def toggle(self):
        if self.started:
            self.stop_app(None)
        else:
            self.start_app(None)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Dictation app using the OpenAI whisper ASR model. By default the keyboard shortcut cmd+option '
        'starts and stops dictation')
    parser.add_argument('-m', '--model_name', type=str,
                        choices=['tiny', 'tiny.en', 'base', 'base.en', 'small', 'small.en', 'medium', 'medium.en', 'large', 'large-v3'],
                        default='small.en',
                        help='Specify the Whisper model to use. Options include tiny, base, small, medium, large, and large-v3. '
                        'Models ending in .en are English-only and may perform better on English. Larger models are more accurate but '
                        'require more resources. Default: small.en.')
    parser.add_argument('-k', '--key_combination', type=str, default='cmd_l+alt' if platform.system() == 'Darwin' else 'ctrl+alt',
                        help='Specify the key combination to toggle the app. Example: cmd_l+alt for macOS '
                        'ctrl+alt for other platforms. Default: cmd_r+alt (macOS) or ctrl+alt (others).')
    parser.add_argument('--k_double_cmd', action='store_true',
                            default=(platform.system() == 'Darwin'),
                            help='If set, use double Right Command key press on macOS to toggle the app (double click to begin recording, single click to stop recording). '
                                 'Ignores the --key_combination argument. Default: enabled on macOS.')
    parser.add_argument('-l', '--language', type=str, default='en',
                        help='Specify the two-letter language code (e.g., "en" for English). Default: en. '
                        'To see the full list of supported languages, check the official list '
                        '[here](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py).')
    parser.add_argument('-t', '--max_time', type=float, default=30,
                        help='Specify the maximum recording time in seconds. The app will automatically stop recording after this duration. '
                        'Default: 30 seconds.')
    parser.add_argument('--start_sound', type=str, default='Ping',
                        help='Sound name to play when listening starts (looked up in custom dir, then system). Default: Ping')
    parser.add_argument('--stop_sound', type=str, default='Bottle',
                        help='Sound name to play when listening stops. Default: Bottle')
    parser.add_argument('--transcribed_sound', type=str, default='Blow',
                        help='Sound name to play when transcription finishes. Default: Blow')
    parser.add_argument('--start_sound_file', type=str, default='/Users/nick.koutrelakos/Music/Sounds/Bottle-reversed.aiff',
                        help='Explicit audio file to play for start (overrides name).')
    parser.add_argument('--stop_sound_file', type=str, default=None,
                        help='Explicit audio file to play for stop (overrides name).')
    parser.add_argument('--transcribed_sound_file', type=str, default=None,
                        help='Explicit audio file to play for transcription finished (overrides name).')
    parser.add_argument('--sounds_dir', type=str, default='~/Music/Sounds',
                        help='Directory to search for custom sound files by name before system sounds. Default: ~/Music/Sounds')

    args = parser.parse_args()

    if args.language is not None:
        args.language = args.language.split(',')

    if args.model_name.endswith('.en') and args.language is not None and any(lang != 'en' for lang in args.language):
        raise ValueError('If using a model ending in .en, you cannot specify a language other than English.')

    return args


if __name__ == "__main__":
    args = parse_args()

    print("Loading model...")
    model = load_whisper_model(args.model_name)

    transcriber = SpeechTranscriber(model)

    sound_player = SoundPlayer(
        args.start_sound, args.stop_sound, args.transcribed_sound,
        start_file=args.start_sound_file, stop_file=args.stop_sound_file, transcribed_file=args.transcribed_sound_file,
        sounds_dir=args.sounds_dir
    ) if platform.system() == 'Darwin' else None

    # Type text into the active application when transcription finishes
    kb = keyboard.Controller()
    def type_text(s: str):
        is_first = True
        for ch in s:
            if is_first and ch == ' ':
                is_first = False
                continue
            try:
                kb.type(ch)
                time.sleep(0.0025)
            except Exception:
                pass

    # Recorder gets callbacks for text and completion (to play sound)
    recorder = Recorder(
        transcriber,
        on_done=(sound_player.play_transcribed if sound_player else None),
        on_text=type_text,
    )

    app = StatusBarApp(recorder, args.language, args.max_time, sound_player)
    if args.k_double_cmd:
        key_listener = DoubleCommandKeyListener(app)
    else:
        key_listener = GlobalKeyListener(app, args.key_combination)
    listener = keyboard.Listener(on_press=key_listener.on_key_press, on_release=key_listener.on_key_release)
    listener.start()

    print("Running... ")
    app.run()

