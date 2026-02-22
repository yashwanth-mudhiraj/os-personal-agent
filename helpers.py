import re
import string
import constants as const
from agent import SimpleAgent
from voice_agent import speak
import app_control as ac

# =====================
# TEXT CLEANUP
# =====================
def remove_leading_the(final_text: str) -> str:
    # Remove "the" only at the start of a sentence
    # return re.sub(r'(?i)(^|[.!?]\s+)\s*the\s+', r'\1', text).strip() 
    cleaned_text = final_text.strip().lower()
                
    # Strip basic punctuation to catch "you." or "you!"
    cleaned_text = cleaned_text.translate(str.maketrans('', '', string.punctuation))

    # 2. Define known Whisper hallucinations and junk words
    ignore_list = [
        "the",
        "you", 
        "thank you", 
        "thanks for watching", 
        "subscribe", 
        "bye",
        "okay",
        "ok"
    ]

    # 3. Filter out junk, empty strings, or really short accidental noises
    if not cleaned_text or cleaned_text in ignore_list or len(cleaned_text) < 2:
        # It's just background noise or a hallucination, ignore it completely
        return ""
    return cleaned_text

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

    for verb in const.FOCUS_VERBS:
        if text.startswith(verb):
            return "focus", text[len(verb):].strip()

    for verb in const.OPEN_VERBS:
        if text.startswith(verb):
            return "open", text[len(verb):].strip()
        
    for verb in const.CLOSE_VERBS:
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

def extract_command(text: str) -> str | None:
    """
    Returns command text if wake word is present, else None
    """
    if not const.WAKE_REGEX.match(text):
        return None
    return const.WAKE_REGEX.sub("", text).strip()


agent = SimpleAgent()
catalog = ac.load_or_refresh_catalog()

def agent_call(final_text: str):
    # Now returns a LIST of items, e.g., [{"intent": "command", ...}, {"intent": "chat", ...}]
    llm_responses = agent.chat(final_text)

    for task in llm_responses:
        intent = task.get("intent")
        
        if intent == "command":
            # Handle system actions (e.g., "open firefox")
            action = task.get("action")
            target = task.get("target")
            print(f"⚙️ Action: {action} -> {target}")
            ac.handle_app_action(action, target, catalog)
            speak(f"{action}ing {target}")  # Verbal confirmation
            
        elif intent == "chat":
            # Handle verbal responses
            response_text = task.get("response", "I'm not sure how to respond to that.")
            print(f"🤖 Agent: {response_text}")
            speak(response_text)

    print("-" * 30 + "\n")