"""Updates carry the owner's seal (1.17.81, as CleanView 1.18.147; the owner, 2026-11-19, in the
CleanView chat: "could someone use another ai chat to change it?", "yes, label the key so its
obvious what it is", "tell the other chats to do the same"). An installed copy of CleanListen,
CleanRead or ReadAloud takes an update only when version.sig is the owner's Ed25519 signature
of version.json and every file it downloads has the fingerprint version.json lists. Tests use a
made-up key, never the owner's, and nothing goes online: a stand-in urlopen, or a server on
this PC."""
import functools
import hashlib
import http.server
import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
import threading
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import sign_release  # noqa: E402

TEST_SEED = bytes(range(32))       # a made-up key for tests, never the owner's

RFC_8032 = [   # secret, public, message, signature (RFC 8032 section 7.1, tests 1 and 2)
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e3970"
     "1cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613"
     "d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]


def load_launcher(path=REPO / "launcher.pyw", name="cl_launcher_sealed"):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def use_test_key(lm):
    lm.PUBLIC_KEY = sign_release.public_of(TEST_SEED, lm)


def sealed_release(lm, remote, files, seed=TEST_SEED):
    """version.json's bytes (with every file's fingerprint) and version.sig's text."""
    remote = dict(remote)
    remote["sha256"] = {n: hashlib.sha256(files[n]).hexdigest() for n in remote["files"]}
    data = json.dumps(remote).encode("utf8")
    return data, sign_release.sign(seed, lm.SEAL_FOR.encode("utf8") + data, lm).hex()


# ---------- the seal itself ----------
def test_the_standard_examples():
    lm = load_launcher()
    for sk, pk, msg, sig in RFC_8032:
        sk, pk, msg, sig = map(bytes.fromhex, (sk, pk, msg, sig))
        assert sign_release.public_of(sk, lm) == pk
        assert sign_release.sign(sk, msg, lm) == sig
        assert lm.ed25519_ok(pk, msg, sig)
        assert not lm.ed25519_ok(pk, msg + b"!", sig)
        for i in (0, 31, 32, 63):
            bad = bytearray(sig)
            bad[i] ^= 1
            assert not lm.ed25519_ok(pk, msg, bytes(bad)), i
        assert not lm.ed25519_ok(pk, msg, sig[:63])


def test_the_owners_public_key_is_a_real_one_and_its_own():
    lm = load_launcher()
    assert lm.PUBLIC_KEY != bytes(32) and lm._ed_point(lm.PUBLIC_KEY) is not None
    assert lm.SEAL_FOR == "CleanListen update\n"
    cv = Path(r"C:\Users\morga\Downloads\CleanView Setup\cleanview-repo\launcher.pyw")
    if cv.exists():                                     # CleanView's key is a different one
        assert lm.PUBLIC_KEY.hex() not in cv.read_text(encoding="utf8")


def test_the_key_file_says_what_it_is(tmp_path):
    text = sign_release.key_text(TEST_SEED, sign_release.public_of(TEST_SEED))
    assert text.startswith("CLEANLISTEN, CLEANREAD AND READALOUD UPDATE KEY  -  SECRET, DO NOT SHARE")
    for said in ("If it's lost", "Keep it secret", "Google Drive", "CleanView has its own"):
        assert said in text
    p = tmp_path / "key.txt"
    p.write_text(text, encoding="utf8")
    assert sign_release.read_key(p) == TEST_SEED


def test_a_new_key_never_replaces_the_one_there(tmp_path, monkeypatch):
    key = tmp_path / "key.txt"
    key.write_text("the owner's key", encoding="utf8")
    monkeypatch.setattr(sign_release, "KEY_FILE", key)
    with pytest.raises(SystemExit):
        sign_release.new_key()
    assert key.read_text(encoding="utf8") == "the owner's key"


@pytest.mark.parametrize("app", ["CleanListen.pyw", "CleanRead.pyw"])
def test_the_apps_only_offer_a_sealed_update(app):
    src = (REPO / app).read_text(encoding="utf8")
    assert "L.remote_version(timeout=10)" in src
    assert 'L.RAW + "version.json"' not in src


# ---------- what an installed copy takes and turns down ----------
class Copy:
    def __init__(self, tmp_path):
        self.lm = load_launcher()
        use_test_key(self.lm)
        self.here = tmp_path
        (self.here / "version.json").write_text(json.dumps({"version": "1.0.0", "files": []}))
        (self.here / "CleanListen.pyw").write_bytes(b"old = 1\n")
        self.files = {"CleanListen.pyw": b"new = 2\n", "cleanlisten.py": b"x = 1\n",
                      "shared_learned.json": b"{}"}
        self.remote = {"version": "1.0.1", "files": list(self.files)}
        self.serve()

    def serve(self, seed=TEST_SEED):
        data, sig = sealed_release(self.lm, self.remote, self.files, seed)
        self.served = dict(self.files, **{"version.json": data, "version.sig": sig.encode()})

    def urlopen(self, url, timeout=None):
        name = url.rsplit("/", 1)[-1]
        if name not in self.served:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        r = io.BytesIO(self.served[name])
        return mock.MagicMock(__enter__=lambda s: r, __exit__=lambda s, *a: None)

    def update(self):
        with mock.patch.object(self.lm.urllib.request, "urlopen", self.urlopen), \
                mock.patch.object(self.lm, "HERE", self.here):
            return self.lm.update()

    def turned_down(self):
        with pytest.raises(Exception):
            self.update()
        assert (self.here / "CleanListen.pyw").read_bytes() == b"old = 1\n"
        assert not (self.here / "cleanlisten.py").exists()
        assert json.loads((self.here / "version.json").read_text())["version"] == "1.0.0"


@pytest.fixture
def copy(tmp_path):
    return Copy(tmp_path)


def test_a_sealed_update_goes_in(copy):
    assert copy.update() == "1.0.1"
    for name, body in copy.files.items():
        assert (copy.here / name).read_bytes() == body
    kept = json.loads((copy.here / "version.json").read_text())
    assert kept["version"] == "1.0.1" and "sha256" in kept


def test_no_seal(copy):
    del copy.served["version.sig"]
    copy.turned_down()


def test_an_empty_or_garbled_seal(copy):
    for sig in (b"", b"not a seal", b"00" * 64):
        copy.served["version.sig"] = sig
        copy.turned_down()


def test_someone_elses_key(copy):
    copy.serve(seed=bytes(32))
    copy.turned_down()


def test_version_json_changed_after_the_seal(copy):
    copy.served["version.json"] = copy.served["version.json"].replace(b"1.0.1", b"1.0.2")
    copy.turned_down()


def test_a_file_that_isnt_the_one_listed(copy):
    copy.served["cleanlisten.py"] = b"import os; os.system('bad')\n"
    copy.turned_down()


def test_a_file_without_a_fingerprint(copy):
    copy.files["extra.py"] = b"y = 1\n"
    copy.remote = {"version": "1.0.1", "files": list(copy.files)}
    data, _ = sealed_release(copy.lm, copy.remote, copy.files)
    listed = json.loads(data)
    del listed["sha256"]["extra.py"]
    data = json.dumps(listed).encode()
    sig = sign_release.sign(TEST_SEED, copy.lm.SEAL_FOR.encode() + data, copy.lm)
    copy.served.update({"extra.py": b"y = 1\n", "version.json": data, "version.sig": sig.hex().encode()})
    copy.turned_down()


def test_cleanviews_seal_doesnt_open_ours(copy):
    data = copy.served["version.json"]
    sig = sign_release.sign(TEST_SEED, b"CleanView update\n" + data, copy.lm)
    copy.served["version.sig"] = sig.hex().encode()
    copy.turned_down()


def test_nothing_newer_is_left_alone(copy):
    copy.remote["version"] = "1.0.0"
    copy.serve()
    assert copy.update() is None


def test_a_turned_down_update_still_opens_the_program():
    src = (REPO / "launcher.pyw").read_text(encoding="utf8")
    assert "except Exception as ex:  # never block the app over an update problem" in src


# ---------- a whole release: sealed in git, served from this PC, taken ----------
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture
def release(tmp_path, monkeypatch):
    repo, installed = tmp_path / "repo", tmp_path / "installed"
    repo.mkdir()
    installed.mkdir()
    lm = load_launcher()
    test_public = sign_release.public_of(TEST_SEED, lm).hex()
    launcher = (REPO / "launcher.pyw").read_text(encoding="utf8").replace(lm.PUBLIC_KEY.hex(), test_public)
    files = {"launcher.pyw": launcher, "CleanListen.pyw": "app = 2\n", "cleanread.py": "core = 2\n"}
    for n, body in files.items():
        (repo / n).write_text(body, encoding="utf8", newline="\n")
    (repo / "version.json").write_text(json.dumps({"version": "1.0.1", "files": list(files)}) + "\n",
                                       encoding="utf8")

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", *args],
                              capture_output=True, check=True).stdout
    git("init", "-q")
    git("add", ".")
    key = tmp_path / "key.txt"
    key.write_text(sign_release.key_text(TEST_SEED, bytes.fromhex(test_public)), encoding="utf8")
    # another chat's unfinished change, in the working copy only
    (repo / "version.json").write_text(json.dumps(
        {"version": "1.0.1", "files": list(files) + ["unfinished.py"]}) + "\n")
    monkeypatch.setattr(sign_release, "REPO", repo)
    monkeypatch.setattr(sign_release, "KEY_FILE", key)
    with mock.patch("builtins.print"):
        sign_release.seal()

    def serve():
        out = tmp_path / "web"
        out.mkdir(exist_ok=True)
        for n in list(files) + ["version.json", "version.sig"]:
            (out / n).write_bytes(git("show", f":{n}"))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(out)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def installed_copy():
        (installed / "version.json").write_text(json.dumps({"version": "1.0.0", "files": []}))
        (installed / "CleanListen.pyw").write_text("app = 1\n")
        lm = load_launcher(name="cl_launcher_installed")
        use_test_key(lm)
        return lm
    return dict(repo=repo, installed=installed, files=files, git=git, serve=serve, copy=installed_copy)


