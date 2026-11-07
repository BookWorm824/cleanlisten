"""Make readaloud_voices.npz: each voice clip's "fingerprint" for the Qwen acting reader.

The acting reader (Qwen3-TTS VoiceDesign) is given the voice's clip as well as the acting note, so a
character keeps one voice from line to line (Lauren, 2026-11-06: "its switching voices even though
the same person is speaking": described afresh for every line, a voice came out a little different
each time; measured with Chatterbox's voice encoder, the narrator's lines were 0.77 alike, and 0.88
with the clip). The clip has to be turned into codec codes plus a speaker embedding, and only the
Base model has the speaker encoder, so this is done once here and shipped, and acting users don't
need the Base model too.

Run in ReadAloud's graphics-card venv, with the Base ("steady") model set up:
    %LOCALAPPDATA%\\CleanListen\\gpu\\venv\\Scripts\\python.exe tools\\make_voice_prints.py
"""
import sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import readaloud_gpu as G  # noqa: E402
from qwen_tts import Qwen3TTSModel  # noqa: E402

m = Qwen3TTSModel.from_pretrained(str(G.model_dir("steady")), device_map="cuda:0", dtype=torch.bfloat16,
                                  attn_implementation="sdpa")
out = {}
for vid in G.GPU_VOICES:
    it = m.create_voice_clone_prompt(ref_audio=str(G.voice_clip(vid)), ref_text=G.REF_TEXT)[0]
    out[f"{vid}.code"] = it.ref_code.detach().cpu().numpy().astype(np.int16)
    out[f"{vid}.spk"] = it.ref_spk_embedding.detach().float().cpu().numpy().astype(np.float32)
    print(vid, out[f"{vid}.code"].shape, out[f"{vid}.spk"].shape)
np.savez_compressed(HERE / "readaloud_voices.npz", **out)
print("saved", (HERE / "readaloud_voices.npz").stat().st_size, "bytes")
