#!/usr/bin/env bash
# Server-side deploy for the single box. Runs as `ubuntu`. Two environments live
# on the box (infra/single-box/README.md): prod (checkout of `main`) and dev
# (checkout of `dev`). Called by .github/workflows/deploy-single-box.yml over SSH
# as a forced command, or by hand:
#
#   deploy.sh                       # deploy the latest origin/main to prod
#   deploy.sh --env=dev             # deploy the latest origin/dev to dev
#   deploy.sh [--env=..] <sha>      # roll that environment to a commit on its branch
#   deploy.sh [--env=..] --plan     # show what would change, touch nothing
#   deploy.sh [--env=..] --force-all  # redeploy every service of that environment
#
# Arguments come from $SSH_ORIGINAL_COMMAND when run as the forced command.
# (`main` and `latest` both mean "the newest commit of the environment's branch".)
#
# What it does: moves that environment's checkout to the target commit, works
# out which services' files changed since the previous commit, rebuilds and
# restarts only those, then health-checks them. A failed web build restores the
# previous .next and restarts nothing, so the old version keeps serving. It never
# applies database migrations (packages/db is applied by a person) and never
# touches Caddy or DNS.
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

BOX="${ZYND_BOX:-/home/ubuntu/.zynd-box}"

log() { printf '[deploy %s] %s\n' "$(date -u +%T)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

# Everything that differs between the two environments lives here: checkout,
# branch, pm2 app names, ecosystem file, docker compose project and services,
# and the localhost ports the health checks hit.
configure_env() {
  case "$1" in
    prod)
      REPO="${ZYND_ROOT:-/home/ubuntu/zynd-platform}"; BRANCH=main
      PM2_API=api; PM2_WEB=web; PM2_CARDS_WEB=cards-web
      ECOSYSTEM=infra/single-box/ecosystem.config.js
      COMPOSE=(docker compose -p zynd -f infra/api-box/docker-compose.prod.yml
               -f infra/single-box/docker-compose.override.yml --env-file "$BOX/compose.env")
      COMPOSE_TOUCHED='^(infra/api-box/docker-compose\.prod\.yml|infra/single-box/docker-compose\.override\.yml)$'
      MEMORY_SERVICES=(postgres redis api worker mcp); CARDS_SERVICES=(cards)
      P_API=8000; P_WEB=3001; P_CARDS_WEB=3002; P_MEMORY=8001; P_CARDS_API=8002 ;;
    dev)
      REPO="${ZYND_ROOT_DEV:-/home/ubuntu/zynd-platform-dev}"; BRANCH=dev
      PM2_API=api-dev; PM2_WEB=web-dev; PM2_CARDS_WEB=cards-web-dev
      ECOSYSTEM=infra/single-box/ecosystem.dev.config.js
      COMPOSE=(env "DEV_ROOT=$REPO" docker compose -p zynd-dev -f infra/single-box/docker-compose.dev.yml)
      COMPOSE_TOUCHED='^infra/single-box/docker-compose\.dev\.yml$'
      # No dev worker on purpose: memory's nightly cron jobs would run twice on the shared DB.
      MEMORY_SERVICES=(api-dev mcp-dev); CARDS_SERVICES=(cards-dev)
      P_API=8100; P_WEB=3101; P_CARDS_WEB=3102; P_MEMORY=8101; P_CARDS_API=8102 ;;
    *) die "unknown environment '$1'" ;;
  esac
}

# ── Stage 1: parse args, take the lock, move the checkout, re-exec ────────
# Re-exec so the (possibly just-updated) deploy.sh is what does the real work,
# instead of bash reading a file that git rewrote under it.
if [[ -z "${ZYND_DEPLOY_STAGE:-}" ]]; then
  read -r -a words <<<"${SSH_ORIGINAL_COMMAND:-$*}"
  ENV_NAME=prod; ref=""; PLAN_ONLY=0; FORCE_ALL=0
  for w in "${words[@]:-}"; do
    case "$w" in
      "") ;;
      --plan) PLAN_ONLY=1 ;;
      --force-all) FORCE_ALL=1 ;;
      --env=prod|--env=dev) ENV_NAME="${w#--env=}" ;;
      main|latest) ref="" ;;
      *) [[ "$w" =~ ^[0-9a-f]{7,40}$ ]] || die "refusing argument '$w' (allowed: main|latest, a commit sha, --env=prod|dev, --plan, --force-all)"
         ref="$w" ;;
    esac
  done

  configure_env "$ENV_NAME"
  cd "$REPO"
  mkdir -p "$BOX"
  exec 9>"$BOX/deploy-$ENV_NAME.lock"
  flock -n 9 || die "another $ENV_NAME deploy is already running"

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
  ZYND_DEPLOY_STAGE=2 ZYND_ENV="$ENV_NAME" OLD_SHA="$OLD_SHA" NEW_SHA="$target" PLAN_ONLY="$PLAN_ONLY" FORCE_ALL="$FORCE_ALL" \
    "$REPO/infra/single-box/deploy.sh" 2>&1 | tee -a "$BOX/deploy-$ENV_NAME.log" || rc="${PIPESTATUS[0]}"
  exit "$rc"
