# Security policy

## Reporting a vulnerability

Please report security issues privately, not in public issues: use GitHub's
[private vulnerability reporting](https://github.com/muditagrawal-alt/OmniDoc/security/advisories/new) for this
repository. Include what you found, how to reproduce it and what it lets someone do. You will get an answer
within a few days, and a fix or a plan for one as soon as the issue is confirmed. Please give a reasonable time
to fix the issue before disclosing it, and do not access other people's data or degrade the live service while
testing; the sample library at [omnidoc-silk.vercel.app](https://omnidoc-silk.vercel.app) is meant for that.

## Supported versions

Only the latest version on the `main` branch (and the `ghcr.io/muditagrawal-alt/omnidoc:slim` image built from
it) receives security fixes.

## What OmniDoc does to stay safe

- **Accounts are isolated.** Documents, chats, page images, tables, records and search results are scoped to
  the owning account; anything else answers *not found*. SQL written by a model runs on a read-only connection
  through an SQLite authorizer that allows a single `SELECT` over the asking account's own tables.
- **Credentials are never stored in the clear.** Passwords are scrypt hashes, session tokens are kept hashed,
  recovery codes work once, keys users save on the server are encrypted, and administrators need two-step
  sign-in.
- **Abuse is limited.** Proof of work before sign-up, guest sessions and feedback; per-address and
  per-username limits on sign-in attempts; daily limits per account; an hourly cap on outgoing e-mail.
- **The browser is locked down.** A strict Content-Security-Policy, HSTS, no framing, `nosniff`, an isolated
  opener, and an HttpOnly, SameSite=Strict cookie that only signs in document images.
- **The server is minimal.** An unprivileged container user, SSH by key only and never as root, only SSH,
  HTTP and HTTPS open, automatic security updates, no published API map and a minimal health check on hosted
  servers. Secrets live only in the server's `.env` (mode 600) and never in the repository.

## Scope

In scope: this repository and the live service at `omnidoc-silk.vercel.app` and its API. Out of scope: the
model providers, Vercel, Oracle Cloud and Resend themselves, denial of service, and findings that need
physical access to a device or a compromised account.
