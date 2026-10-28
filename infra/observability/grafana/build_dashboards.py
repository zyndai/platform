#!/usr/bin/env python3
"""Generates grafana/dashboards/*.json (provisioned into Grafana, see ../README.md).

Hand-editing Grafana JSON is error-prone, so the dashboards are defined here and the
JSON is committed alongside. Change a dashboard by editing this file, then:

    python3 infra/observability/grafana/build_dashboards.py

and commit both. No dependencies. Queries use the project/env labels that every metric
and log line carries (README, "Labels").
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
# Not provisioned: dashboards to import by hand (Dashboards -> New -> Import), which then
# belong to Grafana and can be edited and saved in the UI.
IMPORT = Path(__file__).parent / "import"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}

# Same meaning everywhere: severity colours for the `level` label.
LEVEL_COLORS = {"error": "red", "warning": "orange", "info": "blue", "debug": "gray"}
HEALTH_STEPS = [{"color": "green", "value": None}, {"color": "yellow", "value": 70}, {"color": "red", "value": 85}]
UP_MAPPING = [{"type": "value", "options": {
    "0": {"text": "DOWN", "color": "red", "index": 0},
    "1": {"text": "UP", "color": "green", "index": 1}}}]


def tgt(expr, legend="", ds=PROM, ref="A", **extra):
    t = {"refId": ref, "datasource": ds, "expr": expr, "legendFormat": legend}
    t.update(extra)
    return t


def instant(expr, legend="", ds=PROM, ref="A", **extra):
    return tgt(expr, legend, ds, ref, instant=True, range=False, **extra)


def steps(*pairs):
    """steps(("green", None), ("red", 85)) -> Grafana threshold steps."""
    return [{"color": c, "value": v} for c, v in pairs]


class Dash:
    def __init__(self, uid, title, description, refresh="30s", time_from="now-6h"):
        self.uid, self.title, self.description = uid, title, description
        self.refresh, self.time_from = refresh, time_from
        self.panels, self.variables = [], []
        self._id, self._x, self._y, self._rowh = 0, 0, 0, 0

    def row(self, title):
        self._newline()
        self._id += 1
        self.panels.append({"id": self._id, "type": "row", "title": title, "collapsed": False,
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self._y}, "panels": []})
        self._y += 1

    def _newline(self):
        if self._x:
            self._y += self._rowh
            self._x, self._rowh = 0, 0

    def add(self, panel, w, h):
        if self._x + w > 24:
            self._newline()
        self._id += 1
        panel.update({"id": self._id, "gridPos": {"h": h, "w": w, "x": self._x, "y": self._y}})
        panel.setdefault("fieldConfig", {"defaults": {}, "overrides": []})
        self.panels.append(panel)
        self._x += w
        self._rowh = max(self._rowh, h)
        if self._x >= 24:
            self._newline()

    def var_custom(self, name, label, values, default):
        self.variables.append({
            "name": name, "label": label, "type": "custom", "query": ",".join(values),
            "current": {"text": default, "value": default},
            "options": [{"text": v, "value": v, "selected": v == default} for v in values],
            "includeAll": False, "multi": False})

    def var_query(self, name, label, ds, query, multi=False, default=None, text=False):
        v = {"name": name, "label": label, "type": "query", "datasource": ds, "refresh": 2, "sort": 1,
             "includeAll": multi, "multi": multi, "definition": query}
        if ds is PROM:
            v["query"] = {"query": query, "refId": "PrometheusVariableQueryEditor-VariableQuery"}
        else:
            v["query"] = query            # Loki's legacy label_values(...) string form
        if multi:
            v["allValue"] = ".*"
            v["current"] = {"text": "All", "value": "$__all"}
        elif default:
            v["current"] = {"text": default, "value": default}
        self.variables.append(v)

    def var_text(self, name, label):
        self.variables.append({"name": name, "label": label, "type": "textbox", "query": "",
                               "current": {"text": "", "value": ""}, "options": []})

    def build(self):
        return {
            "uid": self.uid, "title": self.title, "description": self.description,
            "tags": ["zynd"], "timezone": "browser", "editable": True, "graphTooltip": 1,
            "refresh": self.refresh, "schemaVersion": 41, "version": 1,
            "time": {"from": self.time_from, "to": "now"},
            "templating": {"list": self.variables},
            "annotations": {"list": []},
            "links": [{"type": "dashboards", "title": "Zynd dashboards", "tags": ["zynd"],
                       "asDropdown": True, "includeVars": False, "keepTime": True}],
            "panels": self.panels,
        }

    def write(self, out=OUT):
        out.mkdir(exist_ok=True)
        (out / f"{self.uid}.json").write_text(json.dumps(self.build(), indent=2, ensure_ascii=False) + "\n")


# ── Panel builders ────────────────────────────────────────────────────

def stat(title, targets, unit="short", thresholds=None, decimals=None, mappings=None,
         color_mode="value", graph=True, text_mode="auto", description=""):
    return {
        "type": "stat", "title": title, "description": description, "datasource": targets[0]["datasource"],
        "targets": targets,
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals, "mappings": mappings or [],
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": thresholds or steps(("blue", None))}},
            "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": color_mode, "graphMode": "area" if graph else "none",
                    "textMode": text_mode, "orientation": "auto", "justifyMode": "auto"},
    }


def timeseries(title, targets, unit="short", stack=False, description="", legend="list",
               min_=None, max_=None, bars=False, level_colors=False, thresholds_line=None):
    custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 1, "showPoints": "never",
              "fillOpacity": 60 if (stack or bars) else 10, "spanNulls": False,
              "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
    if thresholds_line:
        custom["thresholdsStyle"] = {"mode": "line"}
    defaults = {"unit": unit, "min": min_, "max": max_, "custom": custom,
                "color": {"mode": "palette-classic"}}
    if thresholds_line:
        defaults["thresholds"] = {"mode": "absolute", "steps": thresholds_line}
    overrides = []
    if level_colors:
        overrides = [{"matcher": {"id": "byName", "options": lvl},
                      "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": col}}]}
                     for lvl, col in LEVEL_COLORS.items()]
    return {
        "type": "timeseries", "title": title, "description": description,
        "datasource": targets[0]["datasource"], "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides},
        "options": {"legend": {"displayMode": "table" if legend == "table" else "list",
                               "placement": "bottom", "calcs": ["lastNotNull", "max"] if legend == "table" else []},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }


def bargauge(title, targets, unit="short", description="", thresholds=None, max_=None):
    return {
        "type": "bargauge", "title": title, "description": description,
        "datasource": targets[0]["datasource"], "targets": targets,
        "fieldConfig": {"defaults": {"unit": unit, "min": 0, "max": max_, "color": {"mode": "palette-classic"} if not thresholds else {"mode": "thresholds"},
                                     "thresholds": {"mode": "absolute", "steps": thresholds or steps(("blue", None))}},
                        "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                    "valueMode": "color", "namePlacement": "left", "sizing": "auto", "minVizHeight": 16},
    }


def table(title, targets, description="", transformations=None, overrides=None, sort_by=None):
    return {
        "type": "table", "title": title, "description": description,
        "datasource": targets[0]["datasource"], "targets": targets,
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
                        "overrides": overrides or []},
        "options": {"showHeader": True, "cellHeight": "sm",
                    "sortBy": [{"displayName": sort_by, "desc": True}] if sort_by else []},
        "transformations": transformations or [],
    }


def logs(title, expr, description="", max_lines=300):
    return {
        "type": "logs", "title": title, "description": description, "datasource": LOKI,
        "targets": [{"refId": "A", "datasource": LOKI, "expr": expr, "queryType": "range", "maxLines": max_lines}],
        "options": {"showTime": True, "showLabels": False, "showCommonLabels": False,
                    "wrapLogMessage": True, "prettifyLogMessage": False, "enableLogDetails": True,
                    "dedupStrategy": "none", "sortOrder": "Descending", "enableInfiniteScrolling": False},
    }


def col(field, unit=None, width=None, name=None, mapping=None, thresholds=None, cell=None):
    props = []
    if name:
        props.append({"id": "displayName", "value": name})
    if unit:
        props.append({"id": "unit", "value": unit})
    if width:
        props.append({"id": "custom.width", "value": width})
    if mapping:
        props.append({"id": "mappings", "value": mapping})
    if thresholds:
        props.append({"id": "thresholds", "value": {"mode": "absolute", "steps": thresholds}})
    if cell:
        props.append({"id": "custom.cellOptions", "value": cell})
    return {"matcher": {"id": "byName", "options": field}, "properties": props}


# ── 1. Box overview ───────────────────────────────────────────────────

def box_overview():
    d = Dash("zynd-box", "Box overview",
             "The whole single box: RAM, CPU, disk, and who is using the memory (containers and pm2 processes).")
    d.row("Right now")
    d.add(stat("RAM used", [instant('100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)')],
               "percent", steps(("green", None), ("yellow", 70), ("red", 85)), 1,
               description="Of total RAM, counting what the kernel can't reclaim. The box has no swap, so high = OOM kills."), 4, 4)
    d.add(stat("RAM available", [instant("node_memory_MemAvailable_bytes")], "bytes",
               steps(("red", None), ("yellow", 2e9), ("green", 4e9)), 1), 4, 4)
    d.add(stat("Disk used (/)", [instant('100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})')],
               "percent", steps(("green", None), ("yellow", 70), ("red", 80)), 1), 4, 4)
    d.add(stat("CPU busy", [instant('100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[$__rate_interval])))')],
               "percent", steps(("green", None), ("yellow", 60), ("red", 85)), 1), 4, 4)
    d.add(stat("Load (5m, per core)", [instant('node_load5 / scalar(count(count by (cpu) (node_cpu_seconds_total{mode="idle"})))')],
               "short", steps(("green", None), ("yellow", 0.7), ("red", 1)), 2), 4, 4)
    d.add(stat("OOM kills (in range)", [instant("increase(node_vmstat_oom_kill[$__range])")], "short",
               steps(("green", None), ("red", 1)), 0, description="Processes the kernel killed for lack of memory."), 4, 4)

    d.row("Memory")
    mem = [tgt('sum by (project, env) (container_memory_working_set_bytes{project!=""})', "{{project}} ({{env}})", ref="A"),
           tgt('sum by (project, env) (pm2_process_memory_bytes)', "{{project}} ({{env}})", ref="B")]
    d.add(timeseries("Memory by project", mem, "bytes", stack=True, legend="table",
                     description="Containers (cAdvisor, working set) and pm2 processes (RSS), stacked. "
                                 "Persona's pm2 processes and the memory/cards containers are different workloads, both shown."), 16, 9)
    d.add(bargauge("Top memory users, now",
                   [instant('topk(12, sum by (project, env) (container_memory_working_set_bytes{project!=""}))', "{{project}} ({{env}})", ref="A"),
                    instant('topk(12, sum by (project, env) (pm2_process_memory_bytes))', "{{project}} ({{env}})", ref="B")], "bytes"), 8, 9)
    d.add(timeseries("Box memory",
                     [tgt("node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes", "used", ref="A"),
                      tgt("node_memory_MemAvailable_bytes", "available", ref="B"),
                      tgt("node_memory_Cached_bytes", "page cache", ref="C")], "bytes", legend="table"), 12, 8)
    d.add(timeseries("Memory used %",
                     [tgt('100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)', "used %")],
                     "percent", min_=0, max_=100, thresholds_line=steps(("green", None), ("red", 85)),
                     description="The red line is the alert threshold (85%)."), 12, 8)

    d.row("CPU, disk, network")
    cpu = [tgt('sum by (project, env) (rate(container_cpu_usage_seconds_total{project!=""}[$__rate_interval]))', "{{project}} ({{env}})", ref="A"),
           tgt('sum by (project, env) (pm2_process_cpu_percent) / 100', "{{project}} ({{env}})", ref="B")]
    d.add(timeseries("CPU by project (cores)", cpu, "short", stack=True, legend="table",
                     description="1.0 = one full core of the 8."), 12, 8)
    d.add(timeseries("Network (eth0)",
                     [tgt('rate(node_network_receive_bytes_total{device="eth0"}[$__rate_interval])', "in", ref="A"),
                      tgt('rate(node_network_transmit_bytes_total{device="eth0"}[$__rate_interval])', "out", ref="B")], "Bps"), 12, 8)
    d.add(timeseries("Disk used (/)",
                     [tgt('100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})', "used %")],
                     "percent", min_=0, max_=100, thresholds_line=steps(("green", None), ("red", 80))), 12, 7)
    d.add(timeseries("Disk I/O",
                     [tgt('rate(node_disk_read_bytes_total{device="sda"}[$__rate_interval])', "read", ref="A"),
                      tgt('rate(node_disk_written_bytes_total{device="sda"}[$__rate_interval])', "write", ref="B")], "Bps"), 12, 7)

    d.row("Processes and containers")
    d.add(table("pm2 processes", [
        instant("pm2_process_online", ref="A", format="table"),
        instant("pm2_process_memory_bytes", ref="B", format="table"),
        instant("pm2_process_cpu_percent", ref="C", format="table"),
        instant("pm2_process_uptime_seconds", ref="D", format="table"),
        instant("pm2_process_restarts_total", ref="E", format="table")],
        description="Restarts include deploys. A process that keeps climbing here is crash-looping.",
        transformations=[
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, "job": True, "instance": True, "project": True},
                "indexByName": {"name": 0, "env": 1, "Value #A": 2, "Value #B": 3, "Value #C": 4, "Value #D": 5, "Value #E": 6},
                "renameByName": {"name": "process"}}}],
        overrides=[col("Value #A", name="state", mapping=[{"type": "value", "options": {
            "0": {"text": "down", "color": "red", "index": 0}, "1": {"text": "online", "color": "green", "index": 1}}}],
                       cell={"type": "color-text"}, width=80),
                   col("Value #B", "bytes", name="memory"), col("Value #C", "percent", name="cpu"),
                   col("Value #D", "s", name="uptime"), col("Value #E", name="restarts", cell={"type": "color-text"},
                                                           thresholds=steps(("green", None), ("yellow", 10), ("red", 30)))],
        sort_by="process"), 12, 9)
    d.add(table("Containers", [
        instant('container_memory_working_set_bytes{project!=""}', ref="A", format="table"),
        instant('rate(container_cpu_usage_seconds_total{project!=""}[$__rate_interval])', ref="B", format="table"),
        instant('time() - container_start_time_seconds{project!=""}', ref="C", format="table")],
        description="Uptime resets when a container is recreated (a deploy).",
        transformations=[
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, "job": True, "instance": True, "id": True, "image": True, "cpu": True},
                "indexByName": {"project": 0, "env": 1, "name": 2, "Value #A": 3, "Value #B": 4, "Value #C": 5},
                "renameByName": {"name": "container"}}}],
        overrides=[col("Value #A", "bytes", name="memory"), col("Value #B", "short", name="cpu (cores)", ),
                   col("Value #C", "s", name="uptime")], sort_by="memory"), 12, 9)
    d.write()


# ── 2. One project ────────────────────────────────────────────────────

def project():
    d = Dash("zynd-project", "Project",
             "One service in one environment: health, memory, traffic, latency and its logs. Pick env and project at the top.")
    d.var_custom("env", "Environment", ["prod", "dev"], "prod")
    d.var_query("project", "Project", PROM,
                'label_values({__name__=~"container_memory_working_set_bytes|pm2_process_memory_bytes",env="$env",project!~"monitoring|box"}, project)',
                default="memory-api")
    d.var_text("search", "Log filter")
    sel = '{project="$project", env="$env"}'

    d.row("Health")
    d.add(stat("Public URL", [instant('max(probe_success{project="$project", env="$env"})')], "short",
               steps(("red", None), ("green", 1)), mappings=UP_MAPPING, color_mode="background", graph=False,
               description="Black-box probe of the public URL. No data = this project has no public URL of its own (worker, mcp, plugins)."), 4, 4)
    d.add(stat("Memory", [instant('sum(container_memory_working_set_bytes{project="$project", env="$env"}) or sum(pm2_process_memory_bytes{project="$project", env="$env"})')],
               "bytes", decimals=0), 4, 4)
    d.add(stat("CPU (cores)", [instant('sum(rate(container_cpu_usage_seconds_total{project="$project", env="$env"}[$__rate_interval])) or sum(pm2_process_cpu_percent{project="$project", env="$env"}) / 100')],
               "short", decimals=2), 4, 4)
    d.add(stat("Restarts (in range)", [instant('sum(changes(container_start_time_seconds{project="$project", env="$env"}[$__range])) or sum(increase(pm2_process_restarts_total{project="$project", env="$env"}[$__range]))')],
               "short", steps(("green", None), ("yellow", 3), ("red", 10)), 0,
               description="Container recreations (deploys count) or pm2 restarts in the selected time range."), 4, 4)
    d.add(stat("Errors (in range)", [instant('sum(count_over_time({project="$project", env="$env", level="error"}[$__range])) or vector(0)', ds=LOKI)],
               "short", steps(("green", None), ("yellow", 1), ("red", 50)), 0), 4, 4)
    d.add(stat("Probe latency", [instant('max(probe_duration_seconds{project="$project", env="$env"})')], "s",
               steps(("green", None), ("yellow", 1), ("red", 3)), 2), 4, 4)

    d.row("Resources")
    d.add(timeseries("Memory", [
        tgt('sum by (name) (container_memory_working_set_bytes{project="$project", env="$env"})', "{{name}}", ref="A"),
        tgt('sum by (name) (pm2_process_memory_bytes{project="$project", env="$env"})', "{{name}}", ref="B")],
        "bytes", legend="table"), 12, 8)
    d.add(timeseries("CPU (cores)", [
        tgt('sum by (name) (rate(container_cpu_usage_seconds_total{project="$project", env="$env"}[$__rate_interval]))', "{{name}}", ref="A"),
        tgt('sum by (name) (pm2_process_cpu_percent{project="$project", env="$env"}) / 100', "{{name}}", ref="B")],
        "short", legend="table"), 12, 8)

    d.row("Traffic (cards-api and memory-api only: the other services don't expose /metrics)")
    d.add(timeseries("Requests per second, by status", [
        tgt('sum by (status) (rate(http_requests_total{project="$project", env="$env"}[$__rate_interval]))', "{{status}}")],
        "reqps", stack=True, legend="table",
        description="Includes the /health probes (every few seconds)."), 8, 8)
    d.add(timeseries("5xx ratio", [
        tgt('(sum(rate(http_requests_total{project="$project", env="$env", status="5xx"}[$__rate_interval])) or vector(0)) / sum(rate(http_requests_total{project="$project", env="$env"}[$__rate_interval]))', "5xx share")],
        "percentunit", min_=0, thresholds_line=steps(("green", None), ("red", 0.05)),
        description="The red line is 5%, the alert threshold."), 8, 8)
    d.add(timeseries("Latency p95, by route", [
        tgt('histogram_quantile(0.95, sum by (le, handler) (rate(http_request_duration_seconds_bucket{project="$project", env="$env"}[$__rate_interval])))', "{{handler}}")],
        "s", legend="table", description="Per route template, not per URL. 'none' = paths that match no route (scanners)."), 8, 8)
    d.add(table("Busiest routes", [
        instant('topk(15, sum by (handler, method) (increase(http_requests_total{project="$project", env="$env"}[$__range])))', ref="A", format="table"),
        instant('histogram_quantile(0.95, sum by (le, handler, method) (increase(http_request_duration_seconds_bucket{project="$project", env="$env"}[$__range])))', ref="B", format="table"),
        instant('sum by (handler, method) (increase(http_requests_total{project="$project", env="$env", status=~"4xx|5xx"}[$__range]))', ref="C", format="table")],
        transformations=[
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {"excludeByName": {"Time": True},
                                           "indexByName": {"handler": 0, "method": 1, "Value #A": 2, "Value #C": 3, "Value #B": 4},
                                           "renameByName": {}}}],
        overrides=[col("Value #A", "short", name="requests"), col("Value #C", "short", name="4xx+5xx"),
                   col("Value #B", "s", name="p95")], sort_by="requests"), 24, 8)

    d.row("Logs")
    d.add(timeseries("Log lines by level", [tgt(f'sum by (level) (count_over_time({sel} [$__auto]))', "{{level}}", ds=LOKI)],
                     "short", stack=True, bars=True, level_colors=True), 24, 6)
    d.add(logs("Errors and warnings", f'{sel} | level=~"error|warning" |~ "(?i)$search"',
               "Tracebacks and Next.js stacks are one entry each."), 24, 12)
    d.add(logs("All logs", f'{sel} |~ "(?i)$search"', "Use the 'Log filter' box at the top to narrow this."), 24, 12)
    d.write()


# ── 3. Logs explorer ──────────────────────────────────────────────────

def logs_explorer():
    d = Dash("zynd-logs", "Logs", "Search every log line on the box by environment, project and level.",
             time_from="now-1h")
    base = '{source=~"docker|pm2", env=~"$env", project=~"$project", level=~"$level"}'
    d.var_query("env", "Environment", LOKI, 'label_values({source=~"docker|pm2"}, env)', multi=True)
    d.var_query("project", "Project", LOKI, 'label_values({source=~"docker|pm2", env=~"$env"}, project)', multi=True)
    d.var_query("level", "Level", LOKI, 'label_values({source=~"docker|pm2"}, level)', multi=True)
    d.var_text("search", "Contains (regex, case-insensitive)")

    d.row("Volume")
    d.add(timeseries("Lines by level", [tgt(f'sum by (level) (count_over_time({base} [$__auto]))', "{{level}}", ds=LOKI)],
                     "short", stack=True, bars=True, level_colors=True), 12, 7)
    d.add(timeseries("Errors by project", [tgt('sum by (project, env) (count_over_time({source=~"docker|pm2", env=~"$env", project=~"$project", level="error"} [$__auto]))', "{{project}} ({{env}})", ds=LOKI)],
                     "short", stack=True, bars=True), 12, 7)
    d.add(timeseries("Warnings by project", [tgt('sum by (project, env) (count_over_time({source=~"docker|pm2", env=~"$env", project=~"$project", level="warning"} [$__auto]))', "{{project}} ({{env}})", ds=LOKI)],
                     "short", stack=True, bars=True,
                     description="persona-api's '[heartbeat] ... failed' lines are warnings and dominate this."), 12, 7)
    d.add(timeseries("Crashes (tracebacks, fatal errors)", [tgt('sum by (project, env) (count_over_time({source=~"docker|pm2", env=~"$env", project=~"$project"} |~ "Traceback \\\\(most recent call last\\\\)|Fatal Python error|unhandledRejection" [$__auto]))', "{{project}} ({{env}})", ds=LOKI)],
                     "short", stack=True, bars=True), 12, 7)

    d.row("Lines")
    d.add(logs("Matching logs", f'{base} |~ "(?i)$search"',
               "Filtered by the selectors above and the 'Contains' box."), 24, 16)
    d.add(logs("Crashes", '{source=~"docker|pm2", env=~"$env", project=~"$project"} |~ "Traceback \\\\(most recent call last\\\\)|Fatal Python error|unhandledRejection"',
               "A traceback or a hard crash dump, one entry each."), 24, 12)
    d.write()


# ── 4. Edge (Caddy) ───────────────────────────────────────────────────

def edge():
    d = Dash("zynd-edge", "Edge (Caddy)",
             "Public traffic by hostname from Caddy's access log, plus uptime and certificate expiry. "
             "Excludes this stack's own uptime probes.", time_from="now-3h")
    d.var_query("host", "Host", LOKI, 'label_values({source="caddy"}, host)', multi=True)
    base = '{source="caddy", host=~"$host"} != "Blackbox Exporter"'

    d.row("Uptime")
    d.add(stat("Public URLs", [instant("probe_success", "{{project}} ({{env}})")], "short",
               steps(("red", None), ("green", 1)), mappings=UP_MAPPING, color_mode="background", graph=False,
               text_mode="value_and_name", description="Black-box probe of each public URL every 30s."), 12, 6)
    d.add(stat("Certificate expires in", [instant("min by (url) (probe_ssl_earliest_cert_expiry) - time()", "{{url}}")], "s",
               steps(("red", None), ("yellow", 14 * 86400), ("green", 30 * 86400)), graph=False,
               text_mode="value_and_name", description="Caddy renews at 30 days; under 14 days means renewal is failing."), 12, 6)

    d.row("Traffic")
    d.add(timeseries("Requests per second, by host", [tgt(f'sum by (host) (rate({base} [$__auto]))', "{{host}}", ds=LOKI)],
                     "reqps", stack=True, legend="table"), 12, 8)
    d.add(timeseries("Responses by status", [tgt(f'sum by (status) (count_over_time({base} [$__auto]))', "{{status}}", ds=LOKI)],
                     "short", stack=True, bars=True, legend="table"), 12, 8)
    d.add(stat("5xx share (in range)", [instant(
        f'sum(count_over_time({{source="caddy", host=~"$host", status=~"5.."}} != "Blackbox Exporter" [$__range])) / sum(count_over_time({base} [$__range]))', ds=LOKI)],
        "percentunit", steps(("green", None), ("yellow", 0.01), ("red", 0.05)), 2), 4, 8)
    d.add(timeseries("5xx per second, by host", [tgt(f'sum by (host) (rate({{source="caddy", host=~"$host", status=~"5.."}} [$__auto]))', "{{host}}", ds=LOKI)],
                     "reqps", stack=True, bars=True), 10, 8)
    d.add(timeseries("Latency p95, by host", [tgt(f'quantile_over_time(0.95, {base} | json duration="duration" | unwrap duration [$__auto]) by (host)', "{{host}}", ds=LOKI)],
                     "s", legend="table", description="Time Caddy spent on the request, including the upstream app."), 10, 8)

    d.row("Who is hitting us")
    d.add(table("Top 404 paths", [instant(f'topk(20, sum by (host, uri) (count_over_time({{source="caddy", host=~"$host", status="404"}} != "Blackbox Exporter" | json uri="request.uri" [$__range])))', ds=LOKI, format="table")],
                description="Mostly scanners probing for /wp-login.php, /.env and the like.",
                transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True}, "renameByName": {"Value": "requests"}}}],
                sort_by="requests"), 12, 9)
    d.add(table("Top clients", [instant(f'topk(15, sum by (ip) (count_over_time({base} | json ip="request.remote_ip" [$__range])))', ds=LOKI, format="table")],
                transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True}, "renameByName": {"Value": "requests"}}}],
                sort_by="requests"), 6, 9)
    d.add(table("Top user agents", [instant(f'topk(15, sum by (ua) (count_over_time({base} | json ua=`request.headers["User-Agent"][0]` [$__range])))', ds=LOKI, format="table")],
                transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True}, "renameByName": {"Value": "requests"}}}],
                sort_by="requests"), 6, 9)

    d.row("Errors")
    d.add(logs("5xx responses", '{source="caddy", host=~"$host", status=~"5.."} != "Blackbox Exporter"',
               "Raw access-log entries; expand one for the full request."), 24, 10)
    d.write()

# ── 5. Overview (importable, not provisioned) ─────────────────────────

def overview():
    d = Dash("zynd-overview", "Zynd overview",
             "Everything on one screen: are the public URLs up, is the box healthy, how are the APIs "
             "doing, which processes are restarting, and the latest errors. Pick prod or dev at the top. "
             "The provisioned dashboards in the Zynd folder go deeper.", time_from="now-3h")
    d.var_custom("env", "Environment", ["prod", "dev"], "prod")
    env = 'env="$env"'

    d.row("Status")
    d.add(stat("Public URLs", [instant(f"probe_success{{{env}}}", "{{project}}")], "short",
               steps(("red", None), ("green", 1)), mappings=UP_MAPPING, color_mode="background", graph=False,
               text_mode="value_and_name"), 10, 5)
    d.add(stat("RAM used", [instant("100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)")],
               "percent", steps(("green", None), ("yellow", 70), ("red", 85)), 0), 3, 5)
    d.add(stat("Disk used", [instant('100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})')],
               "percent", steps(("green", None), ("yellow", 70), ("red", 80)), 0), 3, 5)
    d.add(stat("CPU busy", [instant('100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[$__rate_interval])))')],
               "percent", steps(("green", None), ("yellow", 60), ("red", 85)), 0), 3, 5)
    d.add(stat("Errors logged", [instant(f'sum(count_over_time({{source=~"docker|pm2", {env}, level="error"}}[$__range])) or vector(0)', ds=LOKI)],
               "short", steps(("green", None), ("yellow", 1), ("red", 100)), 0,
               description="Log records at level=error in the selected range, all projects in this env."), 3, 5)
    d.add(stat("Firing alerts", [instant('count(ALERTS{alertstate="firing"}) or vector(0)')], "short",
               steps(("green", None), ("orange", 1), ("red", 3)), 0, graph=False,
               description="All environments. Details: Alerting -> Alert rules."), 2, 5)

    d.row("Resources")
    d.add(timeseries("Memory by project", [
        tgt(f'sum by (project) (container_memory_working_set_bytes{{{env}}})', "{{project}}", ref="A"),
        tgt(f'sum by (project) (pm2_process_memory_bytes{{{env}}})', "{{project}}", ref="B")],
        "bytes", stack=True, legend="table"), 12, 8)
    d.add(timeseries("CPU by project (cores)", [
        tgt(f'sum by (project) (rate(container_cpu_usage_seconds_total{{{env}}}[$__rate_interval]))', "{{project}}", ref="A"),
        tgt(f'sum by (project) (pm2_process_cpu_percent{{{env}}}) / 100', "{{project}}", ref="B")],
        "short", stack=True, legend="table"), 12, 8)

    d.row("APIs (cards-api, memory-api)")
    d.add(timeseries("Requests per second", [
        tgt(f'sum by (project, status) (rate(http_requests_total{{{env}}}[$__rate_interval]))', "{{project}} {{status}}")],
        "reqps", stack=True, legend="table", description="Includes the /health probes."), 8, 8)
    d.add(timeseries("5xx share", [
        tgt(f'(sum by (project) (rate(http_requests_total{{{env}, status="5xx"}}[$__rate_interval])) or sum by (project) (rate(http_requests_total{{{env}}}[$__rate_interval])) * 0) '
            f'/ sum by (project) (rate(http_requests_total{{{env}}}[$__rate_interval]))', "{{project}}")],
        "percentunit", min_=0, thresholds_line=steps(("green", None), ("red", 0.05)),
        description="The red line is 5%, the alert threshold."), 8, 8)
    d.add(timeseries("Latency p95", [
        tgt(f'histogram_quantile(0.95, sum by (le, project) (rate(http_request_duration_seconds_bucket{{{env}, handler!="none"}}[$__rate_interval])))', "{{project}}")],
        "s", legend="table"), 8, 8)

    d.row("Processes")
    d.add(table("pm2 processes", [
        instant(f"pm2_process_online{{{env}}}", ref="A", format="table"),
        instant(f"pm2_process_memory_bytes{{{env}}}", ref="B", format="table"),
        instant(f"pm2_process_uptime_seconds{{{env}}}", ref="C", format="table"),
        instant(f"increase(pm2_process_restarts_total{{{env}}}[$__range])", ref="D", format="table")],
        transformations=[
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, "job": True, "instance": True, "env": True, "project": True},
                "indexByName": {"name": 0, "Value #A": 1, "Value #B": 2, "Value #C": 3, "Value #D": 4},
                "renameByName": {"name": "process"}}}],
        overrides=[col("Value #A", name="state", mapping=[{"type": "value", "options": {
            "0": {"text": "down", "color": "red", "index": 0}, "1": {"text": "online", "color": "green", "index": 1}}}],
                       cell={"type": "color-text"}),
                   col("Value #B", "bytes", name="memory"), col("Value #C", "s", name="uptime"),
                   col("Value #D", "short", name="restarts (range)", cell={"type": "color-text"},
                       thresholds=steps(("green", None), ("yellow", 1), ("red", 3)))],
        sort_by="process"), 12, 8)
    d.add(table("Containers", [
        instant(f'container_memory_working_set_bytes{{{env}}}', ref="A", format="table"),
        instant(f'time() - container_start_time_seconds{{{env}}}', ref="B", format="table")],
        description="Uptime resets on every deploy (the container is recreated).",
        transformations=[
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, "job": True, "instance": True, "id": True, "image": True, "env": True},
                "indexByName": {"project": 0, "name": 1, "Value #A": 2, "Value #B": 3},
                "renameByName": {"name": "container"}}}],
        overrides=[col("Value #A", "bytes", name="memory"), col("Value #B", "s", name="uptime")],
        sort_by="memory"), 12, 8)

    d.row("Logs and edge")
    d.add(timeseries("Errors by project", [tgt(f'sum by (project) (count_over_time({{source=~"docker|pm2", {env}, level="error"}} [$__auto]))', "{{project}}", ds=LOKI)],
                     "short", stack=True, bars=True), 12, 7)
    d.add(timeseries("Public traffic by host (Caddy)", [tgt('sum by (host) (rate({source="caddy"} != "Blackbox Exporter" [$__auto]))', "{{host}}", ds=LOKI)],
                     "reqps", stack=True, description="All hosts, prod and dev; excludes the uptime probes."), 12, 7)
    d.add(logs("Latest errors", f'{{source=~"docker|pm2", {env}, level="error"}}',
               "Tracebacks and Next.js stacks are one entry each. Expand one for its labels.", max_lines=200), 24, 12)
    d.write(IMPORT)


if __name__ == "__main__":
    box_overview()
    project()
    logs_explorer()
    edge()
    overview()
    print("wrote", ", ".join(sorted(p.name for p in [*OUT.glob("*.json"), *IMPORT.glob("*.json")])))
