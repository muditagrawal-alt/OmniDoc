#!/usr/bin/env bash
# Deploys the web app to Vercel (free Hobby plan) in front of an OmniDoc server elsewhere (e.g. the
# Oracle VM from oracle-setup.sh). Vercel serves the built app and forwards /api/* to the server,
# so the site is one origin: sign-in cookies and passkeys work as if it were one machine.
#
#   OMNIDOC_BACKEND=https://1-2-3-4.sslip.io OMNIDOC_PROXY_KEY=<from the server's .env> bash deploy/vercel.sh
#
# The forwarding address carries the server's OMNIDOC_PROXY_KEY (core/proxy.py), so vercel.json is
# written into a temporary folder and never committed. Needs the Vercel CLI, signed in (vercel login).
# Afterwards set OMNIDOC_PUBLIC_URL on the server to the address this prints and restart it.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${OMNIDOC_BACKEND:?Set OMNIDOC_BACKEND to the server address, e.g. https://1-2-3-4.sslip.io}"
: "${OMNIDOC_PROXY_KEY:?Set OMNIDOC_PROXY_KEY to the value in the server .env}"
PROJECT="${OMNIDOC_VERCEL_PROJECT:-omnidoc}"
backend="${OMNIDOC_BACKEND%/}"

curl -fsS "$backend/api/health" >/dev/null || { echo "The server does not answer at $backend/api/health" >&2; exit 1; }
curl -fsS "$backend/_via/$OMNIDOC_PROXY_KEY/api/health" >/dev/null \
  || { echo "The server does not accept that OMNIDOC_PROXY_KEY" >&2; exit 1; }

(cd frontend && npm ci --no-audit --no-fund && npm run build)

out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
cp -R frontend/dist/. "$out/"
# The demo video, played from the site itself (the README links to it).
[ -f docs/media/omnidoc-demo.mp4 ] && mkdir -p "$out/demo" && cp docs/media/omnidoc-demo.mp4 docs/media/omnidoc-demo.srt "$out/demo/" 2>/dev/null || true
OMNIDOC_BACKEND="$backend" python3 - "$out/vercel.json" deploy/vercel/vercel.template.json <<'PY'
import json, os, sys
target, template = sys.argv[1], sys.argv[2]
config = json.load(open(template))
destination = f"{os.environ['OMNIDOC_BACKEND']}/_via/{os.environ['OMNIDOC_PROXY_KEY']}/api/:path*"
for rule in config["rewrites"]:
    if rule["source"] == "/api/:path*":
        rule["destination"] = destination
# The page's inline scripts (the theme bootstrap) are allowed by their hash, taken from this build.
import base64, hashlib, re
page = open(os.path.join(os.path.dirname(target), "index.html")).read()
inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", page, re.S)
hashes = " ".join(f"'sha256-{base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()}'" for s in inline)
for rule in config["headers"]:
    for header in rule["headers"]:
        header["value"] = header["value"].replace("{INLINE_SCRIPTS}", hashes)
json.dump(config, open(target, "w"), indent=2)
PY

cd "$out"
vercel link --yes --project "$PROJECT" >/dev/null
url=$(vercel deploy --prod --yes)
echo "Deployed: $url"
echo "The production address (https://$PROJECT....vercel.app) is listed under Domains: vercel project inspect $PROJECT"
