# OmniDoc product plan

The plan for turning OmniDoc into an enterprise-grade SaaS product that runs entirely on free
resources. It records what is done, what comes next and in which order, which free service each
part uses, and the decisions still open. Update it as items ship.

**Constraints:** no paid services and no billing, no domain (the free `<ip>.sslip.io` address), and
no e-mail sending of any kind (decided 2026-10-29). Sign-in, second factors and notifications therefore
use methods that need neither: GitHub (and Google if it accepts the address), passkeys, authenticator
apps, in-app notices and browser push. Every item below names its free resource and the limit that
matters. Where a free tier runs out, the plan says what happens (a lower limit, a queue,
or bring-your-own-key), never "upgrade".

## Status at a glance

| Area | State |
|---|---|
| Document intelligence (cited answers, viewer, extraction, compare, privacy, graph, multilingual) | Done |
| Benchmarks (FinanceBench, MMLongBench-Doc, BEIR, RAGAS) | Done; full MMLongBench run paused at 2 of 10 batches |
| Web app redesign (enterprise look, IBM Plex, one accent) | Done |
| README, demo video, GIFs, screenshots | Done |
| Accounts: Google and GitHub sign-in (e-mailed codes built but switched off: no e-mail sending); private libraries; limits; account deletion | Done (code), not yet live |
| Conversation memory (rolling summary of older turns) | Done |
| One-command deployment, HTTPS, nightly backups, security headers | Done (code), not yet live |
| Everything in the phases below | Planned |

## Free stack

