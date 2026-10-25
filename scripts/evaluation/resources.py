"""Sample process-tree RSS/CPU and whole-device GPU usage; cloud hardware is excluded."""

import json, os, subprocess, threading, time
from pathlib import Path
import psutil


class Resources:
    def __init__(self, path, interval=0.5, pid=None):
        self.path = Path(path)
        self.interval = interval
        self.root = psutil.Process(pid or os.getpid())
        self.stop_event = threading.Event()
        self.rows = []
        self.label = "startup"
        self.processes = {}

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def _run(self):
        with self.path.open("w") as output:
            while not self.stop_event.is_set():
                cpu = 0
                rss = 0
                try:
                    family = [self.root, *self.root.children(recursive=True)]
                except psutil.Error:
                    family = []
                for process in family:
                    try:
                        p = self.processes.setdefault(process.pid, process)
                        cpu += p.cpu_percent()
                        rss += p.memory_info().rss
                    except psutil.Error:
                        pass
                row = {
                    "monotonic": time.monotonic(),
                    "label": self.label,
                    "rss_mib": rss / 1048576,
                    "cpu_percent_one_core": cpu,
                    "cpu_percent_machine": cpu / (psutil.cpu_count() or 1),
                    "system_ram_used_mib": psutil.virtual_memory().used / 1048576,
                }
                try:
                    raw = subprocess.check_output(
                        [
                            "nvidia-smi",
                            "--query-gpu=memory.used,utilization.gpu",
                            "--format=csv,noheader,nounits",
                        ],
                        text=True,
                        timeout=3,
                    ).strip()
                    memory, util = raw.splitlines()[0].split(",")
                    row.update(gpu_vram_mib=float(memory), gpu_util_percent=float(util))
                except (OSError, subprocess.SubprocessError, ValueError):
                    pass
                self.rows.append(row)
                output.write(json.dumps(row) + "\n")
                output.flush()
                self.stop_event.wait(self.interval)

    def summary(self, start=0, end=float("inf")):
        rows = [r for r in self.rows if start <= r["monotonic"] <= end]
        return {
            "samples": len(rows),
            "metrics": {
                k: {
                    "mean": sum(r[k] for r in rows if k in r)
                    / sum(k in r for r in rows),
                    "peak": max(r[k] for r in rows if k in r),
                }
                for k in (
                    "rss_mib",
                    "cpu_percent_one_core",
                    "cpu_percent_machine",
                    "system_ram_used_mib",
                    "gpu_vram_mib",
                    "gpu_util_percent",
                )
                if any(k in r for r in rows)
            },
            "scope": "Process-tree RSS can double-count shared pages; CPU100%=one logical core. GPU is whole-device usage. Coarse samples may miss peaks. Cloud model hardware excluded.",
        }

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)
