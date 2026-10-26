# Stand-in for the local AI, behaving like a small, over-eager model, to test CleanListen's handling.
import re
calls = []
def ensure_ai(progress=None):
    if progress: progress(1.0, "AI ready")
def chat(prompt, images=None, schema=None, timeout=300):
    calls.append(prompt[:40])
    if "sentences in order" in prompt:                     # reading pass: over-flags, by quote
        flags = []
        for line in prompt.splitlines():
            if not line.startswith("- "): continue
            t = line[2:]; low = t.lower(); q = " ".join(t.split()[:8])
            if "affair" in low: flags.append({"quote": q, "type": "ref"})            # real
            if "rolled her eyes" in low: flags.append({"quote": q, "type": "ref"})   # over-eager nonsense
            if "pulled him toward" in low: flags.append({"quote": "She pulled him towards the bedroom breathless", "type": "sex"})  # slightly misquoted
            if "studied the wound" in low: flags.append({"quote": q, "type": "language", "word": "wound"})
        return {"flags": flags}
    if ">>>" in prompt:                                      # strict check of one sentence
        marked = prompt.split("\n>>> ")[-1].split(" <<<")[0].lower()
        if "affair" in marked: return {"fits": True, "confidence": "high"}
        if "wound" in marked: return {"fits": True, "confidence": "medium"}
        return {"fits": False, "confidence": "high"}          # rejects the nonsense
    if "Does it contain" in prompt:
        return {"fits": "motel" not in prompt}
    if "double brackets" in prompt:
        return {"fine": [0, 1, 2, 3]}                          # tries to untick everything it's shown
    return {}
