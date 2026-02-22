import sounddevice as sd
import numpy as np
import time
from queue import Queue
import webrtcvad
import app_control as ac
import helpers as hp
from agent import SimpleAgent
from voice_agent import speak

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
# WHISPER_MODEL_SIZE = "distil-large-v3"
# DEVICE = "cuda"
# COMPUTE_TYPE = "float16"
WHISPER_MODEL_SIZE = "small"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"


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
            final_text = hp.remove_leading_the(final_text)
            if final_text:
                current_time = time.time()

                # Auto-exit session after inactivity
                if LISTENING_MODE and (current_time - LAST_ACTIVITY_TIME > SESSION_TIMEOUT):
                    LISTENING_MODE = False
                    print("🔕 Session ended due to inactivity.\n")

                command_text = hp.extract_command(final_text)

                # Wake word detected → Start session
                if command_text is not None:
                    LISTENING_MODE = True
                    LAST_ACTIVITY_TIME = current_time
                    print("🎧 Session started.\n")
                    continue  # Wait for next command

                if LISTENING_MODE:          # Commander Mode
                    print(f"🗣 You: {final_text}")
                    
                    # 1. THE FAST PATH: Instant Regex/String matching for obvious commands
                    lower_text = final_text.lower()
                    command_keywords = ["open ", "close ", "focus ", "maximize", "minimize"]
                    
                    # Check if the text starts with any of our known actions
                    if any(lower_text.startswith(kw) for kw in command_keywords):
                        # Use your existing fast regex parser for standard commands
                        action, target = hp.parse_intent(final_text) 
                        target = hp.clean_target(target or "")
                        
                        print(f"⚡ FAST PATH Triggered: {action} -> {target}")
                        
                        if action and target:
                            try:
                                ok = ac.handle_app_action(action, target, hp.catalog)
                                if not ok:
                                    print(f"⚠️ I couldn't find {target}.")
                            except Exception as e:
                                print(f"❌ Command failed: {e}")
                                
                    # 2. THE SLOW PATH: Send to LLM for Chat and complex routing
                    else:               # Commander Fallback to LLM for complex commands or chat
                        print("🧠 Sending to LLM for analysis...")
                        hp.agent_call(final_text)  # This will handle both commands and chat responses via the agent
                    LAST_ACTIVITY_TIME = current_time

                else:  # Agent Chat Mode
                    print(f"🗣 You: {final_text}")

                    hp.agent_call(final_text)  # This will handle both commands and chat responses via the agent
                    



