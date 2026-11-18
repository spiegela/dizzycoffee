#!/usr/bin/env bash
# Copy this checkout's Spinn integration to a Home Assistant over SSH, then
# check the config and restart Home Assistant. For testing a branch before it's
# released; HACS / Marketplace installs are overwritten in place.
#
# Needs SSH into the machine that holds HA's /config. On Home Assistant OS that's
# the "Terminal & SSH" or "Advanced SSH & Web Terminal" add-on, with your public
# key added and a port set (often 22).
#
#   scripts/deploy-to-ha.sh root@homeassistant.local          # port 22
#   scripts/deploy-to-ha.sh root@homeassistant.local 2222     # another port
#   NO_RESTART=1 scripts/deploy-to-ha.sh root@homeassistant.local
#
# The copy it replaces is kept in /config/.dizzycoffee/spinn.bak (outside
# custom_components, so HA doesn't try to load it). To go back:
#   ssh root@homeassistant.local 'rm -rf /config/custom_components/spinn &&
#     mv /config/.dizzycoffee/spinn.bak /config/custom_components/spinn && ha core restart'
# or redownload the integration in HACS / Marketplace.
set -euo pipefail

host="${1:?usage: $0 user@host [ssh-port]}"
port="${2:-22}"
config="${HA_CONFIG:-/config}"

here="$(cd "$(dirname "$0")/.." && pwd)"
src="$here/custom_components/spinn"
[ -f "$src/manifest.json" ] || { echo "No integration at $src" >&2; exit 1; }

version="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$src/manifest.json")"
branch="$(git -C "$here" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
commit="$(git -C "$here" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ -n "$(git -C "$here" status --porcelain -- custom_components/spinn 2>/dev/null)" ]; then
  commit="$commit+local changes"
fi
echo "Deploying spinn $version ($branch @ $commit) to $host:$config/custom_components/spinn"

# COPYFILE_DISABLE stops macOS tar adding ._ metadata files.
COPYFILE_DISABLE=1 tar -C "$here/custom_components" \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' -czf - spinn |
  ssh -p "$port" "$host" "set -e
    work='$config/.dizzycoffee'
    dest='$config/custom_components'
    mkdir -p \"\$work\" \"\$dest\"
    rm -rf \"\$work/incoming\"
    mkdir \"\$work/incoming\"
    tar -xzf - -C \"\$work/incoming\"
    test -f \"\$work/incoming/spinn/manifest.json\"
    rm -rf \"\$work/spinn.bak\"
    if [ -d \"\$dest/spinn\" ]; then mv \"\$dest/spinn\" \"\$work/spinn.bak\"; fi
    mv \"\$work/incoming/spinn\" \"\$dest/spinn\"
    rmdir \"\$work/incoming\"
    echo \"Copied. Previous version kept in \$work/spinn.bak\""

if [ -n "${NO_RESTART:-}" ]; then
  echo "Not restarting (NO_RESTART set). Restart Home Assistant to load it."
  exit 0
fi

ssh -p "$port" "$host" 'if command -v ha >/dev/null 2>&1; then
    echo "Checking the configuration…" && ha core check &&
    echo "Restarting Home Assistant…" && ha core restart && echo "Restarted."
  else
    echo "No ha CLI on this host: restart Home Assistant yourself (Settings → System → Restart)."
  fi'
echo "When it's back, hard-refresh the dashboard (the cards are versioned, so a normal reload usually works)."
