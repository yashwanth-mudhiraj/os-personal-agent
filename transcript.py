import sounddevice as sd
import numpy as np
import time
from queue import Queue
import webrtcvad
import re
import pygetwindow as gw
import string
import app_control as ac


from faster_whisper import WhisperModel

# =====================
# AUDIO CONFIG
# =====================
SAMPLE_RATE = 16000
BLOCK_MS = 10
FINAL_CHUNK_SECONDS = 1.0
SILENCE_TIMEOUT = 0.4

LISTENING_MODE = False
LAST_ACTIVITY_TIME = 0
SESSION_TIMEOUT = 10  # seconds

audio_q = Queue(maxsize=50)

# VAD: 0 least aggressive, 3 most aggressive
vad = webrtcvad.Vad(2)

# =====================
# WHISPER CONFIG
# =====================
WHISPER_MODEL_SIZE = "distil-large-v3"
DEVICE = "cuda"
COMPUTE_TYPE = "float16"

whisper_model = WhisperModel(
    WHISPER_MODEL_SIZE,
    device=DEVICE,
    compute_type=COMPUTE_TYPE
)

# Warm-up (prevents first-run lag)
whisper_model.transcribe(
    np.zeros(SAMPLE_RATE, dtype=np.float32),
    language="en",
    beam_size=1,
    without_timestamps=True
)

# =====================
# APP CONTROL CONFIG
# =====================
WAKE_WORD = "alice"

WAKE_REGEX = re.compile(
    rf"^\s*{WAKE_WORD}\b[\s,:-]*",
    re.IGNORECASE
)

OPEN_VERBS = (
        "open",
        "launch",
    )

FOCUS_VERBS = (
    "focus",
    "switch to",
)

CLOSE_VERBS = (
    "close",
    "exit",
)

catalog = ac.load_or_refresh_catalog()


def extract_command(text: str) -> str | None:
    """
    Returns command text if wake word is present, else None
    """
    if not WAKE_REGEX.match(text):
        return None
    return WAKE_REGEX.sub("", text).strip()

# =====================
# TEXT CLEANUP
# =====================
def remove_leading_the(text: str) -> str:
    # Remove "the" only at the start of a sentence
    return re.sub(r'(?i)(^|[.!?]\s+)\s*the\s+', r'\1', text).strip()

def parse_intent(command_text: str):
    """
    Detects command intent and target.
    Returns (intent, target) where:
      intent ∈ {"open", "focus", None}
      target is the remaining text or None
    """
    if not command_text:
        return None, None

    text = command_text.lower().strip()

    for verb in FOCUS_VERBS:
        if text.startswith(verb):
            return "focus", text[len(verb):].strip()

    for verb in OPEN_VERBS:
        if text.startswith(verb):
            return "open", text[len(verb):].strip()
        
    for verb in CLOSE_VERBS:
        if text.startswith(verb):
            return "close", text[len(verb):].strip()
        
    if text.startswith("maximize"):
        return "maximize", text[len("maximize"):].strip()
    
    if text.startswith("minimize"):
        return "minimize", text[len("minimize"):].strip()

    return None, None

def clean_target(text: str) -> str:
    """
    Cleans Whisper-produced app names:
    - removes trailing punctuation (firefox.)
    - removes surrounding quotes
    - normalizes whitespace
    """
    if not text:
        return ""

    text = text.strip()

    # Remove surrounding quotes
    text = text.strip("\"'")

    # Remove leading/trailing punctuation (. , ! ?)
    text = text.strip(string.punctuation)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)

    return text


# =====================
# AUDIO CALLBACK
# =====================
def callback(indata, frames, time_info, status):
    try:
        audio_q.put_nowait(bytes(indata))
    except:
        pass

stream = sd.RawInputStream(
    samplerate=SAMPLE_RATE,
    blocksize=int(SAMPLE_RATE * BLOCK_MS / 1000),
    dtype="int16",
    channels=1,
    callback=callback,
)

print("🎙️ Live dictation (Whisper-only). Ctrl+C to stop\n")

buffer = bytearray()
last_speech_time = time.time()

with stream:
    while True:
        frame = audio_q.get()

        # VAD: collect only speech frames
        if vad.is_speech(frame, SAMPLE_RATE):
            buffer.extend(frame)
            last_speech_time = time.time()

        silence_time = time.time() - last_speech_time

        # Trigger Whisper on silence + enough audio
        if (
            silence_time > SILENCE_TIMEOUT
            and len(buffer) > int(SAMPLE_RATE * FINAL_CHUNK_SECONDS * 2)
        ):
            audio = np.frombuffer(buffer, np.int16).astype(np.float32) / 32768.0
            buffer.clear()

            segments, _ = whisper_model.transcribe(
                audio,
                beam_size=1,
                best_of=1,
                temperature=0.0,
                language="en",
                without_timestamps=True,
                condition_on_previous_text=False,
            )

            final_text = " ".join(s.text.strip() for s in segments if s.text.strip())
            final_text = remove_leading_the(final_text)

            current_time = time.time()

            # Auto-exit session after inactivity
            if LISTENING_MODE and (current_time - LAST_ACTIVITY_TIME > SESSION_TIMEOUT):
                LISTENING_MODE = False
                print("🔕 Session ended due to inactivity.\n")

            command_text = extract_command(final_text)

            # Wake word detected → Start session
            if command_text is not None:
                LISTENING_MODE = True
                LAST_ACTIVITY_TIME = current_time
                print("🎧 Session started.\n")
                continue  # Wait for next command

            # If already in session mode → treat everything as command
            if LISTENING_MODE:
                action, target = parse_intent(final_text)
                target = clean_target(target or "")

                if action and target:
                    try:
                        ok = ac.handle_app_action(action, target, catalog)
                        if not ok and (action == "focus" or action == "close" or action == "maximize" or action == "minimize"):
                            print(f"⚠️ '{target}' because it isn't open.")
                    except Exception as e:
                        print(f"❌ Command failed: {e}")
                else:
                    print(f"⚠️ Unknown command inside session: {final_text}")

                LAST_ACTIVITY_TIME = current_time
            else:
                print(f"✅ FINAL (whisper): {final_text}")


            # command_text = extract_command(final_text) 

            # if command_text:
            #     action, target = parse_intent(command_text)   # "open" / "focus"
            #     target = clean_target(target or "")           # removes trailing punctuation etc.

            #     if action and target:
            #         try:
            #             ok = ac.handle_app_action(action, target, catalog)
            #             if not ok and action == "focus":
            #                 print(f"⚠️ Can't focus '{target}' because it isn't open.")
            #         except Exception as e:
            #             print(f"❌ Command failed: {e}")
            #     else:
            #         print(f"⚠️ Wake word detected but unknown/empty command: {command_text}")

            # else:
            #     print(f"✅ FINAL (whisper): {final_text}")

