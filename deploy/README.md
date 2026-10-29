# Deploying OmniDoc

OmniDoc runs as one container: the API also serves the web app on port 8000. Models come from
free hosted APIs (keys in `.env`, see [`.env.example`](../.env.example)), so the server needs no
GPU and little memory for them; OCR, the reranker and (without Ollama or a hosted embedding
key) a small embedding model run on the CPU. Everything you upload lives in the `/data` volume.

**Before exposing it:** set `OMNIDOC_AUTH=user:a-long-random-password` in `.env`. Every visitor is
then asked for it (HTTP basic auth, so always serve over HTTPS). Without it, anyone with the
address can read and delete your documents.

## Recommended free host: Oracle Cloud "Always Free" VM

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
OMNIDOC_MODEL=nvidia:nvidia/nemotron-3-super-120b-a12b   # answers
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