| Need | Free resource | Limit that matters |
|---|---|---|
| Server | Oracle Cloud Always Free, Ampere A1 VM | 2 OCPUs, 12 GB, 200 GB disk; reclaimed if idle (<20% CPU, network and memory) for 7 days |
| HTTPS and address | Caddy + `<ip>.sslip.io` | No custom name until a domain is added |
| Domain | None: `<ip>.sslip.io` (decided). If a nicer name is ever wanted at no cost: an is-a.dev subdomain (free, via a GitHub pull request) | Without a domain, Cloudflare's proxy and branded e-mail are not available |
| Edge protection | Caddy plus rate limits in the app (Cloudflare's proxy needs a domain) | Per-IP and per-account limits enforced by OmniDoc |
| Bot protection | Cloudflare Turnstile (a free Cloudflare account, no domain on Cloudflare) | Verify that it accepts the sslip.io hostname; otherwise a self-hosted proof-of-work challenge |
| Sign-in without e-mail | GitHub OAuth; Google OAuth if it accepts the address; passkeys (WebAuthn, `py_webauthn`) | Passkeys need HTTPS, which Caddy provides |
| Second factor | Authenticator apps (TOTP, `pyotp`) with recovery codes; passkeys | Free; no messages sent |
| Notifications (security, updates) | In-app notices, browser push (Web Push with the server's own VAPID keys, `pywebpush`), an RSS feed, GitHub Releases | Push needs the user's permission and HTTPS |
| E-mail | Not used (decided) | — |
| Answer models | Gemini, Groq, NVIDIA NIM, OpenRouter free tiers; users' own keys (BYOK) | Per-provider daily and per-minute limits |
| In-browser models | WebLLM (MLC) on WebGPU | Chrome/Edge desktop; 1–4 GB download per model |
| Landing page hosting | Cloudflare Pages or GitHub Pages | Free; Cloudflare Pages allows 500 builds/month |
| CI/CD | GitHub Actions (public repository) | Free minutes for public repositories |
| Container registry | GitHub Container Registry | Free for public images |
| Security scanning | Dependabot, CodeQL, secret scanning (public repository) | Free |
| Uptime monitoring and status page | UptimeRobot (50 monitors, 5-minute checks); Upptime on GitHub Pages | Free |
| Error tracking | Sentry Developer plan, or self-hosted GlitchTip | Sentry ~5,000 errors/month |
| Product analytics | Umami, self-hosted on the VM | Free; privacy-friendly, no cookies |
| Off-site backups | Cloudflare R2 (10 GB) or Backblaze B2 (10 GB), encrypted | Free storage tier |
| Malware scanning of uploads | ClamAV in its own container | Free; about 1 GB of memory |
| Release notes | release-please GitHub Action (from conventional commits) | Free |

## Phase 0: go live

1. Oracle VM, `oracle-setup.sh`, HTTPS on `<ip>.sslip.io`.
2. Accounts on: a GitHub OAuth app, and a Google OAuth client if Google accepts the sslip.io address.
   Passkeys (Phase 1) let people without GitHub or Google sign up: an account is a display name plus a
   passkey, with recovery codes shown once at sign-up.
3. UptimeRobot on `/api/health`; status page.
4. Off-site encrypted backup (restic to R2 or B2) next to the nightly local snapshot; one restore drill.
5. CI: tests, lint and build on every push; Docker image to GHCR; deploy to the VM over SSH on `main`.

Done when: the public address works, sign-in works three ways, a broken commit cannot deploy, and a
backup has been restored once.

## Phase 1: security for users and for the operator

For users:
- **Passkeys** (WebAuthn, `py_webauthn`): sign up and sign in with Face ID, Touch ID, Windows Hello or
  a phone, with no password and no e-mail. Ten one-time recovery codes are shown at sign-up; an account
  can also link GitHub or Google as a second way in.
- **Two-step sign-in** without e-mail: a code from an authenticator app (TOTP, `pyotp`: Google
  Authenticator, Microsoft Authenticator, 1Password...) after GitHub or Google sign-in, or a passkey.
  Optional per user, required for admins; recovery codes as the fallback.
- **Sessions and devices.** A list of signed-in devices (browser, approximate place, last use) with
  "sign out" per device and "sign out everywhere"; a notice in the app (and a browser push, if allowed)
  on each new-device sign-in.
- **Data rights.** Export everything (documents, chats, records) as a zip; deletion already exists.
- **Encryption at rest** for each user's chats (key derived per user from the server secret), and
  for stored API keys (see Phase 2).

For the operator:
- Turnstile on sign-up and sign-in (or a proof-of-work challenge if it refuses the sslip.io name).
- Rate limits per IP as well as per address (uvicorn behind Caddy with forwarded headers trusted
  only from Caddy).
- ClamAV scan of every upload; parsers in a sandboxed worker with memory and time limits.
- Content Security Policy for the app; dependency, code and secret scanning in CI.
- Audit log of sign-ins, admin actions, deletions and key changes, kept 90 days.
- Admin console: users, usage, limits, suspend or delete, announcements.
- Fail2ban or CrowdSec on the VM's SSH; SSH by key only; automatic security updates.

## Phase 2: free trial, then bring your own key

- Each new account gets a small number of answers on the server's keys (the plan: 5–7; set by
  `OMNIDOC_TRIAL_ANSWERS`). The account dialog shows what is left.
- After that, the user adds their own key for any supported provider (Gemini, Groq, NVIDIA,
  OpenRouter, Mistral). Each sign-up link is shown with its free tier. The key is checked with one
  small request before it is saved.
- Two ways to keep a key, the user's choice:
  - **On this device only:** kept in the browser and sent with each question over HTTPS, never
    stored on the server.
  - **Encrypted on the server:** AES-GCM with a key that is not stored next to the data; usable from
    any device.
- The server never logs keys. Background work (summaries, graph) for a BYOK user also uses that
  user's key.
- Admins can grant more trial answers to an account.

## Phase 3: privacy modes

- **Chats on this device only.** Conversations are kept in the browser (IndexedDB) and the server
  keeps no copy. Questions and their evidence still pass through the server to be answered.
  Optional: an encrypted export file to move chats between devices.
- **Answers in the browser (WebLLM).** On a WebGPU browser the user can download a small model
  (for example Qwen 2.5 3B or Llama 3.2 3B, 2–3 GB, cached) and the answer is written in the
  browser. The server still finds the evidence; only the question and evidence stay out of
  third-party APIs. Answers are slower and less accurate than the hosted models, and the interface
  says so.
- **Fully local.** The existing self-hosted mode with Ollama: nothing leaves the machine.

A privacy panel states plainly, for the current settings, what leaves the device and where it goes.

## Phase 4: product website

- A separate landing site (React + Vite, Framer Motion, GSAP ScrollTrigger, React Three Fiber),
  hosted free on Cloudflare Pages or GitHub Pages and linking to the app.
- Direction: the big-tech product page (Apple, Google, Stripe, Linear, Framer) and Awwwards
  winners, in the app's own identity (IBM Plex, one blue, cool greys):
  - a 3D hero: a document whose pages fan out into the knowledge globe, with citations as light;
  - scroll-driven sections, each showing one capability with the real interface;
  - a live demo strip that plays the walkthrough;
  - benchmark numbers with their methodology.
- Budgets: Lighthouse performance 90+ on mobile, `prefers-reduced-motion` respected, no layout shift,
  3D loaded only when visible and replaced by a still image on weak devices.
- Pages: home, features, security and privacy, benchmarks, changelog, docs, status, pricing (free
  plus BYOK), terms, privacy policy, contact.
- **Support assistant** on the site: OmniDoc answering from its own documentation (README, deploy
  guide, FAQ, changelog) with citations, rate-limited per visitor and protected by Turnstile.

## Phase 5: automatic update notices (no e-mail)

- Commits already follow conventional subjects. release-please turns them into versioned releases
  and a `CHANGELOG.md` with no manual writing.
- On each release, a GitHub Action calls the server's `/api/admin/announce` with the notes. The
  server writes a short readable summary with a model and:
  - shows it in the app as "What's new" (a dot on the menu until read);
  - sends a browser push notification to users who allowed them (Web Push with the server's own
    VAPID keys: free, no third-party service, works on the sslip.io HTTPS address);
  - publishes it in an RSS feed, and on GitHub Releases, which anyone can watch.
- Users choose in the account dialog: push for every release, a weekly digest, or in-app only.

## Phase 6: enterprise features

- Organizations and teams: shared workspaces, roles (owner, admin, member, viewer), invitations by
  single-use, expiring links (no e-mail), per-organization limits.
- Single sign-on for organizations: OpenID Connect (any provider) first, then SAML (`python3-saml`).
- API keys per user, scoped and revocable; public REST API documentation and webhooks.
- Usage reporting per organization; data retention settings (delete chats after N days).
- Legal: terms of service, privacy policy, data processing terms, subprocessor list (the model
  providers), cookie notice if analytics ever set cookies (Umami does not).

## Phase 7: quality and growth

- Onboarding: a sample library and a short guided tour on first sign-in.
- Feedback: thumbs up or down on answers with an optional comment; collected into an evaluation set.
- Progressive web app: installable, share-to-OmniDoc from a phone, camera capture of receipts.
- Accessibility to WCAG 2.1 AA, and the interface itself in Hindi and other Indian languages.
- Focused page reading and repeated counting for chart and table questions: the largest remaining
  source of errors on MMLongBench-Doc.

## Decisions still open

- Decided 2026-10-29: no domain (`sslip.io`) and no e-mail sending.
- The trial size (5, 6 or 7 answers) and whether background work counts against it.
- Whether chats default to "on this device only" or to the server.
- The landing page: coded in this repository (full control, free hosting) or built in Framer (fast
  to design; the free plan shows a Framer badge on a `framer.website` address).

## Risks to watch

- Free model tiers change without notice: NVIDIA retired Nemotron 3 Super in October 2026. Keep
  several providers configured and BYOK available.
- Without e-mail there is no automatic account recovery: users must keep their recovery codes or
  link a second sign-in method. The sign-up flow insists on one of the two.
- Google may refuse an sslip.io redirect address; GitHub sign-in and passkeys then cover everyone.
- Oracle reclaims idle Always Free VMs; keeping the models loaded keeps memory above the threshold,
  and the uptime monitor provides light traffic.
- One VM is a single point of failure: off-site backups and a written restore procedure matter
  more than any feature.