def test_sealed_checked_and_taken(release):
    staged = json.loads(release["git"]("show", ":version.json"))
    assert set(staged["sha256"]) == set(release["files"])
    assert "unfinished.py" not in staged["files"]
    kept = json.loads((release["repo"] / "version.json").read_text())
    assert "unfinished.py" in kept["files"]                     # the other chat's work kept
    assert kept["sha256"] == staged["sha256"]
    with mock.patch("builtins.print"):
        sign_release.check()
    server = release["serve"]()
    try:
        lm = release["copy"]()
        raw = f"http://127.0.0.1:{server.server_address[1]}/"
        with mock.patch.multiple(lm, HERE=release["installed"], RAW=raw):
            assert lm.update() == "1.0.1"
    finally:
        server.shutdown()
        server.server_close()
    for n, body in release["files"].items():
        assert (release["installed"] / n).read_text(encoding="utf8") == body


def test_a_file_changed_after_the_seal(release):
    (release["repo"] / "cleanread.py").write_text("core = 3\n")
    release["git"]("add", "cleanread.py")
    with pytest.raises(ValueError), mock.patch("builtins.print"):
        sign_release.check()
    server = release["serve"]()
    try:
        lm = release["copy"]()
        raw = f"http://127.0.0.1:{server.server_address[1]}/"
        with mock.patch.multiple(lm, HERE=release["installed"], RAW=raw), pytest.raises(lm.NotSealed):
            lm.update()
    finally:
        server.shutdown()
        server.server_close()
    assert (release["installed"] / "CleanListen.pyw").read_text() == "app = 1\n"
