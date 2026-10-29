#!/usr/bin/env bash
# One-command setup (and update) of OmniDoc on a fresh Ubuntu 24.04 VM, e.g. Oracle Cloud's
# Always Free Ampere A1 (2 OCPUs, 12 GB). Run it as the default user from the repository folder:
#
#   git clone https://github.com/muditagrawal-alt/OmniDoc.git && cd OmniDoc
#   cp .env.example .env && nano .env      # API keys, OMNIDOC_AUTH, OMNIDOC_DOMAIN
#   bash deploy/oracle-setup.sh
#
# It installs Docker, opens ports 80 and 443 in the VM's own firewall (Oracle's Ubuntu images
# block them even when the subnet allows them), builds the image and starts OmniDoc behind Caddy
# (automatic HTTPS) with Ollama serving the nomic-embed-text embeddings. Running it again pulls
# the latest code and rebuilds; the library in the omnidoc-data volume is kept.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "Create .env first (cp .env.example .env): API keys, OMNIDOC_AUTH and OMNIDOC_DOMAIN." >&2
  exit 1
fi
domain=$(grep -E '^OMNIDOC_DOMAIN=' .env | cut -d= -f2- || true)
if [ -z "$domain" ]; then
  ip=$(curl -fs https://api.ipify.org || true)
  [ -n "$ip" ] || { echo "Set OMNIDOC_DOMAIN in .env (your domain, or <ip-with-dashes>.sslip.io)." >&2; exit 1; }
  domain="${ip//./-}.sslip.io"
  echo "OMNIDOC_DOMAIN=$domain" >> .env
  echo "Using the free domain $domain"
fi
grep -qE '^OMNIDOC_AUTH=.+:.+' .env || echo "Warning: OMNIDOC_AUTH is not set: anyone with the address can use and delete your documents." >&2

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
  sudo apt-get install -y -qq iptables-persistent >/dev/null 2>&1 || true
  sudo netfilter-persistent save >/dev/null 2>&1 || true
fi

# Latest code (when this is a git checkout).
[ -d .git ] && git pull --ff-only || true

compose="$DOCKER compose -f docker-compose.yml -f deploy/compose.https.yml --profile local"
$compose up -d --build
# The embedding model (about 270 MB, pulled once into the ollama-models volume).
for i in $(seq 1 30); do $compose exec -T ollama ollama list >/dev/null 2>&1 && break; sleep 2; done
$compose exec -T ollama ollama pull nomic-embed-text >/dev/null
$DOCKER image prune -f >/dev/null
# A nightly snapshot of the library (deploy/backup.sh keeps the last 7).
( crontab -l 2>/dev/null | grep -v "# omnidoc-backup" ; echo "30 3 * * * bash $PWD/deploy/backup.sh >> $HOME/omnidoc-backup.log 2>&1 # omnidoc-backup" ) | crontab -

echo "Waiting for OmniDoc to start..."
for i in $(seq 1 90); do
  if $compose exec -T omnidoc curl -fs http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "OmniDoc is running: https://$domain"
    exit 0
  fi
  sleep 5
done
echo "OmniDoc did not answer yet; see: $compose logs -f omnidoc" >&2
exit 1
