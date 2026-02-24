import sounddevice as sd
import numpy as np
import time
from queue import Queue
import webrtcvad
import app_control
import helpers as hp
from voice_agent import speak
import file_control
import os, re

from faster_whisper import WhisperModel
from session_state import session    


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

file_control.ensure_index([
    "C:/Users/Yash",
    "D:/",
    "E:/"
])

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

                lower_text = final_text.lower()

                # =====================================================
                # SELECTION MEMORY (Flexible + Natural)
                # =====================================================

                if session.has_pending():

                    # -----------------------------
                    # CANCEL SELECTION (Flexible)
                    # -----------------------------
                    if any(phrase in lower_text for phrase in [
                        "cancel",
                        "never mind",
                        "forget it",
                        "leave it",
                        "stop that",
                        "don't open",
                        "do not open"
                    ]):
                        session.clear()
                        print("❌ Selection cancelled.")
                        continue


                    # -----------------------------
                    # SHOW OPTIONS AGAIN (Flexible)
                    # -----------------------------
                    if (
                        ("show" in lower_text and any(word in lower_text for word in ["option", "choices", "list"]))
                        or "repeat" in lower_text
                        or "what were" in lower_text
                        or "show again" in lower_text
                        or "say again" in lower_text
                    ):
                        session.show_options()
                        continue


                    # -----------------------------
                    # OPEN / SELECT / CHOOSE (Flexible)
                    # -----------------------------
                    if any(word in lower_text for word in ["open", "select", "choose", "pick"]):

                        # Look for any number in the sentence
                        normalized_text = hp.normalize_spoken_numbers(lower_text)
                        match = re.search(r"\d+", normalized_text)

                        if match:
                            number = int(match.group())
                            index = number - 1

                            if 0 <= index < len(session.pending_matches):
                                entry = session.pending_matches[index]
                                file_control.open_entry(entry)
                                print(f"🟢 Opened {entry.name}")
                                session.clear()
                            else:
                                print("❌ Invalid selection number.")

                            continue


                        # Optional: support "first", "second", etc.
                        ordinal_map = {
                            "first": 0,
                            "second": 1,
                            "third": 2,
                            "fourth": 3,
                            "fifth": 4,
                        }

                        for word, idx in ordinal_map.items():
                            if word in lower_text:
                                if idx < len(session.pending_matches):
                                    entry = session.pending_matches[idx]
                                    file_control.open_entry(entry)
                                    print(f"🟢 Opened {entry.name}")
                                    session.clear()
                                else:
                                    print("❌ That option doesn't exist.")
                                break

                        else:
                            # No valid selection found
                            pass

                # =====================================================
                # 2️⃣ WAKE WORD / LISTENING MODE
                # =====================================================

                if LISTENING_MODE:          # Commander Mode
                    print(f"🗣 You: {final_text}")
                    
                    # 1. THE FAST PATH: Instant Regex/String matching for obvious commands
                    lower_text = final_text.lower()
                    command_keywords = ["open ", "close ", "focus ", "maximize", "minimize"]

                    # -----------------------------------------
                    # FILE CONTROL FAST PATH
                    # -----------------------------------------

                    # Open folder
                    if "open the folder" in lower_text or "open folder" in lower_text:
                        target = (
                            lower_text
                            .replace("open the folder", "")
                            .replace("open folder", "")
                            .strip()
                        )

                        result = file_control.handle_file_action("open", "folder", target)

                        if isinstance(result, list):  # multiple matches
                            session.set_pending(result, "folder")

                            print("📂 Multiple folders found:")
                            for i, m in enumerate(result):
                                print(f"{i+1}. {m.name}")

                            print("Say: open number X")


                    # Open file
                    elif "open the file" in lower_text or "open file" in lower_text:
                        target = (
                            lower_text
                            .replace("open the file", "")
                            .replace("open file", "")
                            .strip()
                        )

                        result = file_control.handle_file_action("open", "file", target)

                        if isinstance(result, list):  # multiple matches
                            session.set_pending(result, "file")

                            print("📄 Multiple files found:")
                            for i, m in enumerate(result):
                                print(f"{i+1}. {m.name}")

                            print("Say: open number X")


                    # List folder contents
                    elif "list the folder" in lower_text or "what files are in the folder" in lower_text:

                        target = (
                            lower_text
                            .replace("list the folder", "")
                            .replace("what files are in the folder", "")
                            .strip()
                        )

                        result = file_control.handle_file_action("list_folder", "folder", target)

                        if result is False:
                            speak("I couldn't find that folder.")

                    # -----------------------------------------
                    # APP CONTROL FAST PATH
                    # -----------------------------------------
                    elif any(lower_text.startswith(kw) for kw in command_keywords):

                        action, target = hp.parse_intent(final_text)
                        target = hp.clean_target(target or "")

                        print(f"⚡ FAST PATH: {action} -> {target}")

                        if action and target:
                            try:
                                ok = app_control.handle_app_action(action, target, hp.catalog)
                                if not ok:
                                    print(f"⚠️ I couldn't find {target}.")
                            except Exception as e:
                                print(f"❌ Command failed: {e}")

                    # -----------------------------------------
                    # FALLBACK TO LLM
                    # -----------------------------------------
                    else:
                        print("🧠 Sending to LLM for analysis...")
                        hp.agent_call(final_text)
                    LAST_ACTIVITY_TIME = current_time

                #     # Check if the text starts with any of our known actions
                #     if any(lower_text.startswith(kw) for kw in command_keywords):
                #         # Use your existing fast regex parser for standard commands
                #         action, target = hp.parse_intent(final_text) 
                #         target = hp.clean_target(target or "")
                        
                #         print(f"⚡ FAST PATH Triggered: {action} -> {target}")
                        
                #         if action and target:
                #             try:
                #                 ok = app_control.handle_app_action(action, target, hp.catalog)
                #                 if not ok:
                #                     print(f"⚠️ I couldn't find {target}.")
                #             except Exception as e:
                #                 print(f"❌ Command failed: {e}")
                                
                #     # 2. THE SLOW PATH: Send to LLM for Chat and complex routing
                #     else:               # Commander Fallback to LLM for complex commands or chat
                #         print("🧠 Sending to LLM for analysis...")
                #         hp.agent_call(final_text)  # This will handle both commands and chat responses via the agent
                #     LAST_ACTIVITY_TIME = current_time

                # =====================================================
                # 3️⃣ NON-LISTENING MODE (No Wake Word Detected) → Whisper-only Dictation or Pending Selection Handling
                # =====================================================
                else:  # Agent Chat Mode
                    print(f"🗣 You: {final_text}")

                    hp.agent_call(final_text)  # This will handle both commands and chat responses via the agent
                    



