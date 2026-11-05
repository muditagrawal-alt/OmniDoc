# Deploying OmniDoc on ClawCloud Run (free)

ClawCloud Run gives a GitHub account older than 180 days **$5 of credit every month**, with no card.
At $4 per vCPU-month and $2 per GB-month, that covers OmniDoc's slim server: **0.5 vCPU and 1 GB of
memory, always on**, with HTTPS on a `*.clawcloudrun.com` address and a persistent disk. If the credit
ever runs out, the app pauses; nothing is charged.

The slim image (`deploy/Dockerfile.slim`) is the full app without PyTorch or Ollama: embeddings and
reranking run as small ONNX models, answers come from free hosted model APIs (or each user's own key).
CI measures it on every push: it peaks near 790 MB through an upload with OCR and a run of questions.
GitHub Actions builds and publishes it after the tests pass, as `ghcr.io/muditagrawal-alt/omnidoc:slim`.

## 1. Make the image public (once)

GitHub publishes new images as private. Open
[github.com/muditagrawal-alt?tab=packages](https://github.com/muditagrawal-alt?tab=packages) →
**omnidoc** → **Package settings** → **Change visibility** → **Public**.

## 2. Create the app

1. Sign in at [run.claw.cloud](https://run.claw.cloud) with GitHub and pick a region near your users
   (Singapore or Tokyo for India).
2. **App Launchpad** → **Create App**:

   | Setting | Value |
   |---|---|
   | Application name | `omnidoc` |
   | Image | Public, `ghcr.io/muditagrawal-alt/omnidoc:slim` |
   | Usage | Fixed, 1 replica |
   | CPU / Memory | **0.5** vCPU / **1 G** |
   | Network | Container port **8000**, **Public Access** on (HTTPS) |
   | Local Storage | Mount path **`/data`**, **2 Gi** |

3. Before creating it, copy the public address it shows, for example
   `https://abcdefgh.ap-southeast-1.clawcloudrun.com`, and add these **environment variables**:

   ```
   OMNIDOC_ACCOUNTS=1
   OMNIDOC_DEMO=1
   OMNIDOC_PUBLIC_URL=https://<your app address>
   OMNIDOC_ADMIN_EMAILS=<the e-mail address on your GitHub account>
   OMNIDOC_MODEL=nvidia:nvidia/nemotron-3-ultra-550b-a55b
   OMNIDOC_LLM_PROVIDERS=nvidia,groq,gemini,openrouter
   OMNIDOC_VISION_MODEL=gemini:gemini-3.5-flash-lite
   NVIDIA_API_KEY=<key>
   GROQ_API_KEY=<key>
   GEMINI_API_KEY=<key>
   OPENROUTER_API_KEY=<key>
   ```

   The server makes its own secret key on first start and keeps it in `/data`. Everything else has
   a sensible default (three free answers per account, then each user's own key; see `.env.example`).
4. **Deploy**. The first start takes about a minute: it indexes the demo's sample library (five
   documents about a fictional company) in the background. Open the address: the product page appears.

## 3. Turn on GitHub sign-in (optional)

Passkey sign-up and the demo work without it. To add "Continue with GitHub":

1. [github.com/settings/developers](https://github.com/settings/developers) → **New OAuth App**:
   homepage `https://<your app address>`, callback
   `https://<your app address>/api/auth/oauth/github/callback`.
2. **Generate a new client secret**, then add to the app's environment:
   `OMNIDOC_GITHUB_CLIENT_ID=<id>` and `OMNIDOC_GITHUB_CLIENT_SECRET=<secret>`, and update the app.

Sign in with GitHub once with the address in `OMNIDOC_ADMIN_EMAILS`, then add a passkey or an
authenticator app under *Account → Sign-in and security*: administrator settings need one.

## 4. Updates and backups

- **Updates:** every push to `main` that passes CI publishes a new `:slim` image. In App Launchpad,
  open the app and **Restart** (or **Update** to pin `:slim-<commit>` for a fixed version).
- **Backups:** the library is the `/data` volume. From the app's **Terminal**, `tar czf /tmp/b.tgz -C
  /data .` and download it, or keep a copy with *Account → Download everything* per account.
- **Watching:** `/api/health` reports the stores and the server's memory (`memory_mb`); add it to a
  free monitor such as UptimeRobot.

## Using your own sample documents

Copy files into `/data/demo` from the app's Terminal, set `OMNIDOC_DEMO_DIR=/data/demo`, and restart:
each file is indexed once into the shared, read-only library that guests see.
