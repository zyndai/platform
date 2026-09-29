#!/usr/bin/env bash
# Server-side deploy for the single box. Runs as `ubuntu` inside the checkout
# (/home/ubuntu/zynd-platform). Called by .github/workflows/deploy-single-box.yml
# over SSH as a forced command (see infra/single-box/README.md, "CI/CD"), or by
# hand:
#
#   infra/single-box/deploy.sh                 # deploy the latest origin/main
#   infra/single-box/deploy.sh <sha>           # roll to a commit reachable from main
#   infra/single-box/deploy.sh --plan          # show what would change, touch nothing
#   infra/single-box/deploy.sh --force-all     # redeploy every service
#
# Arguments come from $SSH_ORIGINAL_COMMAND when run as the forced command.
#
# What it does: moves the checkout to the target commit, works out which
# services' files changed since the previous commit, rebuilds/restarts only
# those, then health-checks them. A failed web build restores the previous
# .next and restarts nothing, so the old version keeps serving. It never
# applies database migrations (packages/db is applied by a person) and never
# touches Caddy or DNS.
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

REPO="${ZYND_ROOT:-/home/ubuntu/zynd-platform}"
BOX="${ZYND_BOX:-/home/ubuntu/.zynd-box}"
BRANCH=main

log() { printf '[deploy %s] %s\n' "$(date -u +%T)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

cd "$REPO"

# ── Stage 1: parse args, take the lock, move the checkout, re-exec ────────
# Re-exec so the (possibly just-updated) deploy.sh is what does the real work,
# instead of bash reading a file that git rewrote under it.
if [[ -z "${ZYND_DEPLOY_STAGE:-}" ]]; then
  mkdir -p "$BOX"
  exec 9>"$BOX/deploy.lock"
  flock -n 9 || die "another deploy is already running"

  read -r -a words <<<"${SSH_ORIGINAL_COMMAND:-$*}"
  ref=""; PLAN_ONLY=0; FORCE_ALL=0
  for w in "${words[@]:-}"; do
    case "$w" in
      "") ;;
      --plan) PLAN_ONLY=1 ;;
      --force-all) FORCE_ALL=1 ;;
      main) ref="" ;;
      *) [[ "$w" =~ ^[0-9a-f]{7,40}$ ]] || die "refusing argument '$w' (allowed: main, a commit sha, --plan, --force-all)"
         ref="$w" ;;
    esac
  done

  git fetch --quiet origin "$BRANCH"
  target="$(git rev-parse --verify "${ref:-origin/$BRANCH}^{commit}")" || die "unknown commit '$ref'"
  git merge-base --is-ancestor "$target" "origin/$BRANCH" || die "$target is not on origin/$BRANCH"
  OLD_SHA="$(git rev-parse HEAD)"

  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    die "checkout has local modifications to tracked files; refusing to overwrite them: $(git status --porcelain --untracked-files=no | head -5 | tr '\n' ' ')"
  fi

  if [[ "$PLAN_ONLY" == 0 ]]; then
    git checkout -q "$BRANCH"
    git reset -q --hard "$target"
  fi
  # Run stage 2 in a pipeline (not `exec` + process substitution): tee has
  # flushed everything before we exit, so the SSH session never cuts the tail
  # of the log. fd 9 (the lock) is inherited by the child.
  rc=0
  ZYND_DEPLOY_STAGE=2 OLD_SHA="$OLD_SHA" NEW_SHA="$target" PLAN_ONLY="$PLAN_ONLY" FORCE_ALL="$FORCE_ALL" \
    "$REPO/infra/single-box/deploy.sh" 2>&1 | tee -a "$BOX/deploy.log" || rc="${PIPESTATUS[0]}"
  exit "$rc"
fi

# ── Stage 2: decide and act ───────────────────────────────────────────────
trap 'log "deploy FAILED at line $LINENO. Previous commit was ${OLD_SHA:0:12}; roll back with: deploy.sh ${OLD_SHA:0:12}"' ERR

if [[ "$OLD_SHA" == "$NEW_SHA" && "$FORCE_ALL" == 0 ]]; then
  log "already at ${NEW_SHA:0:12}; nothing to deploy"
  exit 0
fi

changed="$(git diff --name-only "$OLD_SHA" "$NEW_SHA")"
touched() { grep -qE "$1" <<<"$changed"; }
log "${OLD_SHA:0:12} -> ${NEW_SHA:0:12} ($(grep -c . <<<"$changed" || true) files changed)"

COMPOSE_FILES=(-f infra/api-box/docker-compose.prod.yml -f infra/single-box/docker-compose.override.yml)
COMPOSE=(docker compose -p zynd "${COMPOSE_FILES[@]}" --env-file "$BOX/compose.env")
COMPOSE_TOUCHED='^(infra/api-box/docker-compose\.prod\.yml|infra/single-box/docker-compose\.override\.yml)$'

do_persona_api=0; do_persona_web=0; do_cards_web=0; do_memory=0; do_cards_api=0; do_pm2_config=0
if [[ "$FORCE_ALL" == 1 ]]; then
  do_persona_api=1; do_persona_web=1; do_cards_web=1; do_memory=1; do_cards_api=1
