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

# No test sends real mail: the developer's .env may hold a Resend key or SMTP login, and .env is
# loaded without overriding what is already set, so blank values here keep them out. Tests that
# exercise sending set their own values and a fake sender.
for _name in ("RESEND_API_KEY", "OMNIDOC_RESEND_API_KEY", "OMNIDOC_FEEDBACK_EMAIL", "OMNIDOC_SMTP_HOST",
              "OMNIDOC_SMTP_USER", "OMNIDOC_SMTP_PASSWORD"):
    os.environ[_name] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
