// PM2 manifest for the single-box deployment (host processes only; the memory
// stack + cards-api run in Docker, see docker-compose.override.yml).
//
//   pm2 start infra/single-box/ecosystem.config.js            # everything
//   pm2 start infra/single-box/ecosystem.config.js --only web,cards-web
//   pm2 restart api web cards-web
//
// Ports: persona-api 127.0.0.1:8000 and persona-web 127.0.0.1:3001 sit behind
// Caddy on :3000 (Caddyfile); cards-web is served directly on :3002.
// `next start` needs `npm run build` first, and NEXT_PUBLIC_* values are baked
// in at build time, so rebuild after changing an app's .env.local.
const ROOT = process.env.ZYND_ROOT || "/home/ubuntu/zynd-platform";

module.exports = {
  apps: [
    {
      name: "api", // persona-api
      cwd: `${ROOT}/services/persona-api`,
      script: `${ROOT}/services/persona-api/.venv/bin/uvicorn`,
      // --loop asyncio for the same reason as ecosystem.dev.config.js.
      // One worker: heartbeats and persona rehydration are per-process state.
      args: "main:app --host 127.0.0.1 --port 8000 --workers 1 --loop asyncio",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      max_memory_restart: "4G",
      env: { PYTHONUNBUFFERED: "1", PYTHONFAULTHANDLER: "1" },
      merge_logs: true,
      time: true,
    },
    {
      name: "web", // persona-web
      cwd: `${ROOT}/apps/persona-web`,
      script: "/usr/bin/npx",
      args: "next start -H 127.0.0.1 -p 3001",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      max_memory_restart: "1G",
      env: { NODE_ENV: "production", PORT: "3001", HOSTNAME: "127.0.0.1" },
      merge_logs: true,
      time: true,
    },
    {
      name: "cards-web",
      cwd: `${ROOT}/apps/cards-web`,
      script: "/usr/bin/npx",
      args: "next start -H 0.0.0.0 -p 3002",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      max_memory_restart: "1G",
      env: { NODE_ENV: "production", PORT: "3002", HOSTNAME: "0.0.0.0" },
      merge_logs: true,
      time: true,
    },
  ],
};
