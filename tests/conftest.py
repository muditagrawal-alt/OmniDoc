"""
Every test runs against a throwaway data folder, whichever test file is collected first: without
this, a file that imports the server before setting OMNIDOC_DATA_DIR would write test accounts,
documents and keys into the real library (.data).
"""
import os
import sys
import tempfile

os.environ.setdefault("OMNIDOC_DATA_DIR", tempfile.mkdtemp(prefix="omnidoc-test-"))
os.environ.setdefault("OMNIDOC_WARMUP", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
