"""Seal a CleanListen release (1.17.81, as CleanView 1.18.147). Installed copies of CleanListen,
CleanRead and ReadAloud only take an update whose version.sig fits the public key in
launcher.pyw (see "The owner's seal" there). The three are one set of files with one
version.json, so they share one seal and one key.

Run it from the repo after every other change is staged, as the last step before the commit:

    python tools/sign_release.py           # fingerprints from the staged files, then the seal
    python tools/sign_release.py check     # the staged release checks out, as a copy would see it
    python tools/sign_release.py check origin/main    # what's on GitHub now
    python tools/sign_release.py new-key   # once only: makes the key file (refuses to replace one)

It works on git's staged copy (what will be pushed), and writes version.json's "sha256" and
version.sig there and in the working copy (another chat's unfinished change to the working
copy's version.json is kept). The secret key is read from KEY_FILE (or the file named by
CLEANLISTEN_SEAL_KEY); it's never printed and never goes in the repo."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEY_DIR = Path.home() / "App update keys"
KEY_FILE = Path(os.environ.get("CLEANLISTEN_SEAL_KEY")
                or KEY_DIR / "CleanListen, CleanRead and ReadAloud update key - SECRET.txt")
DRIVE_PLACE = "Google Drive: Cleaning up > App update keys - PRIVATE (only the owner can open it)"


def launcher():
    loader = importlib.machinery.SourceFileLoader("cl_launcher_seal", str(REPO / "launcher.pyw"))
    spec = importlib.util.spec_from_loader("cl_launcher_seal", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def git(*args, data=None):
    return subprocess.run(["git", "-C", str(REPO), *args], input=data, capture_output=True,
                          check=True).stdout


def staged(name, ref=""):
    return git("show", f"{ref}:{name}")


def put_staged(name, data):
    blob = git("hash-object", "-w", "--stdin", data=data).decode().strip()
    git("update-index", "--add", "--cacheinfo", f"100644,{blob},{name}")


# ---- Ed25519 signing (RFC 8032); the curve itself is the launcher's ----
def _expand(seed):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_of(seed, lm=None):
    lm = lm or launcher()
    return lm._ed_bytes(lm._ed_mul(_expand(seed)[0], lm._G))


def sign(seed, message, lm=None):
    lm = lm or launcher()
    a, prefix = _expand(seed)
    public = lm._ed_bytes(lm._ed_mul(a, lm._G))
    r = lm._ed_hash(prefix, message)
    big_r = lm._ed_bytes(lm._ed_mul(r, lm._G))
    s = (r + lm._ed_hash(big_r, public, message) * a) % lm._L
    return big_r + s.to_bytes(32, "little")


def key_text(seed, public):
    return f"""CLEANLISTEN, CLEANREAD AND READALOUD UPDATE KEY  -  SECRET, DO NOT SHARE

What this is: the secret key that seals every update of CleanListen, CleanRead and
ReadAloud (they update together, as one set of files). They only install an update
that carries this seal, so nobody else can send an update to the people using them,
even if they get into the GitHub account. (CleanView has its own, separate key.)

Keep it secret: anyone with this key could seal an update. Don't email it, post it,
or put it on GitHub.

If it's lost: CleanListen, CleanRead and ReadAloud can't be updated any more. Everyone
would need to install them again from a new setup zip with a new key. So keep both copies:
  - on the owner's PC: {KEY_DIR}
  - {DRIVE_PLACE}

Made {date.today().isoformat()} for CleanListen 1.17.81, with tools/sign_release.py.

Public half (it's in CleanListen's launcher.pyw; safe to share):
{public.hex()}

SECRET KEY (Ed25519 seed, hex):
{seed.hex()}
"""


def read_key(path=None):
    path = path or KEY_FILE
    m = re.search(r"SECRET KEY[^\n]*\n\s*([0-9a-f]{64})\s", path.read_text(encoding="utf8") + "\n")
    if not m:
        raise SystemExit(f"No secret key found in {path}")
    return bytes.fromhex(m.group(1))


def new_key():
    if KEY_FILE.exists():
        raise SystemExit(f"{KEY_FILE} is already there; a new key would stop every installed "
                         "copy from updating. Not replaced.")
    seed = secrets.token_bytes(32)
    public = public_of(seed)
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key_text(seed, public), encoding="utf8")
    print("Key file made:", KEY_FILE)
    print("Public half (put in launcher.pyw PUBLIC_KEY):", public.hex())


def with_hashes(text, hashes):
    d = json.loads(text)
    d["sha256"] = {n: hashes[n] for n in d["files"] if n in hashes}
    return json.dumps(d, indent=1) + "\n"


def seal():
    lm = launcher()
    seed = read_key()
    if public_of(seed, lm) != lm.PUBLIC_KEY:
        raise SystemExit("The key file doesn't fit launcher.pyw's PUBLIC_KEY: not sealed.")
    names = json.loads(staged("version.json"))["files"]
    hashes = {n: hashlib.sha256(staged(n)).hexdigest() for n in names}
    data = with_hashes(staged("version.json").decode("utf8"), hashes).encode("utf8")
    put_staged("version.json", data)
    wc = REPO / "version.json"            # the working copy may hold another chat's changes:
    wc.write_text(with_hashes(wc.read_text(encoding="utf8"), hashes), encoding="utf8")  # same fingerprints
    sig = sign(seed, lm.SEAL_FOR.encode("utf8") + data, lm).hex() + "\n"
    (REPO / lm.SIG_NAME).write_text(sig, encoding="ascii", newline="\n")
    put_staged(lm.SIG_NAME, sig.encode("ascii"))
    print(f"Sealed {json.loads(data)['version']}: {len(names)} files.")
    check()


def check(ref=""):
    """What an installed copy would do with the release at ref ("" = staged)."""
    lm = launcher()
    shipped = re.search(r'PUBLIC_KEY = bytes\.fromhex\("([0-9a-f]{64})"\)',
                        staged("launcher.pyw", ref).decode("utf8"))
    if not shipped or bytes.fromhex(shipped.group(1)) != lm.PUBLIC_KEY:
        raise SystemExit("launcher.pyw there doesn't carry this PUBLIC_KEY.")
    remote = lm.sealed(staged("version.json", ref), staged(lm.SIG_NAME, ref).decode("ascii"))
    for n in remote["files"]:
        lm.file_matches(n, staged(n, ref), remote)
    print(f"OK: {remote['version']} is sealed and all {len(remote['files'])} files match"
          f" ({ref or 'staged'}).")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "sign"
    if what == "new-key":
        new_key()
    elif what == "check":
        check(sys.argv[2] if len(sys.argv) > 2 else "")
    elif what == "sign":
        seal()
    else:
        raise SystemExit(__doc__)
