"""
Behaviour under concurrent load: the first requests to a fresh server agree on one secret key
(they used to race, and one could crash or read an empty key).
"""
import threading

from core import accounts


def test_concurrent_first_requests_agree_on_one_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OMNIDOC_SECRET_KEY", raising=False)
    folder = tmp_path / "fresh"
    keys, errors, start = [], [], threading.Barrier(32)

    def first_request():
        start.wait()
        try:
            keys.append(accounts._secret(folder))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=first_request) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(set(keys)) == 1 and len(keys[0]) == 64
    assert (folder / "secret.key").read_text().strip().encode() == keys[0]
    assert not [p for p in folder.iterdir() if p.name.startswith(".secret.key.")]  # no temporary files left
