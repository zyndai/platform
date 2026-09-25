// PM2 process manifest for the agent-persona DEV channel.
// Dev channel: dev.persona.zynd.ai — backend on :8001, web on :3002.
// Start:   pm2 start ecosystem.dev.config.js
// Restart: pm2 restart api-dev web-dev
// Logs:    pm2 logs api-dev  |  pm2 logs web-dev
//
// Deploy flow: git pull in /home/ubuntu/agent-persona-dev ->
//   (backend) restart only, unless requirements.txt changed -> pip install
//   (webapp)  npm run build ALWAYS after pull, then restart
// Production equivalent lives in /home/ubuntu/agent-persona/ecosystem.config.js.

const DEV = "/home/ubuntu/agent-persona-dev";

module.exports = {
  apps: [
    {
      // ── FastAPI backend (dev) ───────────────────────────────────
      name: "api-dev",
      cwd: `${DEV}/backend`,
      script: `${DEV}/backend/.venv/bin/uvicorn`,
      // --loop asyncio: uvloop's aarch64 build intermittently corrupts the
      // heap here (malloc(): unsorted double linked list corrupted /
      // silent segfaults killing the process mid-chat-turn). Pure-Python
      // loop is the stable choice on this box until that's root-caused.
      args: "main:app --host 127.0.0.1 --port 8001 --workers 1 --loop asyncio",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      // Same in-process-state constraints as prod (heartbeats, persona
      // rehydration) — keep at 1 worker.
      max_memory_restart: "4G",
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONFAULTHANDLER: "1",
        OPENROUTER_MODEL: "deepseek/deepseek-v4-flash",
      },
      out_file: "/home/ubuntu/.pm2/logs/api-dev-out.log",
      error_file: "/home/ubuntu/.pm2/logs/api-dev-err.log",
      merge_logs: true,
      time: true,
    },
    {
      // ── Next.js production server (dev) ─────────────────────────
      name: "web-dev",
      cwd: `${DEV}/webapp`,
      script: "/usr/bin/npx",
      args: "next start -H 127.0.0.1 -p 3002",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "production",
        NEXT_PUBLIC_API_URL: "https://dev.persona.zynd.ai",
        NEXT_PUBLIC_MEMORY_API_URL: "https://api.zynd.ai",
        PORT: "3002",
        HOSTNAME: "127.0.0.1",
      },
      out_file: "/home/ubuntu/.pm2/logs/web-dev-out.log",
      error_file: "/home/ubuntu/.pm2/logs/web-dev-err.log",
      merge_logs: true,
      time: true,
    },
  ],
};
