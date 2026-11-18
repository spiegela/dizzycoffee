#!/usr/bin/env bash
# Deploy this checkout's Spinn integration to a Home Assistant, to test a branch
# before it's released. Two ways in:
#
#   Kubernetes (kubectl exec into the Home Assistant pod):
#     scripts/deploy-to-ha.sh k8s [-n NAMESPACE] [--context CONTEXT] [-c CONTAINER]
#                                 [-l SELECTOR | POD | deploy/NAME | statefulset/NAME]
#                                 [--restart api|pod|none]
#   SSH (e.g. the Terminal & SSH add-on on Home Assistant OS):
#     scripts/deploy-to-ha.sh ssh root@homeassistant.local [PORT]
#     (the older form without "ssh" still works)
#
# Both copy custom_components/spinn/ to <config>/custom_components/spinn, keep the
# copy they replace in <config>/.dizzycoffee/spinn.bak (outside custom_components,
# so Home Assistant doesn't load it), then restart Home Assistant.
#
# Kubernetes target: a pod, deploy/NAME or statefulset/NAME, or -l SELECTOR. With
# none, it looks for a running pod labelled app.kubernetes.io/name=home-assistant.
#
# Kubernetes restart (--restart; default "api" when HA_URL and HA_TOKEN are set,
# otherwise "pod"):
#   api   Restart Home Assistant in place through its API. Checks the config first,
#         waits for it to come back, and reports whether the Spinn entry loaded.
#         Needs HA_URL (how you reach it, e.g. https://ha.example.com) and HA_TOKEN
#         (a long-lived access token: your profile → Security). The pod is left alone.
#   pod   Delete the pod so its Deployment / StatefulSet replaces it, wait for the
#         new pod to be Ready, and check the files survived. They won't if an init
#         container or the image resets custom_components at startup; use api then.
#   none  Copy only (same as NO_RESTART=1).
#
# Environment: HA_CONFIG (config dir on the target, default /config), NO_RESTART=1,
#              HA_URL, HA_TOKEN. kubectl uses your usual kubeconfig / KUBECONFIG.
# With HA_URL set (token or not), it finishes by checking that Home Assistant
# serves the card version from your checkout.
#
# To go back: redownload the integration in HACS / Marketplace, or move
# <config>/.dizzycoffee/spinn.bak back to <config>/custom_components/spinn and restart.
#
# Written for bash 3.2 too (macOS), hence ${arr[@]+"${arr[@]}"} for maybe-empty arrays.
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }
usage() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"; }

here="$(cd "$(dirname "$0")/.." && pwd)"
src="$here/custom_components/spinn"
config="${HA_CONFIG:-/config}"
[ -f "$src/manifest.json" ] || die "no integration at $src"

# --------------------------------------------------------------------- what
version="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$src/manifest.json")"
branch="$(git -C "$here" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
commit="$(git -C "$here" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ -n "$(git -C "$here" status --porcelain -- custom_components/spinn 2>/dev/null)" ]; then
  commit="$commit+local-changes"
fi
# Written into the deployed copy as .deployed-from, so a restart can be checked.
deploy_label="$(printf 'spinn %s %s@%s %s' "$version" "$branch" "$commit" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" |
  LC_ALL=C tr -cd 'A-Za-z0-9._/@:+ -')"

make_tarball() {
  # COPYFILE_DISABLE stops macOS tar adding ._ metadata files.
  COPYFILE_DISABLE=1 tar -C "$here/custom_components" \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' -czf - spinn
}

