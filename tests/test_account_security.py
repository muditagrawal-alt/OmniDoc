"""
Sign-in without e-mail on a hosted OmniDoc: passkeys, recovery codes, authenticator apps as a second
step, the devices list, linked sign-in, data export, notices, the guest demo and abuse limits.

Passkeys are exercised with a software authenticator (a P-256 key that answers WebAuthn ceremonies
the way a phone or laptop would), so no browser is needed.
"""
import io
import os
import sys
import json
import time
import struct
import hashlib
import zipfile
import tempfile

_TMP_DATA = tempfile.mkdtemp(prefix="omnidoc-security-test-")
os.environ.setdefault("OMNIDOC_DATA_DIR", _TMP_DATA)
os.environ.setdefault("OMNIDOC_WARMUP", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cbor2  # noqa: E402
import pyotp  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from webauthn.helpers import bytes_to_base64url  # noqa: E402

import server  # noqa: E402
from core import abuse, accounts  # noqa: E402

client = TestClient(server.app)
ORIGIN = "http://localhost:8000"
MAC_CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
WINDOWS_FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:144.0) Gecko/20100101 Firefox/144.0"


class SoftAuthenticator:
    """A passkey on a pretend device: makes and signs WebAuthn responses with its own P-256 key."""

    def __init__(self, origin: str = ORIGIN):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.origin = origin
        self.count = 0
        self.handle = None

    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def create(self, options):
        self.handle = options["user"]["id"]
        client_data = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": self.origin}).encode()
        auth_data = (hashlib.sha256(options["rp"]["id"].encode()).digest() + bytes([0x45]) + struct.pack(">I", 0)
                     + bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose_key())
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        cid = bytes_to_base64url(self.credential_id)
        return {"id": cid, "rawId": cid, "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": bytes_to_base64url(client_data),
                             "attestationObject": bytes_to_base64url(attestation), "transports": ["internal"]}}

    def get(self, options):
        self.count += 1
        client_data = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": self.origin}).encode()
        auth_data = hashlib.sha256(options["rpId"].encode()).digest() + bytes([0x05]) + struct.pack(">I", self.count)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        cid = bytes_to_base64url(self.credential_id)
        return {"id": cid, "rawId": cid, "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": bytes_to_base64url(client_data), "authenticatorData": bytes_to_base64url(auth_data),
                             "signature": bytes_to_base64url(signature), "userHandle": self.handle}}


def solve(challenge):
    """What the browser does: find the number whose SHA-256 (after the salt) is the challenge."""
    for n in range(challenge["maxnumber"] + 1):
        if hashlib.sha256(f"{challenge['salt']}{n}".encode()).hexdigest() == challenge["challenge"]:
            return {**challenge, "number": n}
    raise AssertionError("no solution")


def proof():
    return solve(client.get("/api/auth/challenge").json())


@pytest.fixture
def hosted(monkeypatch):
    sent = {}
    monkeypatch.setenv("OMNIDOC_ACCOUNTS", "1")
    monkeypatch.setenv("OMNIDOC_OTP_LOG", "1")
    monkeypatch.setenv("OMNIDOC_PUBLIC_URL", ORIGIN)
    monkeypatch.setenv("OMNIDOC_POW_MAX", "500")
    monkeypatch.setattr(accounts, "send_code_email", lambda to, code: sent.__setitem__(to, code))
    abuse.limiter.reset()
    return sent


def signup(name="Asha Rao", device=None, ua=MAC_CHROME):
    device = device or SoftAuthenticator()
    start = client.post("/api/auth/passkey/signup/options", json={"name": name, "pow": proof()})
    assert start.status_code == 200, start.text
    done = client.post("/api/auth/passkey/signup/verify", headers={"User-Agent": ua},
                       json={"challenge_id": start.json()["challenge_id"], "credential": device.create(start.json()["options"])})
    assert done.status_code == 200, done.text
    body = done.json()
    return device, {"X-OmniDoc-Token": body["token"]}, body


def passkey_sign_in(device, ua=MAC_CHROME):
    start = client.post("/api/auth/passkey/signin/options").json()
    return client.post("/api/auth/passkey/signin/verify", headers={"User-Agent": ua},
                       json={"challenge_id": start["challenge_id"], "credential": device.get(start["options"])})


def email_sign_in(sent, email, ua=MAC_CHROME):
    # Several sign-ins in a row: lift the one-code-a-minute spacing that protects real inboxes.
    server.db.conn.execute("UPDATE otp_codes SET last_sent = 0, sends = 0 WHERE email = ?", (email,))
    server.db.conn.commit()
    assert client.post("/api/auth/code/request", json={"email": email}).status_code == 200
    return client.post("/api/auth/code/verify", json={"email": email, "code": sent[email]}, headers={"User-Agent": ua})


