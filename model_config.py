# model_config.py
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ======================================================
# SETTINGS
# ======================================================
MODEL_MODE = "local"  # "local", "api", or "auto"

# If using Ollama (Highly Recommended for RTX 5070)
LOCAL_MODEL_NAME = "qwen2.5:7b-instruct"  # Make sure this matches your Ollama model name

# If using OpenAI
API_MODEL_NAME = "gpt-4o-mini"

TEMPERATURE = 0.7
MAX_TOKENS = 512

# ======================================================
# BASE MODEL CLASS
# ======================================================
class BaseModel:
    def generate(self, messages):
        raise NotImplementedError

# ======================================================
# LOCAL MODEL (Optimized via Ollama)
# ======================================================
class LocalModel(BaseModel):
    def __init__(self, model_name):
        print(f"[INFO] Connecting to Ollama: {model_name}")
        # Ollama mimics the OpenAI API on port 11434
        self.client = OpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama"  # Required but ignored by Ollama
        )
        self.model_name = model_name

    def generate(self, messages):
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"Error connecting to Ollama: {e}. Make sure Ollama is running (ollama serve)."

# ======================================================
# API MODEL (OpenAI)
# ======================================================
class APIModel(BaseModel):
    def __init__(self, model_name):
        print(f"[INFO] Using OpenAI API: {model_name}")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")
        self.client = OpenAI(api_key=api_key)
        self.model_name = model_name

    def generate(self, messages):
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
        return response.choices[0].message.content.strip()

# ======================================================
# FACTORY FUNCTION
# ======================================================
def load_model():
    api_key_exists = os.getenv("OPENAI_API_KEY") is not None

    if MODEL_MODE == "local":
        return LocalModel(LOCAL_MODEL_NAME)
    elif MODEL_MODE == "api":
        return APIModel(API_MODEL_NAME)
    elif MODEL_MODE == "auto":
        return APIModel(API_MODEL_NAME) if api_key_exists else LocalModel(LOCAL_MODEL_NAME)
    else:
        raise ValueError("MODEL_MODE must be 'local', 'api', or 'auto'")