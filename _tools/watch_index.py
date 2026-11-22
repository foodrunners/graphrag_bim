"""Retro ASCII progress bar monitor for running GraphRAG indexing jobs (read-only)."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import time

ROOT = Path(__file__).resolve().parents[1]

STAGES = [
    ("load_input_documents", "1. Load documents"),
    ("create_base_text_units", "2. Chunk text units"),
    ("create_final_documents", "3. Finalize documents"),
    ("extract_graph", "4. Extract graph (LLM)"),
    ("summarize", "5. Merge descriptions (LLM)"),
    ("finalize_graph", "6. Finalize graph"),
    ("create_communities", "7. Cluster communities"),
    ("create_community_reports", "8. Write cluster reports (LLM)"),
    ("generate_text_embeddings", "9. Embed vectors (Gemini)"),
]

PROGRESS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+ - INFO - .*? - (.*?) progress:\s*(\d+)/(\d+)"
)
WORKFLOW_START_RE = re.compile(r"Workflow started:\s*(\S+)")
WORKFLOW_DONE_RE = re.compile(r"Workflow completed:\s*(\S+)")


def read_index_status(scope="scdf"):
    scope_dir = ROOT / "03_graphrag" / scope
    log_file = scope_dir / "logs" / "indexing-engine.log"
    cache_dir = scope_dir / "cache"
    out_dir = scope_dir / "output"

    status = {
        "scope": scope,
        "state": "not_started",
        "current_stage": "Waiting for log...",
        "done": 0,
        "total": 0,
        "pct": 0.0,
        "last_update": "",
        "completed_workflows": [],
        "cache_files": 0,
        "cache_mb": 0.0,
        "output_files": sorted(p.name for p in out_dir.glob("*.parquet")) if out_dir.is_dir() else [],
        "error": None,
    }

    if cache_dir.is_dir():
        files = [p for p in cache_dir.rglob("*") if p.is_file()]
        status["cache_files"] = len(files)
        status["cache_mb"] = round(sum(p.stat().st_size for p in files) / (1024 * 1024), 2)

    if not log_file.is_file():
        return status

    # Read tail of log (fast even for large logs)
    raw = log_file.read_bytes()
    text = raw[-250_000:].decode("utf-8", errors="replace")
    lines = text.splitlines()

    # Keep only the latest indexing run (after last "Workflow started: load_input_documents")
    start_idx = 0
    for i, line in enumerate(lines):
        if "Workflow started: load_input_documents" in line or "Starting pipeline" in line:
            start_idx = i
    run_lines = lines[start_idx:]

    completed = set()
    active_workflow = ""
    last_label = ""
    last_done = 0
    last_total = 0
    last_ts = ""
    error_msg = None

    for line in run_lines:
        m_done = WORKFLOW_DONE_RE.search(line)
        if m_done:
            completed.add(m_done.group(1))
        m_start = WORKFLOW_START_RE.search(line)
        if m_start:
            active_workflow = m_start.group(1)
        m_prog = PROGRESS_RE.search(line)
        if m_prog:
            last_ts, label, d, t = m_prog.groups()
            last_label = label.strip()
            last_done = int(d)
            last_total = int(t)
        if " - ERROR - " in line or "Pipeline error:" in line or "RESOURCE_EXHAUSTED" in line or "Payment Required" in line:
            error_msg = line.strip()[-200:]

    if "generate_text_embeddings" in completed or any("Pipeline complete" in l for l in run_lines[-15:]):
        if not error_msg:
            status["state"] = "complete"
            status["current_stage"] = "Pipeline complete!"
            status["done"] = 1
            status["total"] = 1
            status["pct"] = 100.0
    if status["state"] != "complete":
        if error_msg:
            status["state"] = "error"
            status["error"] = error_msg
        else:
            status["state"] = "running"
        status["current_stage"] = last_label or active_workflow or "Initializing..."
        status["done"] = last_done
        status["total"] = last_total
        status["pct"] = round((last_done / last_total) * 100.0, 1) if last_total > 0 else 0.0

    status["last_update"] = last_ts or datetime.fromtimestamp(log_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    status["completed_workflows"] = sorted(completed)
    return status


def ascii_bar(pct, width=36):
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round((pct / 100.0) * width))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + f"] {pct:5.1f}%"


def render_ascii_panel(st, rate_per_sec=None):
    bar = ascii_bar(st["pct"], width=40)
    eta_str = "calculating..."
    if rate_per_sec and rate_per_sec > 0 and st["total"] > st["done"]:
        rem_sec = (st["total"] - st["done"]) / rate_per_sec
        mins, secs = divmod(int(rem_sec), 60)
        hrs, mins = divmod(mins, 60)
        eta_str = f"~{hrs}h {mins:02d}m" if hrs else f"~{mins}m {secs:02d}s"
    elif st["state"] == "complete":
        eta_str = "DONE!"

    done_wf = set(st["completed_workflows"])
    stage_low = st["current_stage"].lower()
    stage_lines = []
    for key, label in STAGES:
        is_done = key in done_wf or st["state"] == "complete"
        if key == "extract_graph" and ("summarize" in stage_low or "finalize_graph" in done_wf):
            is_done = True
        if key == "summarize" and "finalize_graph" in done_wf:
            is_done = True
        is_active = (
            not is_done
            and st["state"] == "running"
            and (
                (key == "summarize" and "summarize" in stage_low)
                or (key == "extract_graph" and "extract graph" in stage_low)
                or (key == "create_community_reports" and "community" in stage_low)
                or (key == "generate_text_embeddings" and "embed" in stage_low)
                or (key in stage_low)
            )
        )
        mark = "[DONE]" if is_done else ("[>>>>]" if is_active else "[    ]")
        stage_lines.append(f"  {mark} {label}")

    border = "+" + "=" * 66 + "+"
    rows = [
        border,
        f"|  SG BIM GRAPHRAG INDEXER MONITOR  ::  SCOPE = {st['scope'].upper():<17}|",
        border,
        f"|  Status : {st['state'].upper():<12}  Last log: {st['last_update']:<26}|",
        f"|  Step   : {st['current_stage'][:54]:<54}|",
        f"|  Bar    : {bar:<54}|",
        f"|  Items  : {st['done']:,} / {st['total']:,}   Cache: {st['cache_files']:,} files ({st['cache_mb']:.1f} MB)".ljust(67) + "|",
        f"|  Speed  : {(f'{rate_per_sec:.1f} items/s' if rate_per_sec else 'measuring...'):<18}  Stage ETA: {eta_str:<21}|",
        "+" + "-" * 66 + "+",
    ]
    for sl in stage_lines:
        rows.append(f"|{sl:<66}|")
    if st["error"]:
        rows.append("+" + "-" * 66 + "+")
        rows.append(f"|  ERROR: {st['error'][:57]:<57}|")
    rows.append(border)
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", nargs="?", default="scdf", choices=["scdf", "full", "multicode", "ifcsg"])
    parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds.")
    parser.add_argument("--once", action="store_true", help="Print one snapshot and exit.")
    parser.add_argument("--json", action="store_true", help="Print JSON status and exit.")
    args = parser.parse_args()

    if args.json:
        print(json.dumps(read_index_status(args.scope), indent=2))
        return
    if args.once:
        print(render_ascii_panel(read_index_status(args.scope)))
        return

    prev_done = None
    prev_time = None
    rate = None
    try:
        while True:
            st = read_index_status(args.scope)
            now = time.monotonic()
            if prev_done is not None and st["done"] > prev_done and (now - prev_time) > 0:
                inst = (st["done"] - prev_done) / (now - prev_time)
                rate = inst if rate is None else (0.7 * rate + 0.3 * inst)
            prev_done = st["done"]
            prev_time = now

            print("\033[2J\033[H", end="")
            print(render_ascii_panel(st, rate_per_sec=rate))
            print("\nPress Ctrl+C to close monitor (indexing keeps running in background).")
            if st["state"] in {"complete", "error"}:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitor closed.")


if __name__ == "__main__":
    main()
