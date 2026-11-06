"""
Username and password accounts on a hosted OmniDoc: sign-up, sign-in, the authenticator-app step,
"forgot password" with a recovery code (there is no e-mail), password changes, and feedback.
"""
import server
from core import passwords
from test_account_security import client, hosted, proof, signup  # noqa: F401  (hosted is a fixture)

GOOD = "correct horse battery"


def make(username="asha.rao", password=GOOD, name="Asha Rao"):
    r = client.post("/api/auth/password/signup", json={"username": username, "password": password, "name": name, "pow": proof()})
    return r


def sign_in(username, password):
    return client.post("/api/auth/password/signin", json={"username": username, "password": password})


def test_hashes_are_salted_and_slow_to_reverse():
    a, b = passwords.hash_password(GOOD), passwords.hash_password(GOOD)
    assert a != b and a.startswith("scrypt$32768$8$1$")
    assert passwords.verify_password(GOOD, a) and not passwords.verify_password(GOOD + "!", a)
    assert not passwords.verify_password(GOOD, None) and not passwords.verify_password(GOOD, "garbage")
    assert passwords.password_problem("short") and passwords.password_problem("password123")
    assert passwords.password_problem("asha.rao-is-me", "asha.rao") and passwords.password_problem("aaaaaaaaaaaa")
    assert passwords.password_problem(GOOD) is None


def test_signing_up_and_in_with_a_password(hosted):
    assert client.get("/api/auth/methods").json()["password"] is True
    assert client.post("/api/auth/password/signup", json={"username": "kavya", "password": GOOD}).status_code == 400  # proof of work
    weak = make("kavya", "1234567890")
    assert weak.status_code == 400 and "common" in weak.json()["detail"]
    assert make("k", GOOD).status_code == 400
    made = make("Kavya.Iyer", GOOD, "Kavya Iyer")
    assert made.status_code == 200
    body = made.json()
    assert len(body["recovery_codes"]) == 10 and body["user"]["username"] == "kavya.iyer"
    assert body["user"]["has_password"] is True and "password_hash" not in body["user"]
    assert make("kavya.iyer", GOOD).status_code == 409

    assert sign_in("kavya.iyer", "wrong password!").status_code == 401
    assert sign_in("nobody-here", GOOD).status_code == 401
    ok = sign_in("KAVYA.IYER", GOOD)
    assert ok.status_code == 200 and ok.json()["user"]["name"] == "Kavya Iyer"

    server.db.conn.execute("UPDATE users SET totp_enabled = 1 WHERE username = 'kavya.iyer'")
    server.db.conn.commit()
    assert "mfa" in sign_in("kavya.iyer", GOOD).json()  # the authenticator app is still asked for


def test_guessing_one_username_is_limited(hosted):
    assert make("imran", GOOD).status_code == 200
    for _ in range(10):
        assert sign_in("imran", "not the password").status_code == 401
    assert sign_in("imran", GOOD).status_code == 429


def test_forgot_password_is_a_recovery_code_and_a_new_password(hosted):
    made = make("lena", GOOD).json()
    old_session = {"X-OmniDoc-Token": made["token"]}
    code = made["recovery_codes"][0]
    reset = lambda c, p: client.post("/api/auth/password/reset", json={"username": "lena", "code": c, "password": p, "pow": proof()})
    assert reset("aaaa-bbbb-cccc", "a brand new passphrase").status_code == 401
    assert reset(code, "short").status_code == 400  # the code is checked first, then spent only with a good password
    done = reset(made["recovery_codes"][1], "a brand new passphrase")
    assert done.status_code == 200 and done.json()["recovery_codes_left"] == 8
    assert client.get("/api/account", headers=old_session).status_code == 401  # other devices signed out
    assert sign_in("lena", GOOD).status_code == 401
    assert sign_in("lena", "a brand new passphrase").status_code == 200
    assert reset(made["recovery_codes"][1], "yet another passphrase").status_code == 401  # each code works once


def test_passwords_can_be_added_changed_and_removed(hosted):
    _, passkey_headers, _ = signup("Ravi")
    added = client.put("/api/account/password", headers=passkey_headers, json={"password": GOOD, "username": "ravi"})
    assert added.status_code == 200 and added.json()["user"]["has_password"]
    assert sign_in("ravi", GOOD).status_code == 200
    wrong = client.put("/api/account/password", headers=passkey_headers, json={"password": "a different phrase", "current_password": "nope"})
    assert wrong.status_code == 403
    changed = client.put("/api/account/password", headers=passkey_headers, json={"password": "a different phrase", "current_password": GOOD})
    assert changed.status_code == 200 and sign_in("ravi", "a different phrase").status_code == 200
    assert client.delete("/api/account/password", headers=passkey_headers).status_code == 200  # the passkey remains
    assert sign_in("ravi", "a different phrase").status_code == 401

    only = make("meera", GOOD).json()
    blocked = client.delete("/api/account/password", headers={"X-OmniDoc-Token": only["token"]})
    assert blocked.status_code == 400 and "only way" in blocked.json()["detail"]


def test_feedback_reaches_the_administrator_only(hosted, monkeypatch):
    assert client.post("/api/feedback", json={"message": "Lovely citations"}).status_code == 400  # proof of work
    sent = client.post("/api/feedback", json={"message": "Lovely citations", "rating": 5, "contact": "@asha", "pow": proof()})
    assert sent.status_code == 200
    assert client.post("/api/feedback", json={"message": "Bad", "rating": 9, "pow": proof()}).status_code == 422

    # Administrator pages need two-step sign-in: a passkey account has it.
    _, headers, _ = signup("Owner")
    assert client.get("/api/admin/feedback", headers=headers).status_code == 403
    assert client.post("/api/admin/claim", headers=headers, json={"code": server.admin_setup_code()}).status_code == 200
    items = client.get("/api/admin/feedback", headers=headers).json()["feedback"]
    assert items[0]["message"] == "Lovely citations" and items[0]["rating"] == 5
    assert client.delete(f"/api/admin/feedback/{items[0]['id']}", headers=headers).status_code == 200
