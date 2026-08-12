// PM2 process manifest for agent-persona.
// Start everything:   pm2 start ecosystem.config.js
// Restart all:        pm2 restart all
// Logs:               pm2 logs           (interleaved, follow mode)
//                     pm2 logs api
//                     pm2 logs web
// Status table:       pm2 status
// Persist across reboot:
//   pm2 save                              (snapshot current process list)
//   pm2 startup                           (prints sudo command to install
//                                          a systemd unit that runs `pm2
//                                          resurrect` at boot — run it once)

module.exports = {
  apps: [
    {
      // ── FastAPI backend ───────────────────────────────────────────
      name: "api",
      cwd: "/home/ubuntu/agent-persona/backend",
      // Run uvicorn out of the project venv so requirements.txt deps
      // resolve. PM2 spawns this directly — no shell — so the binary
      // path has to be explicit.
      script: "/home/ubuntu/agent-persona/backend/.venv/bin/uvicorn",
      args: "main:app --host 127.0.0.1 --port 8000 --workers 1",
      // PM2 defaults to fork mode for non-Node scripts, which is what
      // we want — uvicorn manages its own worker count.
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      // The heartbeat manager and persona rehydration hold in-process
      // state per worker. Multiple instances would duplicate the
      // outbound WebSockets to dns01.zynd.ai. Keep this at 1.
      // 1G was getting hit every 15-45min under normal chat traffic,
      // killing in-flight requests (e.g. slow LinkedIn/Apify searches)
      // mid-stream with no error logged. The box has 123G total / 96G
      // free, so 1G was an arbitrarily tight ceiling, not a real
      // constraint — raised to give the in-memory conversation cache
      // (orchestrator.py's `_conversations`, never evicted) much more
      // room before a forced restart is needed.
      max_memory_restart: "4G",
      // PYTHONUNBUFFERED is essential — without it, print() output
      // never flushes to PM2's log buffer until the process exits.
      env: {
        PYTHONUNBUFFERED: "1",
        OPENROUTER_MODEL: "deepseek/deepseek-v4-flash",
      },
      out_file: "/home/ubuntu/.pm2/logs/api-out.log",
      error_file: "/home/ubuntu/.pm2/logs/api-err.log",
      merge_logs: true,
      time: true,
    },
    {
      // ── Next.js production server ─────────────────────────────────
      name: "web",
      cwd: "/home/ubuntu/agent-persona/webapp",
      // Use the npx shim that systemd was using — same binary that's
      // on $PATH for the ubuntu user. `next start` requires `next build`
      // to have been run beforehand (build artifacts in .next/).
      script: "/usr/bin/npx",
      args: "next start -H 127.0.0.1 -p 3001",
      interpreter: "none",
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "production",
        NEXT_PUBLIC_API_URL: "https://persona.zynd.ai",
        NEXT_PUBLIC_MEMORY_API_URL: "https://api.zynd.ai",
        PORT: "3001",
        HOSTNAME: "127.0.0.1",
      },
      out_file: "/home/ubuntu/.pm2/logs/web-out.log",
      error_file: "/home/ubuntu/.pm2/logs/web-err.log",
      merge_logs: true,
      time: true,
    },
  ],
};
