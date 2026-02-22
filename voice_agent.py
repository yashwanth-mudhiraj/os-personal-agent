import sounddevice as sd
import numpy as np
import torch
from kokoro import KPipeline

VOICES = [
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore",
    "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky", "am_adam",
    "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
    "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis", "ef_dora", "em_alex",
    "em_santa", "ff_siwis", "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
    "if_sara", "im_nicola", "jf_alpha", "jf_gongitsune", "jf_nezumi",
    "jf_tebukuro", "jm_kumo", "pf_dora", "pm_alex", "pm_santa", "zf_xiaobei",
    "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian", "zm_yunxi",
    "zm_yunxia", "zm_yunyang"
]

# Initialize the pipeline once
# 'a' is for American English. Use 'b' for British.
pipeline = KPipeline(lang_code='b', device='cuda' if torch.cuda.is_available() else 'cpu')

def speak(text):
    print(f"\n🗣 Generating Audio: {text}")

    # The pipeline returns a generator of (graphemes, phonemes, audio)
    generator = pipeline(
        text, 
        voice='bf_alice', # 'af_heart' is high quality. Try 'af_bella' too.
        speed=1, 
        split_pattern=r'\n+'
    )

    for i, (gs, ps, audio) in enumerate(generator):
        # audio is a numpy array
        sd.play(audio, samplerate=24000)
        sd.wait()

if __name__ == "__main__":
    print("--- Kokoro TTS Ready ---")
    while True:
        text = input("You: ")
        if text.lower() == "exit":
            break
        if text.strip():
            speak(text)