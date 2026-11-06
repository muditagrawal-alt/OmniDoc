#!/usr/bin/env bash
# One-command setup (and update) of a hosted OmniDoc on a fresh Ubuntu 24.04 VM, e.g. Oracle Cloud's
# Always Free Ampere A1 (1 OCPU and 6 GB is plenty). Run it as the default user from the repository:
#
#   git clone https://github.com/muditagrawal-alt/OmniDoc.git && cd OmniDoc
#   cp .env.example .env && nano .env      # free model API keys (see deploy/README.md)
#   bash deploy/oracle-setup.sh
#
# It installs Docker, opens ports 80 and 443 in the VM's own firewall (Oracle's Ubuntu images block
# them even when the subnet allows them), turns on accounts and the demo, makes the secret the
# Vercel front end forwards /api with (OMNIDOC_PROXY_KEY), and starts the slim image from GitHub's
# registry behind Caddy (automatic HTTPS on <ip-with-dashes>.sslip.io unless OMNIDOC_DOMAIN is set).
# Running it again pulls the latest image; the library in the omnidoc_omnidoc-data volume is kept.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "Create .env first (cp .env.example .env) with at least one free model API key." >&2
  exit 1
fi

# Sets KEY=value in .env unless .env already sets it.
default() {
  grep -qE "^$1=" .env || { echo "$1=$2" >> .env; echo "  .env: $1 set"; }
}
value() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

domain=$(value OMNIDOC_DOMAIN)
if [ -z "$domain" ]; then
  ip=$(curl -fs https://api.ipify.org || true)
  [ -n "$ip" ] || { echo "Set OMNIDOC_DOMAIN in .env (your domain, or <ip-with-dashes>.sslip.io)." >&2; exit 1; }
  domain="${ip//./-}.sslip.io"
  default OMNIDOC_DOMAIN "$domain"
fi
default OMNIDOC_ACCOUNTS 1
default OMNIDOC_DEMO 1
default OMNIDOC_PROXY_KEY "$(openssl rand -hex 24)"
# SMTP, when set, is for the operator's own notices (feedback): no e-mailed sign-in codes to visitors.
default OMNIDOC_EMAIL_SIGNIN 0
# The address people open: the Vercel front end when there is one (deploy/vercel.sh), else this server.
default OMNIDOC_PUBLIC_URL "https://$domain"

# Docker.
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

# The VM's own firewall: let the web ports through (once).
if sudo iptables -C INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT 2>/dev/null; then :; else
  sudo iptables -I INPUT 5 -p tcp -m multiport --dports 80,443 -j ACCEPT
  sudo iptables -I INPUT 5 -p udp --dport 443 -j ACCEPT
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iptables-persistent >/dev/null 2>&1 || true
  sudo netfilter-persistent save >/dev/null 2>&1 || true
fi

# Latest scripts (when this is a git checkout), then the latest image.
[ -d .git ] && git pull --ff-only || true
compose="$DOCKER compose --env-file .env -f deploy/compose.oracle.yml"
$compose pull -q
$compose up -d --remove-orphans
$DOCKER image prune -f >/dev/null

# A nightly snapshot of the library (deploy/backup.sh keeps the last 7).
# (No crontab yet, or nothing left after the filter, is fine: hence the "|| true"s under set -e.)
( { crontab -l 2>/dev/null || true; } | { grep -v "# omnidoc-backup" || true; }
  echo "30 3 * * * OMNIDOC_COMPOSE=deploy/compose.oracle.yml bash $PWD/deploy/backup.sh >> $HOME/omnidoc-backup.log 2>&1 # omnidoc-backup" ) | crontab -

echo "Waiting for OmniDoc to start..."
for i in $(seq 1 60); do
  if $compose exec -T omnidoc curl -fs http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "OmniDoc is running on https://$domain"
    echo "People open: $(value OMNIDOC_PUBLIC_URL)"
    echo "The administrator's setup code is in the log: $compose logs omnidoc | grep -i 'administer this server'"
    exit 0
  fi
  sleep 5
done
echo "OmniDoc did not answer yet; see: $compose logs -f omnidoc" >&2
exit 1
