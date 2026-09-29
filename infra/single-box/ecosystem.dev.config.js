// PM2 manifest for the DEV instance on the single box (branch `dev`, checkout
// /home/ubuntu/zynd-platform-dev). Prod's is ecosystem.config.js; both run under
// the same pm2 daemon, so every name and port here is different from prod's.
//
//   pm2 start infra/single-box/ecosystem.dev.config.js
//   pm2 restart api-dev web-dev cards-web-dev
//
// Ports (all 127.0.0.1; host Caddy serves them on the dev.* domains):
// persona-api 8100, persona-web 3101, cards-web 3102. The dev containers
// (memory 8101, mcp 8190, cards-api 8102) come from docker-compose.dev.yml.
// `next start` needs `npm run build` first; NEXT_PUBLIC_* are baked in at build.
const ROOT = process.env.ZYND_ROOT_DEV || "/home/ubuntu/zynd-platform-dev";

module.exports = {
  apps: [
    {
      name: "api-dev", // persona-api
      cwd: `${ROOT}/services/persona-api`,
      script: `${ROOT}/services/persona-api/.venv/bin/uvicorn`,
      args: "main:app --host 127.0.0.1 --port 8100 --workers 1 --loop asyncio",
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
      name: "web-dev", // persona-web
      cwd: `${ROOT}/apps/persona-web`,
      script: "/usr/bin/npx",
      args: "next start -H 127.0.0.1 -p 3101",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      max_memory_restart: "1G",
      env: { NODE_ENV: "production", PORT: "3101", HOSTNAME: "127.0.0.1" },
      merge_logs: true,
      time: true,
    },
    {
      name: "cards-web-dev",
      cwd: `${ROOT}/apps/cards-web`,
      script: "/usr/bin/npx",
      args: "next start -H 127.0.0.1 -p 3102",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      max_memory_restart: "1G",
      env: { NODE_ENV: "production", PORT: "3102", HOSTNAME: "127.0.0.1" },
      merge_logs: true,
      time: true,
    },
  ],
};