fi

# ── Stage 2: decide and act ───────────────────────────────────────────────
configure_env "$ZYND_ENV"
cd "$REPO"
trap 'log "[$ZYND_ENV] deploy FAILED at line $LINENO. Previous commit was ${OLD_SHA:0:12}; roll back with: deploy.sh --env=$ZYND_ENV ${OLD_SHA:0:12}"' ERR

if [[ "$OLD_SHA" == "$NEW_SHA" && "$FORCE_ALL" == 0 ]]; then
  log "[$ZYND_ENV] already at ${NEW_SHA:0:12}; nothing to deploy"
  exit 0
fi

changed="$(git diff --name-only "$OLD_SHA" "$NEW_SHA")"
touched() { grep -qE "$1" <<<"$changed"; }
log "[$ZYND_ENV] ${OLD_SHA:0:12} -> ${NEW_SHA:0:12} ($(grep -c . <<<"$changed" || true) files changed)"

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
touched "^${ECOSYSTEM//./\\.}\$" && do_pm2_config=1

# dependency files: reinstall when they changed, or on --force-all
dep_changed() { [[ "$FORCE_ALL" == 1 ]] || touched "$1"; }
note() { if dep_changed "$1"; then printf '%s' "$2"; fi; }   # always exits 0 (safe inside $(...) under set -e)

plan=()
((do_persona_api)) && plan+=("persona-api (pm2 $PM2_API)$(note '^services/persona-api/requirements\.txt$' ' +pip install')")
((do_persona_web)) && plan+=("persona-web (pm2 $PM2_WEB)$(note '^apps/persona-web/package-lock\.json$' ' +npm ci') +build")
((do_cards_web))   && plan+=("cards-web (pm2 $PM2_CARDS_WEB)$(note '^apps/cards-web/package-lock\.json$' ' +npm ci') +build")
((do_memory))      && plan+=("memory (docker: ${MEMORY_SERVICES[*]})")
((do_cards_api))   && plan+=("cards-api (docker: ${CARDS_SERVICES[*]})")
((do_pm2_config))  && plan+=("pm2 ecosystem config changed: startOrRestart all $ZYND_ENV pm2 apps")
if ((${#plan[@]})); then printf '[plan] %s\n' "${plan[@]}"; else log "[plan] no service files changed; only the checkout moves"; fi
touched '^packages/db/' && log "NOTE: packages/db changed. Deploys never apply migrations; a person does (packages/db/README.md)."

if [[ "$PLAN_ONLY" == 1 ]]; then log "--plan: nothing changed"; exit 0; fi

# Caddy is not managed by deploys (needs root): just say when it drifted.
if ! cmp -s infra/single-box/Caddyfile /etc/caddy/Caddyfile 2>/dev/null; then
  log "NOTE: infra/single-box/Caddyfile differs from /etc/caddy/Caddyfile. As root: install -m644 it there, then 'systemctl reload caddy'."
fi

# ── actions ───────────────────────────────────────────────────────────────
build_web() { # <dir>
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
  log "memory: docker compose up --build (${MEMORY_SERVICES[*]})"
  "${COMPOSE[@]}" up -d --build "${MEMORY_SERVICES[@]}"
fi
if ((do_cards_api)); then
  log "cards-api: docker compose up --build (${CARDS_SERVICES[*]})"
  "${COMPOSE[@]}" up -d --build "${CARDS_SERVICES[@]}"
fi

if ((do_pm2_config)); then
  log "pm2: startOrRestart $ECOSYSTEM"
  pm2 startOrRestart "$ECOSYSTEM" --update-env
else
  ((do_persona_api)) && { log "pm2: restart $PM2_API";       pm2 restart "$PM2_API" --update-env; }
  ((do_persona_web)) && { log "pm2: restart $PM2_WEB";       pm2 restart "$PM2_WEB" --update-env; }
  ((do_cards_web))   && { log "pm2: restart $PM2_CARDS_WEB"; pm2 restart "$PM2_CARDS_WEB" --update-env; }
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
((do_persona_api || do_pm2_config)) && { wait_http persona-api "http://127.0.0.1:$P_API/api/openapi.json" || failed=1; }
((do_persona_web  || do_pm2_config)) && { wait_http persona-web "http://127.0.0.1:$P_WEB/" || failed=1; }
((do_cards_web    || do_pm2_config)) && { wait_http cards-web   "http://127.0.0.1:$P_CARDS_WEB/" || failed=1; }
((do_memory))                        && { wait_http memory-api  "http://127.0.0.1:$P_MEMORY/health" || failed=1; }
((do_cards_api))                     && { wait_http cards-api   "http://127.0.0.1:$P_CARDS_API/health" || failed=1; }

if [[ "$failed" == 1 ]]; then
  die "[$ZYND_ENV] health checks failed after deploying ${NEW_SHA:0:12}. Roll back with: deploy.sh --env=$ZYND_ENV ${OLD_SHA:0:12}"
fi
log "[$ZYND_ENV] deployed ${NEW_SHA:0:12} OK"