def test_creating_an_account_with_a_passkey_needs_no_email(hosted):
    methods = client.get("/api/auth/methods").json()
    assert methods["passkey"] and not methods["demo"]
    device, headers, body = signup()
    assert body["user"]["email"] == "" and body["user"]["provider"] == "passkey" and body["user"]["name"] == "Asha Rao"
    assert len(body["recovery_codes"]) == 10 and len(set(body["recovery_codes"])) == 10
    assert "totp_secret" not in body["user"] and "webauthn_handle" not in body["user"]
    account = client.get("/api/account", headers=headers).json()
    assert account["security"] == {"passkeys": 1, "totp": False, "recovery_codes_left": 10, "email": ""}
    # Sign out, then back in with the passkey alone.
    client.post("/api/auth/logout", headers=headers)
    assert client.get("/api/chats", headers=headers).status_code == 401
    again = passkey_sign_in(device)
    assert again.status_code == 200 and again.json()["user"]["id"] == body["user"]["id"]
    assert server.db.get_passkey(bytes_to_base64url(device.credential_id))["sign_count"] == 1


def test_passkey_ceremonies_reject_other_sites_and_replays(hosted):
    device, _, _ = signup()
    # A response made for another site (a phishing page) is refused.
    start = client.post("/api/auth/passkey/signin/options").json()
    device.origin = "https://omnidoc-login.example"
    bad = client.post("/api/auth/passkey/signin/verify", json={"challenge_id": start["challenge_id"], "credential": device.get(start["options"])})
    assert bad.status_code == 401
    # A challenge works once, even with a valid response.
    device.origin = ORIGIN
    start = client.post("/api/auth/passkey/signin/options").json()
    response = device.get(start["options"])
    assert client.post("/api/auth/passkey/signin/verify", json={"challenge_id": start["challenge_id"], "credential": response}).status_code == 200
    assert client.post("/api/auth/passkey/signin/verify", json={"challenge_id": start["challenge_id"], "credential": response}).status_code == 400
    # A passkey nobody registered signs nobody in.
    stranger = SoftAuthenticator()
    stranger.handle = "x"
    start = client.post("/api/auth/passkey/signin/options").json()
    assert client.post("/api/auth/passkey/signin/verify", json={"challenge_id": start["challenge_id"], "credential": stranger.get(start["options"])}).status_code == 401


def test_sign_up_needs_the_proof_of_work(hosted):
    assert client.post("/api/auth/passkey/signup/options", json={"name": "Bot"}).status_code == 400
    solution = proof()
    assert client.post("/api/auth/passkey/signup/options", json={"name": "Ravi", "pow": solution}).status_code == 200
    reused = client.post("/api/auth/passkey/signup/options", json={"name": "Ravi", "pow": solution})
    assert reused.status_code == 400 and "already used" in reused.json()["detail"]
    forged = {**proof(), "signature": "0" * 64}
    assert client.post("/api/auth/passkey/signup/options", json={"name": "Ravi", "pow": forged}).status_code == 400


def test_recovery_codes_sign_in_once_each(hosted):
    _, _, body = signup()
    code = body["recovery_codes"][3]
    first = client.post("/api/auth/recovery", json={"code": code.upper().replace("-", " "), "pow": proof()})
    assert first.status_code == 200 and first.json()["recovery_codes_left"] == 9
    assert first.json()["user"]["id"] == body["user"]["id"]
    assert client.post("/api/auth/recovery", json={"code": code, "pow": proof()}).status_code == 401
    notices = client.get("/api/notices", headers={"X-OmniDoc-Token": first.json()["token"]}).json()
    assert any("recovery code" in n["title"] for n in notices["notices"]) and notices["unread"] >= 1