# Shell run on the target (POSIX sh / busybox): unpack stdin, swap the folder in.
install_script() {
  cat <<EOS
set -e
work='$config/.dizzycoffee'
dest='$config/custom_components'
mkdir -p "\$work" "\$dest"
rm -rf "\$work/incoming"
mkdir "\$work/incoming"
tar -xzf - -C "\$work/incoming"
test -f "\$work/incoming/spinn/manifest.json"
printf '%s\n' '$deploy_label' > "\$work/incoming/spinn/.deployed-from"
rm -rf "\$work/spinn.bak"
if [ -d "\$dest/spinn" ]; then mv "\$dest/spinn" "\$work/spinn.bak"; fi
mv "\$work/incoming/spinn" "\$dest/spinn"
rmdir "\$work/incoming"
echo "Copied. Previous version kept in \$work/spinn.bak"
EOS
}

# ---------------------------------------------------- Home Assistant's API
api() {  # METHOD PATH [JSON]: prints the body; curl's exit code (22 = HTTP error)
  # A config check can take a while on a big config; polls pass API_MAX_TIME=10.
  local args=(-fsS --max-time "${API_MAX_TIME:-120}" -X "$1" -H @- -H 'Content-Type: application/json')
  [ -n "${3:-}" ] && args+=(--data "$3")
  # The token goes in on stdin, not the command line.
  curl "${args[@]}" "${HA_URL%/}$2" <<EOF
Authorization: Bearer $HA_TOKEN
EOF
}

restart_via_api() {
  { [ -n "${HA_URL:-}" ] && [ -n "${HA_TOKEN:-}" ]; } || die "--restart api needs HA_URL and HA_TOKEN"
  command -v curl >/dev/null || die "--restart api needs curl"
  command -v python3 >/dev/null || die "--restart api needs python3"

  echo "Checking the configuration…"
  local check
  check="$(api POST /api/config/core/check_config)" || die "couldn't use $HA_URL/api (check HA_URL and HA_TOKEN; the token must be an admin's)"
  if ! printf '%s' "$check" | python3 -c '
import json, sys
try:
    ok = json.load(sys.stdin).get("result") == "valid"
except Exception:
    ok = False
sys.exit(0 if ok else 1)'; then
    echo "The config check failed, so Home Assistant wasn't restarted:" >&2
    printf '%s\n' "$check" >&2
    exit 1
  fi

  echo "Restarting Home Assistant…"
  local rc=0
  api POST /api/services/homeassistant/restart '{}' >/dev/null 2>&1 || rc=$?
  # 22 = Home Assistant answered with an error (e.g. it refused to restart).
  # Anything else is the connection dropping as it shuts down, which is fine.
  [ "$rc" -ne 22 ] || die "Home Assistant refused to restart; see its logs"

  local went_down=""
  for _ in $(seq 1 60); do
    if ! API_MAX_TIME=10 api GET /api/ >/dev/null 2>&1; then went_down=1; break; fi
    sleep 1
  done
  [ -n "$went_down" ] || echo "warning: didn't see Home Assistant go down; it may not have restarted" >&2

  local state=""
  for _ in $(seq 1 150); do
    state="$(API_MAX_TIME=10 api GET /api/config 2>/dev/null |
      python3 -c 'import json,sys; print(json.load(sys.stdin).get("state", "RUNNING"))' 2>/dev/null || true)"
    [ "$state" = RUNNING ] && break
    sleep 2
  done
  [ "$state" = RUNNING ] || die "Home Assistant didn't come back within 5 minutes; check its logs"
  echo "Home Assistant is running again."

  local entries
  if entries="$(api GET '/api/config/config_entries/entry?domain=spinn' 2>/dev/null)"; then
    printf '%s' "$entries" | python3 -c '
import json, sys
entries = [e for e in json.load(sys.stdin) if e.get("domain") == "spinn"]
for e in entries:
    print("Spinn entry %r: %s" % (e.get("title"), e.get("state")))
if not entries:
    print("No Spinn entry is set up yet.")
elif any(e.get("state") != "loaded" for e in entries):
    print("Not loaded yet: check Settings > Devices & services, and the logs.")
' || true
  fi
}

