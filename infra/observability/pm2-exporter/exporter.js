#!/usr/bin/env node
// Serves pm2 process stats as Prometheus metrics on 127.0.0.1:9209.
//
// Runs as its own systemd service (zynd-pm2-exporter.service), not under pm2:
// it must keep reporting when pm2 itself is the thing that broke. No
// dependencies; it shells out to `pm2 jlist`, but only when the pm2 daemon is
// already alive, because `pm2 jlist` would otherwise start a fresh daemon.
"use strict";

const http = require("http");
const fs = require("fs");
const path = require("path");
const { execFile } = require("child_process");

const PORT = 9209;
const PM2_BIN = "/usr/bin/pm2";
const PM2_HOME = process.env.PM2_HOME || path.join(process.env.HOME || "/home/ubuntu", ".pm2");
const CACHE_MS = 5000; // concurrent scrapes share one `pm2 jlist`

function daemonAlive() {
  try {
    const pid = parseInt(fs.readFileSync(path.join(PM2_HOME, "pm2.pid"), "utf8"), 10);
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function jlist() {
  return new Promise((resolve) => {
    if (!daemonAlive()) return resolve(null);
    const opts = { timeout: 10000, maxBuffer: 16 << 20, env: { ...process.env, PM2_HOME } };
    execFile(PM2_BIN, ["jlist"], opts, (err, stdout) => {
      if (err) return resolve(null);
      // pm2 may print banners before the JSON array.
      const line = stdout.split("\n").find((l) => l.startsWith("["));
      try {
        resolve(line ? JSON.parse(line) : null);
      } catch {
        resolve(null);
      }
    });
  });
}

const esc = (v) => String(v).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n");

function render(procs) {
  const out = [];
  const metric = (name, type, help, rows) => {
    out.push(`# HELP ${name} ${help}`, `# TYPE ${name} ${type}`);
    for (const [labels, value] of rows) {
      const l = labels ? `{${Object.entries(labels).map(([k, v]) => `${k}="${esc(v)}"`).join(",")}}` : "";
      out.push(`${name}${l} ${value}`);
    }
  };

  metric("pm2_up", "gauge", "1 if the pm2 daemon answered, 0 if it is down or unreadable.", [[null, procs ? 1 : 0]]);
  if (procs) {
    const apps = procs.filter((p) => !p.pm2_env.pmx_module);
    const now = Date.now();
    const per = (fn) => apps.map((p) => [{ name: p.name }, fn(p)]);
    metric("pm2_process_online", "gauge", "1 if the process status is online.", per((p) => (p.pm2_env.status === "online" ? 1 : 0)));
    metric("pm2_process_memory_bytes", "gauge", "Resident memory of the process.", per((p) => p.monit.memory || 0));
    metric("pm2_process_cpu_percent", "gauge", "CPU use of the process, percent of one core.", per((p) => p.monit.cpu || 0));
    metric("pm2_process_restarts_total", "counter", "Restarts since the process was first started (includes deploy restarts).", per((p) => p.pm2_env.restart_time || 0));
    metric("pm2_process_unstable_restarts", "gauge", "Recent restarts pm2 counts as unstable (crashed soon after start).", per((p) => p.pm2_env.unstable_restarts || 0));
    metric("pm2_process_uptime_seconds", "gauge", "Seconds since the last (re)start; 0 when not online.", per((p) => (p.pm2_env.status === "online" ? Math.max(0, Math.round((now - p.pm2_env.pm_uptime) / 1000)) : 0)));
    metric("pm2_process_pid", "gauge", "Current pid (0 when not running).", per((p) => p.pid || 0));
  }
  return out.join("\n") + "\n";
}

let cache = { at: 0, body: "" };

http
  .createServer(async (req, res) => {
    if (req.url !== "/metrics") {
      res.writeHead(404).end();
      return;
    }
    if (Date.now() - cache.at > CACHE_MS) cache = { at: Date.now(), body: render(await jlist()) };
    res.writeHead(200, { "Content-Type": "text/plain; version=0.0.4" }).end(cache.body);
  })
  .listen(PORT, "127.0.0.1");