def test_an_authenticator_app_becomes_the_second_step(hosted):
    response = email_sign_in(hosted, "kiran@example.com")
    headers = {"X-OmniDoc-Token": response.json()["token"]}
    setup = client.post("/api/account/totp/setup", headers=headers).json()
    assert setup["uri"].startswith("otpauth://totp/OmniDoc:kiran%40example.com?") and setup["qr_svg"].startswith("<svg")
    totp = pyotp.TOTP(setup["secret"])
    assert client.post("/api/account/totp/enable", headers=headers, json={"challenge_id": setup["challenge_id"], "code": "000000"}).status_code == 400
    enabled = client.post("/api/account/totp/enable", headers=headers, json={"challenge_id": setup["challenge_id"], "code": totp.now()})
    assert enabled.status_code == 200 and len(enabled.json()["recovery_codes"]) == 10
    recovery = enabled.json()["recovery_codes"]
    stored = server.db.get_user_by_email("kiran@example.com")["totp_secret"]
    assert stored.startswith("g1:") and setup["secret"] not in stored  # encrypted at rest

    # E-mailed code now gives a ticket, not a session.
    step_one = email_sign_in(hosted, "kiran@example.com").json()
    assert "token" not in step_one and step_one["mfa"]
    assert client.post("/api/auth/mfa", json={"ticket": step_one["mfa"], "code": totp.now()}).status_code == 401  # already used
    later = totp.at(time.time() + 30)
    done = client.post("/api/auth/mfa", json={"ticket": step_one["mfa"], "code": later})
    assert done.status_code == 200 and done.json()["user"]["email"] == "kiran@example.com"
    # A recovery code also works as the second step, once.
    ticket = email_sign_in(hosted, "kiran@example.com").json()["mfa"]
    assert client.post("/api/auth/mfa", json={"ticket": ticket, "code": recovery[0]}).status_code == 200
    ticket = email_sign_in(hosted, "kiran@example.com").json()["mfa"]
    assert client.post("/api/auth/mfa", json={"ticket": ticket, "code": recovery[0]}).status_code == 401


def test_devices_can_be_listed_and_signed_out(hosted):
    device, mac, body = signup(ua=MAC_CHROME)
    pc = {"X-OmniDoc-Token": passkey_sign_in(device, ua=WINDOWS_FIREFOX).json()["token"]}
    sessions = client.get("/api/account/sessions", headers=mac).json()["sessions"]
    assert {s["device"] for s in sessions} == {"Chrome on macOS", "Firefox on Windows"}
    assert [s["current"] for s in sessions].count(True) == 1
    assert "token" not in json.dumps(sessions)
    # A new kind of device leaves a security notice.
    titles = [n["title"] for n in client.get("/api/notices", headers=mac).json()["notices"]]
    assert "New sign-in: Firefox on Windows" in titles
    pc_session = next(s for s in sessions if s["device"] == "Firefox on Windows")
    assert client.delete(f"/api/account/sessions/{pc_session['id']}", headers=mac).status_code == 200
    assert client.get("/api/chats", headers=pc).status_code == 401
    other = {"X-OmniDoc-Token": passkey_sign_in(device, ua=WINDOWS_FIREFOX).json()["token"]}
    assert client.post("/api/account/sessions/sign-out-others", headers=mac).json()["signed_out"] == 1
    assert client.get("/api/chats", headers=other).status_code == 401
    assert client.get("/api/chats", headers=mac).status_code == 200


def test_the_last_way_in_cannot_be_removed(hosted):
    device, headers, _ = signup()
    only = bytes_to_base64url(device.credential_id)
    assert client.delete(f"/api/account/passkeys/{only}", headers=headers).status_code == 409
    second = SoftAuthenticator()
    start = client.post("/api/account/passkeys/options", headers=headers).json()
    assert [c["id"] for c in start["options"]["excludeCredentials"]] == [only]
    added = client.post("/api/account/passkeys/verify", headers=headers,
                        json={"challenge_id": start["challenge_id"], "credential": second.create(start["options"]), "label": "YubiKey"})
    assert added.status_code == 200 and [k["label"] for k in added.json()["passkeys"]] == ["Chrome on macOS", "YubiKey"]
    assert client.delete(f"/api/account/passkeys/{only}", headers=headers).status_code == 200
    assert passkey_sign_in(device).status_code == 401
    assert passkey_sign_in(second).status_code == 200


def test_linking_github_to_a_passkey_account(hosted, monkeypatch):
    monkeypatch.setenv("OMNIDOC_GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("OMNIDOC_GITHUB_CLIENT_SECRET", "client-secret")
    _, headers, body = signup()
    url = client.post("/api/account/link/github", headers=headers).json()["url"]
    state = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))["state"]

    class Reply:
        def __init__(self, data):
            self.data, self.status_code = data, 200

        def json(self):
            return self.data
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **k: Reply({"access_token": "gh"}))
    monkeypatch.setattr(httpx, "get", lambda url, **k: Reply(
        [{"email": "asha@users.example", "verified": True, "primary": True}] if url.endswith("/emails") else {"login": "asha"}))
    done = client.get(f"/api/auth/oauth/github/callback?code=c&state={state}", follow_redirects=False)
    assert done.headers["location"].endswith("#linked=github")
    me = client.get("/api/account", headers=headers).json()
    assert me["user"]["id"] == body["user"]["id"] and me["security"]["email"] == "asha@users.example"