# The cards are served without a login, so this needs HA_URL but no token.
check_cards() {
  if [ -z "${HA_URL:-}" ]; then
    echo "Tip: set HA_URL and the script checks which card version Home Assistant serves."
    return 0
  fi
  command -v curl >/dev/null || return 0
  local want got=""
  want="$(sed -n 's/^CARD_VERSION = "\(.*\)"/\1/p' "$src/const.py")"
  # Home Assistant may still be starting integrations; give it up to 2 minutes.
  for _ in $(seq 1 30); do
    got="$(curl -fsS --max-time 10 "${HA_URL%/}/spinn_cards/spinn-card.js" 2>/dev/null |
      sed -n 's/^const CARD_VERSION = "\(.*\)";/\1/p' | head -n 1)"
    [ -n "$got" ] && break
    sleep 4
  done
  if [ "$got" = "$want" ]; then
    echo "Home Assistant is serving cards v$got. Reload the dashboard page to pick them up."
  else
    echo "warning: expected cards v$want but Home Assistant serves ${got:-nothing} at /spinn_cards/spinn-card.js; it may not have restarted with the new files." >&2
  fi
}

# ------------------------------------------------------------------ SSH mode
deploy_ssh() {
  local host="${1:?usage: $0 ssh user@host [port]}" port="${2:-22}"
  echo "Deploying ${deploy_label% *} to $host:$config/custom_components/spinn"
  make_tarball | ssh -p "$port" "$host" "$(install_script)"

  if [ -n "${NO_RESTART:-}" ]; then
    echo "Not restarting (NO_RESTART set). Restart Home Assistant to load it."
    return
  fi
  ssh -p "$port" "$host" 'if command -v ha >/dev/null 2>&1; then
      echo "Checking the configuration…" && ha core check &&
      echo "Restarting Home Assistant…" && ha core restart && echo "Restarted."
    else
      echo "No ha CLI on this host: restart Home Assistant yourself (Settings → System → Restart)."
    fi'
  check_cards
}

# ----------------------------------------------------------- Kubernetes mode
kube=()        # global kubectl flags (-n, --context)
container=()   # -c CONTAINER for exec
pod=""

k() { kubectl ${kube[@]+"${kube[@]}"} "$@"; }
kexec() { k exec -i "$pod" ${container[@]+"${container[@]}"} -- "$@"; }

# KIND/NAME -> its pod selector as "k=v,k=v" (from .spec.selector.matchLabels).
selector_of() {
  local sel
  # shellcheck disable=SC2016  # a go-template for kubectl, not shell
  sel="$(k get "$1" -o go-template='{{range $k, $v := .spec.selector.matchLabels}}{{$k}}={{$v}},{{end}}')" || return 1
  printf '%s' "${sel%,}"
}

first_pod() {  # SELECTOR [extra kubectl args]: first matching pod name, or nothing
  local sel="$1"; shift
  k get pods -l "$sel" "$@" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
}

restart_pod() {
  local owner kind name sel new
  owner="$(k get pod "$pod" -o jsonpath='{.metadata.ownerReferences[0].kind}/{.metadata.ownerReferences[0].name}')"
  case "$owner" in
    ReplicaSet/?*|StatefulSet/?*) ;;
    *) die "pod $pod isn't run by a Deployment or StatefulSet, so deleting it wouldn't bring it back. Use --restart api, or restart Home Assistant yourself." ;;
  esac
  kind="$(printf '%s' "${owner%%/*}" | tr '[:upper:]' '[:lower:]')"
  name="${owner#*/}"
  sel="$(selector_of "$kind/$name")" && [ -n "$sel" ] || die "couldn't read the pod selector of $owner"

  echo "Restarting: deleting pod $pod so $owner replaces it…"
  k delete pod "$pod" --wait=true >/dev/null
  new=""
  for _ in $(seq 1 60); do
    # Not Failed/Succeeded: skips evicted leftovers that match the selector.
    new="$(first_pod "$sel" --field-selector='status.phase!=Failed,status.phase!=Succeeded')"
    [ -n "$new" ] && break
    sleep 2
  done
  [ -n "$new" ] || die "no replacement pod appeared for $owner"
  echo "Waiting for pod $new to be Ready…"
  k wait --for=condition=Ready "pod/$new" --timeout=300s >/dev/null || die "pod $new isn't Ready after 5 minutes; check its logs"
  pod="$new"

  local found
  found="$(kexec cat "$config/custom_components/spinn/.deployed-from" 2>/dev/null || true)"
  if [ "$found" != "$deploy_label" ]; then
    die "the new pod doesn't have the deployed files (found: ${found:-nothing}). Something resets custom_components at startup (an init container or the image); deploy again with HA_URL and HA_TOKEN set (--restart api)."
  fi
  echo "Home Assistant restarted with the new files (pod $pod)."
}

