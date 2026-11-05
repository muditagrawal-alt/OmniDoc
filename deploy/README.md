# Deploying OmniDoc

OmniDoc runs as one container: the API also serves the web app on port 8000. Models come from
free hosted APIs (keys in `.env`, see [`.env.example`](../.env.example)), so the server needs no
GPU and little memory for them; OCR, the reranker and (without Ollama or a hosted embedding
key) a small embedding model run on the CPU. Everything you upload lives in the `/data` volume.

**Before exposing it:** set `OMNIDOC_AUTH=user:a-long-random-password` in `.env`. Every visitor is
then asked for it (HTTP basic auth, so always serve over HTTPS). Without it, anyone with the
address can read and delete your documents.

## Free hosts

| Host | What you get | Guide |
|---|---|---|
| **ClawCloud Run** (no card) | $5 credit a month for GitHub accounts over 180 days old: the slim image at 0.5 vCPU and 1 GB, HTTPS, a persistent disk | [CLAWCLOUD.md](CLAWCLOUD.md) |
| Oracle Cloud Always Free | A 2 OCPU, 12 GB Arm VM with 200 GB of disk; the full image with Ollama | below |
| Your own computer | Cloudflare Tunnel for a temporary public address | below |

## Oracle Cloud "Always Free" VM

Oracle's Always Free tier includes Arm (Ampere A1) capacity of 2 OCPUs and 12 GB of memory and
200 GB of disk that stays free, which is enough for OmniDoc and keeps your library on a
persistent disk. Sign-up asks for a card for identity checks; Always Free resources are not
charged (stay on the Free Tier, do not upgrade the account).

1. Create a VM: *Compute → Instances → Create*, image **Ubuntu 24.04**, shape
   **VM.Standard.A1.Flex** with 2 OCPUs and 12 GB, boot volume up to 200 GB, and your SSH key.
   "Out of capacity" means none is free in that availability domain right now: try another one or
   try again later.
2. Open the web ports in the instance's subnet *Security List*: an ingress rule for TCP 80 and
   443 from `0.0.0.0/0`.
3. On the VM (`ssh ubuntu@<public-ip>`):
   ```bash
   git clone https://github.com/muditagrawal-alt/OmniDoc.git && cd OmniDoc
   cp .env.example .env && nano .env    # API keys and OMNIDOC_AUTH=you:a-long-random-password
   bash deploy/oracle-setup.sh
   ```
   The script installs Docker, opens the VM's own firewall for ports 80 and 443, builds the image
   (about 15 minutes on 2 Arm cores) and starts OmniDoc behind Caddy with a free HTTPS address,
   `https://<public-ip-with-dashes>.sslip.io` unless `OMNIDOC_DOMAIN` names your own domain. It
   also starts Ollama for the `nomic-embed-text` embeddings, the model the benchmarks use. Run it
   again to update to the latest code; the library is kept.

The settings the benchmarks measured (add them to `.env`):

```bash
OMNIDOC_MODEL=nvidia:nvidia/nemotron-3-ultra-550b-a55b   # answers (Super, used by the benchmarks, was retired)
OMNIDOC_LLM_PROVIDERS=nvidia,groq,gemini                 # fallbacks when one is rate-limited
OMNIDOC_VISION_MODEL=gemini:gemini-3.5-flash-lite        # figures and page reading
OLLAMA_HOST=http://ollama:11434                          # embeddings: nomic-embed-text
OLLAMA_KEEP_ALIVE=-1
OMNIDOC_LOCAL_FALLBACK=0                                 # no local chat model on the VM
```

Oracle reclaims an Always Free Arm VM that stays below 20% CPU, network *and* memory use for
seven days. OmniDoc keeps its reranker and (with `OLLAMA_KEEP_ALIVE=-1`) the embedding model in
memory, about a fifth of 12 GB; check with `free -h` if the VM sees little use.

Logs: `docker compose logs -f omnidoc`. Backups: the library is the `omnidoc_omnidoc-data` Docker
volume (`docker run --rm -v omnidoc_omnidoc-data:/data -v $PWD:/b alpine tar czf /b/omnidoc-data.tgz /data`).

## Accounts: sign-in for everyone you share it with

With `OMNIDOC_ACCOUNTS=1` every visitor signs in, and each account has its own private library,
conversations, knowledge graph and record tables. Nothing about a user is stored except a name, how
they sign in (an e-mail address for GitHub, Google or codes; only a public key for a passkey) and
their own documents and chats, all on your server: no third-party account service is needed. OmniDoc
stores no passwords; sessions last 30 days and only their hashes are kept.

**Passkeys need no setup and no e-mail.** Anyone can create an account with Face ID, Touch ID,
Windows Hello or a phone, and gets ten one-time recovery codes. Passkeys need HTTPS (Caddy provides
it) and work on the free `<ip>.sslip.io` address. Accounts can also turn on an authenticator app
(Google or Microsoft Authenticator, 1Password...) as a second step after GitHub, Google or e-mail
sign-in, see and sign out their devices, link GitHub or Google as a second way in, and download all
their data as a zip, under *Settings → Account and security*. Administrators must use a passkey or an
authenticator app before they can change server settings.