def test_exporting_everything_as_a_zip(hosted):
    response = email_sign_in(hosted, "export@example.com")
    headers, user = {"X-OmniDoc-Token": response.json()["token"]}, response.json()["user"]
    upload_dir = server.UPLOAD_DIR
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "doc_export1.txt").write_text("Revenue grew 12%.")
    server.db.add_document("doc_export1", "notes.txt", "hash-export", 17, "txt", owner_id=user["id"])
    chat = client.post("/api/chats", json={"title": "Q4 revenue"}, headers=headers).json()["chat"]
    server.db.add_message(chat["id"], "user", "How did revenue change?")
    server.db.add_message(chat["id"], "assistant", "It grew 12% [1].")
    exported = client.get("/api/account/export", headers=headers)
    assert exported.status_code == 200 and exported.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    names = archive.namelist()
    assert "account.json" in names and "documents/doc_export1-notes.txt" in names
    assert archive.read("documents/doc_export1-notes.txt") == b"Revenue grew 12%."
    transcript = next(n for n in names if n.startswith("conversations/") and n.endswith(".md"))
    assert "It grew 12% [1]." in archive.read(transcript).decode()
    assert "totp_secret" not in archive.read("account.json").decode()


def test_guests_read_the_demo_library_and_change_nothing(hosted, monkeypatch):
    assert client.post("/api/auth/guest", json={"pow": proof()}).status_code == 404
    monkeypatch.setenv("OMNIDOC_DEMO", "1")
    monkeypatch.setenv("OMNIDOC_GUEST_QUESTIONS", "1")
    server.db.add_document("doc_demo1", "annual-report.pdf", "hash-demo", 500, "pdf", owner_id=accounts.DEMO_OWNER)
    assert client.get("/api/auth/methods").json()["demo"] is True
    assert client.post("/api/auth/guest", json={}).status_code == 400  # proof of work first
    guest = client.post("/api/auth/guest", json={"pow": proof()})
    assert guest.status_code == 200 and guest.json()["user"]["id"].startswith("gst_")
    headers = {"X-OmniDoc-Token": guest.json()["token"]}
    assert [d["id"] for d in client.get("/api/documents", headers=headers).json()["documents"]] == ["doc_demo1"]
    assert server.scoped_ids([], guest.json()["user"]["id"]) == ["doc_demo1"]
    assert client.post("/api/chats", json={"title": "Demo"}, headers=headers).status_code == 200
    upload = client.post("/api/documents/upload", headers=headers, files={"file": ("x.txt", b"x", "text/plain")})
    assert upload.status_code == 403 and "read-only" in upload.json()["detail"]
    assert client.delete("/api/documents/doc_demo1", headers=headers).status_code == 403
    assert client.get("/api/account/sessions", headers=headers).status_code == 403
    assert client.delete("/api/account", headers=headers).status_code == 403
    account = client.get("/api/account", headers=headers).json()
    assert account["guest"] and account["limits"]["questions_per_day"] == 1
    server.db.count_usage(guest.json()["user"]["id"], "questions")
    with pytest.raises(server.HTTPException) as exc:
        server.check_quota(guest.json()["user"]["id"], "questions")
    assert exc.value.status_code == 429


def test_administrator_settings_need_two_step_sign_in(hosted, monkeypatch):
    monkeypatch.setenv("OMNIDOC_ADMIN_EMAILS", "admin@example.com")
    headers = {"X-OmniDoc-Token": email_sign_in(hosted, "admin@example.com").json()["token"]}
    blocked = client.put("/api/models/current", headers=headers, json={"model": "anything"})
    assert blocked.status_code == 403 and "two-step" in blocked.json()["detail"]
    user_headers = {"X-OmniDoc-Token": email_sign_in(hosted, "member@example.com").json()["token"]}
    assert client.put("/api/models/current", headers=user_headers, json={"model": "anything"}).status_code == 403


def test_repeated_attempts_are_rate_limited(hosted):
    for _ in range(10):
        assert client.post("/api/auth/recovery", json={"code": "aaaa-bbbb-cccc", "pow": proof()}).status_code == 401
    limited = client.post("/api/auth/recovery", json={"code": "aaaa-bbbb-cccc", "pow": proof()})
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_forwarded_addresses_are_believed_only_from_a_local_proxy():
    assert abuse.client_ip("172.18.0.3", "203.0.113.9") == "203.0.113.9"
    assert abuse.client_ip("172.18.0.3", "198.51.100.1, 203.0.113.9") == "203.0.113.9"
    assert abuse.client_ip("198.51.100.7", "203.0.113.9") == "198.51.100.7"  # a visitor cannot pick their address
    assert accounts.device_label(MAC_CHROME) == "Chrome on macOS"
    assert accounts.device_label("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit Version/18.0 Mobile Safari/604.1") == "Safari on iPhone"