deploy_k8s() {
  local target="" selector="" restart=""
  while [ $# -gt 0 ]; do
    case "$1" in
      -n|--namespace) kube+=(--namespace "${2:?$1 needs a value}"); shift 2 ;;
      --context) kube+=(--context "${2:?$1 needs a value}"); shift 2 ;;
      -c|--container) container=(-c "${2:?$1 needs a value}"); shift 2 ;;
      -l|--selector) selector="${2:?$1 needs a value}"; shift 2 ;;
      --restart) restart="${2:?$1 needs api, pod or none}"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      -*) die "unknown option $1 (see --help)" ;;
      *) [ -z "$target" ] || die "more than one target: $target, $1"; target="$1"; shift ;;
    esac
  done
  command -v kubectl >/dev/null || die "kubectl isn't on your PATH"
  [ -z "$target" ] || [ -z "$selector" ] || die "give a target or -l, not both"

  if [ -z "$restart" ]; then
    if [ -n "${NO_RESTART:-}" ]; then restart=none
    elif [ -n "${HA_URL:-}" ] && [ -n "${HA_TOKEN:-}" ]; then restart=api
    else restart=pod
    fi
  fi
  case "$restart" in api|pod|none) ;; *) die "--restart must be api, pod or none" ;; esac
  if [ "$restart" = api ]; then
    { [ -n "${HA_URL:-}" ] && [ -n "${HA_TOKEN:-}" ]; } || die "--restart api needs HA_URL and HA_TOKEN"
  fi

  case "$target" in
    "") selector="${selector:-app.kubernetes.io/name=home-assistant}" ;;
    pod/*|pods/*) pod="${target#*/}" ;;
    deploy/*|deployment/*|deployments/*|statefulset/*|statefulsets/*|sts/*)
      selector="$(selector_of "$target")" && [ -n "$selector" ] || die "couldn't read the pod selector of $target" ;;
    */*) die "unsupported target $target: use a pod name, deploy/NAME or statefulset/NAME" ;;
    *) pod="$target" ;;
  esac
  if [ -z "$pod" ]; then
    pod="$(first_pod "$selector" --field-selector=status.phase=Running)"
    [ -n "$pod" ] || die "no running pod matches -l $selector (pass -n NAMESPACE, a pod name, or deploy/NAME)"
  fi

  echo "Deploying ${deploy_label% *} to pod $pod:$config/custom_components/spinn"
  make_tarball | kexec sh -c "$(install_script)"

  case "$restart" in
    none) echo "Not restarting. Restart Home Assistant to load it." ;;
    api) restart_via_api; check_cards ;;
    pod) restart_pod; check_cards ;;
  esac
}

# ---------------------------------------------------------------------- main
case "${1:-}" in
  k8s|kubectl|kube) shift; deploy_k8s "$@" ;;
  ssh) shift; deploy_ssh "$@" ;;
  ""|-h|--help) usage ;;
  -*) die "unknown option $1 (see --help)" ;;
  *) deploy_ssh "$@" ;;  # older form: scripts/deploy-to-ha.sh user@host [port]
esac
echo "Done. If a dashboard still shows the old cards, reload the page (in the companion app, reset its frontend cache)."
