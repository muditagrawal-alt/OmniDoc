"""
The demo's sample library is built the same way every time, byte for byte: a server only reads a
sample again when it really changed, so an image rebuild does not spend model calls re-reading it.
"""
import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_samples_are_identical_on_every_build(tmp_path):
    spec = importlib.util.spec_from_file_location("make_samples", ROOT / "deploy" / "demo" / "make_samples.py")
    samples = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(samples)
    samples.main(str(tmp_path / "a"))
    samples.main(str(tmp_path / "b"))
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    names = sorted(p.name for p in (tmp_path / "a").iterdir())
    assert len(names) >= 4
    assert [digest(tmp_path / "a" / n) for n in names] == [digest(tmp_path / "b" / n) for n in names]
