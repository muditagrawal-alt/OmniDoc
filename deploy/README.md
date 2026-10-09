# Deploying OmniDoc

OmniDoc runs as one container: the API also serves the web app on port 8000. Models come from
free hosted APIs (keys in `.env`, see [`.env.example`](../.env.example)), so the server needs no
GPU and little memory for them; OCR, the reranker and (without Ollama or a hosted embedding
key) a small embedding model run on the CPU. Everything you upload lives in the `/data` volume.

**Before exposing it:** set `OMNIDOC_AUTH=user:a-long-random-password` in `.env`. Every visitor is
then asked for it (HTTP basic auth, so always serve over HTTPS). Without it, anyone with the
address can read and delete your documents.

## Recommended free host: Oracle Cloud "Always Free" VM

Oracle's Always Free tier includes Arm (Ampere A1) capacity of 4 cores and 24 GB of memory and
200 GB of disk that stays free, which is plenty for OmniDoc and keeps your library on a
persistent disk. Sign-up asks for a card for identity checks; Always Free resources are not
charged.

1. Create a VM: *Compute → Instances → Create*, image **Ubuntu 24.04**, shape
   **VM.Standard.A1.Flex** (e.g. 2 OCPU, 12 GB), add your SSH key.
2. Open the web ports: in the instance's subnet *Security List*, add ingress rules for TCP 80
   and 443 from `0.0.0.0/0`. On the VM:
   ```bash
   sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443 -j ACCEPT && sudo netfilter-persistent save
   ```
3. Install Docker and get the code:
   ```bash
   curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER && newgrp docker
   git clone https://github.com/<you>/OmniDoc.git && cd OmniDoc
   cp .env.example .env && nano .env    # API keys, OMNIDOC_AUTH, OMNIDOC_DOMAIN
   ```
4. A domain: use your own, or the free `<public-ip>.sslip.io` (e.g. `OMNIDOC_DOMAIN=129-146-1-2.sslip.io`).
5. Start it with HTTPS:
   ```bash
   docker compose -f docker-compose.yml -f deploy/compose.https.yml up -d --build
   ```
   Open `https://<your domain>`. Logs: `docker compose logs -f omnidoc`. Update: `git pull` and the same command.

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
| Hugging Face Spaces (Docker) | Good, not free | Docker Spaces now need a PRO plan; CPU Basic (2 vCPU, 16 GB) itself costs nothing. Set `app_port: 8000`, add keys as Secrets; storage is lost on restart unless you add persistent storage. |
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