GitHub sign-in is optional, needs no e-mail service and accepts the sslip.io address (Google may
refuse it):

| Method | Free service | Setup |
|---|---|---|
| GitHub | [New OAuth App](https://github.com/settings/developers): homepage `https://<your domain>`, callback `https://<your domain>/api/auth/oauth/github/callback` | `OMNIDOC_GITHUB_CLIENT_ID` / `_SECRET` |
| Google | [Google Cloud console](https://console.cloud.google.com/apis/credentials) → OAuth client ID (Web application), redirect URI `https://<your domain>/api/auth/oauth/google/callback`; the consent screen needs only the `email` and `profile` scopes (no billing) | `OMNIDOC_GOOGLE_CLIENT_ID` / `_SECRET` |
| E-mailed six-digit code (optional; off unless SMTP is set) | Gmail (500 e-mails/day): turn on 2-Step Verification, create an [app password](https://myaccount.google.com/apppasswords), and set `OMNIDOC_SMTP_HOST=smtp.gmail.com`, `OMNIDOC_SMTP_USER`, `OMNIDOC_SMTP_PASSWORD` (the app password). Or [Brevo](https://www.brevo.com) (300/day) with its SMTP key. | `.env` |

Also set `OMNIDOC_PUBLIC_URL=https://<your domain>` and `OMNIDOC_ADMIN_EMAILS=<your address>`.
Every account gets daily limits (40 questions, 20 uploads) and a 200 MB library by default
(`OMNIDOC_DAILY_QUESTIONS`, `OMNIDOC_DAILY_UPLOADS`, `OMNIDOC_STORAGE_MB`) so that free model quotas
and the disk are shared fairly; administrators have none. `OMNIDOC_ALLOWED_EMAILS` restricts sign-in
to listed addresses or `@domains`. Users can see their usage and delete their account, with all their
data, from *Settings → Account and security*.

**A guest demo** for visitors who will not sign up: set `OMNIDOC_DEMO=1` and copy a few public
documents into the data volume's `demo` folder
(`docker compose cp ./samples/. omnidoc:/data/demo/`, then restart). They are indexed once into a
shared library. "Try the demo" on the sign-in page opens a one-day guest session that can ask,
compare, search and extract on it (8 questions by default, `OMNIDOC_GUEST_QUESTIONS`) but cannot
upload, delete or see any account.

**Abuse limits, with no third-party service.** Creating an account, opening the demo and using a
recovery code first make the browser solve a small proof-of-work puzzle (about a second for a person,
expensive for a bot at scale). Each address is limited to 240 API requests a minute and to a few
sign-up, demo and recovery attempts an hour; behind Caddy the visitor's real address is used.

With 200 GB of disk and 200 MB per account, the server holds the libraries of about 900 users;
conversations are stored compressed and take a few kilobytes per answer.

**Backups.** `oracle-setup.sh` schedules `deploy/backup.sh` every night at 03:30: a snapshot of the
library in `~/omnidoc-backups`, the last seven kept. For copies off the server, add a backup policy to
the boot volume in the Oracle console (five volume backups are free).

## Instant sharing from your own computer: Cloudflare Tunnel

No server and no account needed; your computer stays the server (it must be on).

```bash
brew install cloudflared                      # or see developers.cloudflare.com
OMNIDOC_AUTH=me:long-password python server.py   # after `npm run build` in frontend/
cloudflared tunnel --url http://localhost:8000
```

`cloudflared` prints a `https://<random>.trycloudflare.com` address. For a stable address on
your own domain, create a named tunnel in the Cloudflare dashboard (free).

## Other hosts

| Host | Fit | Notes |
| --- | --- | --- |
| Any VPS or home server with Docker | Good | `docker compose up -d` (+ `deploy/compose.https.yml` for HTTPS). 2 GB of memory is the practical minimum. |
| Hugging Face Spaces (Docker) | Good, not free | Docker and Gradio Spaces need a PRO plan (free accounts get only ZeroGPU Gradio Spaces); CPU Basic (2 vCPU, 16 GB) itself costs nothing. Set `app_port: 8000`, add keys as Secrets; storage is lost on restart unless you add persistent storage. |
| Google Cloud Run | Poor for a library | Free request quota, but the disk is temporary: uploads and indexes vanish when the container stops unless you mount a bucket. |
| Render / Koyeb / Railway free plans | Too small | 512 MB of memory is not enough for OCR, the reranker and the indexes. |

## With local models instead of APIs

`docker compose --profile local up -d` also starts Ollama; set `OLLAMA_HOST=http://ollama:11434`
in `.env` and pull the models:

```bash
docker compose exec ollama ollama pull qwen2.5:7b-instruct
docker compose exec ollama ollama pull nomic-embed-text
```

This needs a machine with about 8 GB of free memory for a 7B model.