else
  touched '^services/persona-api/'  && do_persona_api=1
  touched '^apps/persona-web/'      && do_persona_web=1
  touched '^apps/cards-web/'        && do_cards_web=1
  touched '^services/memory/'       && do_memory=1
  touched '^services/cards-api/'    && do_cards_api=1
  if touched "$COMPOSE_TOUCHED"; then do_memory=1; do_cards_api=1; fi
fi
touched '^infra/single-box/ecosystem\.config\.js$' && do_pm2_config=1

# dependency files: reinstall when they changed, or on --force-all
dep_changed() { [[ "$FORCE_ALL" == 1 ]] || touched "$1"; }
note() { if dep_changed "$1"; then printf '%s' "$2"; fi; }   # always exits 0 (safe inside $(...) under set -e)

plan=()
((do_persona_api)) && plan+=("persona-api (pm2 api)$(note '^services/persona-api/requirements\.txt$' ' +pip install')")
((do_persona_web)) && plan+=("persona-web (pm2 web)$(note '^apps/persona-web/package-lock\.json$' ' +npm ci') +build")
((do_cards_web))   && plan+=("cards-web (pm2 cards-web)$(note '^apps/cards-web/package-lock\.json$' ' +npm ci') +build")
((do_memory))      && plan+=("memory (docker: api worker mcp)")
((do_cards_api))   && plan+=("cards-api (docker: cards)")
((do_pm2_config))  && plan+=("pm2 ecosystem config changed: startOrRestart all pm2 apps")
if ((${#plan[@]})); then printf '[plan] %s\n' "${plan[@]}"; else log "[plan] no service files changed; only the checkout moves"; fi
touched '^packages/db/' && log "NOTE: packages/db changed. Deploys never apply migrations; a person does (packages/db/README.md)."

if [[ "$PLAN_ONLY" == 1 ]]; then log "--plan: nothing changed"; exit 0; fi

# Caddy is not managed by deploys (needs root): just say when it drifted.
if ! cmp -s infra/single-box/Caddyfile /etc/caddy/Caddyfile 2>/dev/null; then
  log "NOTE: infra/single-box/Caddyfile differs from /etc/caddy/Caddyfile. As root: install -m644 it there, then 'systemctl reload caddy'."
fi

# ── actions ───────────────────────────────────────────────────────────────
build_web() { # <dir> <lockfile-touched-regex>
  local dir=$1
  (
    cd "$REPO/$dir"
    if dep_changed "^${dir}/package-lock\.json$" || [[ ! -d node_modules ]]; then
      log "$dir: npm ci"; npm ci --no-audit --no-fund
    fi
    rm -rf .next.prev
    [[ -d .next ]] && cp -a .next .next.prev
    log "$dir: npm run build"
    if npm run build; then
      rm -rf .next.prev
    else
      log "$dir: build FAILED; restoring the previous build, nothing restarted"
      rm -rf .next
      [[ -d .next.prev ]] && mv .next.prev .next
      exit 1
    fi
  )
}

# Builds first (any failure stops here, before anything is restarted).
((do_persona_web)) && build_web apps/persona-web
((do_cards_web))   && build_web apps/cards-web

if ((do_persona_api)); then
  if dep_changed '^services/persona-api/requirements\.txt$'; then
    log "persona-api: pip install -r requirements.txt"
    services/persona-api/.venv/bin/pip install --quiet -r services/persona-api/requirements.txt
  fi
fi

if ((do_memory)); then
  log "memory: docker compose up --build (api worker mcp)"
  "${COMPOSE[@]}" up -d --build postgres redis api worker mcp
fi
if ((do_cards_api)); then
  log "cards-api: docker compose up --build (cards)"
  "${COMPOSE[@]}" up -d --build cards
fi

if ((do_pm2_config)); then
  log "pm2: startOrRestart infra/single-box/ecosystem.config.js"
  pm2 startOrRestart infra/single-box/ecosystem.config.js --update-env
else
  ((do_persona_api)) && { log "pm2: restart api";       pm2 restart api --update-env; }
  ((do_persona_web)) && { log "pm2: restart web";       pm2 restart web --update-env; }
  ((do_cards_web))   && { log "pm2: restart cards-web"; pm2 restart cards-web --update-env; }
fi
pm2 save >/dev/null

# ── health checks (only what was touched) ─────────────────────────────────
wait_http() { # <name> <url> [tries]
  local name=$1 url=$2 tries=${3:-60} i code=000
  for ((i = 1; i <= tries; i++)); do
    code="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$url" || true)"
    if [[ "$code" == 200 ]]; then log "healthy: $name"; return 0; fi
    sleep 2
  done
  log "UNHEALTHY: $name ($url answered $code)"; return 1
}
failed=0
((do_persona_api || do_pm2_config)) && { wait_http persona-api http://127.0.0.1:8000/api/openapi.json || failed=1; }
((do_persona_web  || do_pm2_config)) && { wait_http persona-web http://127.0.0.1:3001/ || failed=1; }
((do_cards_web    || do_pm2_config)) && { wait_http cards-web   http://127.0.0.1:3002/ || failed=1; }
((do_memory))                        && { wait_http memory-api  http://127.0.0.1:8001/health || failed=1; }
((do_cards_api))                     && { wait_http cards-api   http://127.0.0.1:8002/health || failed=1; }

if [[ "$failed" == 1 ]]; then
  die "health checks failed after deploying ${NEW_SHA:0:12}. Roll back with: deploy.sh ${OLD_SHA:0:12}"
fi
log "deployed ${NEW_SHA:0:12} OK"
