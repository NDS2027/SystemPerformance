"""
Root Cause Analysis Engine for the System Performance Analyzer.
Reconstructs timelines around anomalies, identifies responsible processes,
traces process trees, and analyzes I/O bottlenecks.
"""

import json
import logging
from datetime import datetime, timedelta

from src.utils import format_bytes, format_percent, safe_div

logger = logging.getLogger("performance_analyzer.root_cause")


class RootCauseAnalyzer:
    """Performs root cause analysis when anomalies are detected."""

    def __init__(self, config, db_manager):
        self.config = config
        self.db = db_manager
        logger.info("RootCauseAnalyzer initialized.")

    def analyze(self, anomaly, current_processes=None):
        """
        Perform root cause analysis for a detected anomaly.
        Returns the anomaly dict with 'root_cause' field populated.
        """
        root_cause = {
            "timeline": None,
            "top_contributors": [],
            "process_tree": None,
            "io_analysis": None,
            "summary": "",
        }

        try:
            anomaly_type = anomaly.get("anomaly_type", "")
            timestamp = anomaly.get("timestamp")

            # 1. Timeline reconstruction
            root_cause["timeline"] = self._reconstruct_timeline(
                timestamp, anomaly.get("metric_name")
            )

            # 2. Process contribution analysis
            if current_processes:
                contributors = self._analyze_process_contributions(
                    anomaly_type, timestamp, current_processes
                )
                root_cause["top_contributors"] = contributors

                # 3. Process tree for top contributor
                if contributors:
                    top_pid = contributors[0].get("pid")
                    if top_pid and current_processes:
                        tree = self._build_process_tree(top_pid, current_processes)
                        root_cause["process_tree"] = tree

            # 4. I/O analysis for I/O-related anomalies
            if anomaly_type in ("io_bottleneck", "swap_thrashing"):
                root_cause["io_analysis"] = self._analyze_io(
                    timestamp, current_processes
                )

            # 5. Generate summary
            root_cause["summary"] = self._generate_summary(anomaly, root_cause)

        except Exception as e:
            logger.error(f"Error in root cause analysis: {e}")
            root_cause["summary"] = f"Root cause analysis failed: {e}"

        anomaly["root_cause"] = root_cause
        return anomaly

    def _reconstruct_timeline(self, timestamp, metric_name):
        """
        Reconstruct a timeline of metric values around the anomaly.
        Look at 5 samples before and 5 after (±25 seconds at 5s intervals).
        """
        if not metric_name:
            return None

        try:
            start = timestamp - timedelta(seconds=30)
            end = timestamp + timedelta(seconds=30)
            metrics = self.db.get_system_metrics(start, end)

            if not metrics:
                return None

            timeline = []
            for m in metrics:
                val = m.get(metric_name)
                ts = m.get("timestamp")
                if val is not None:
                    timeline.append({
                        "timestamp": ts,
                        "value": val,
                    })

            return timeline

        except Exception as e:
            logger.debug(f"Error reconstructing timeline: {e}")
            return None

    def _analyze_process_contributions(self, anomaly_type, timestamp, current_processes):
        """
        Identify which processes are contributing most to the anomaly.
        Compare current process state to a baseline (30 seconds ago).
        """
        contributors = []

        # Determine sort key based on anomaly type
        if "cpu" in anomaly_type:
            sort_key = "cpu_percent"
        elif "memory" in anomaly_type:
            sort_key = "memory_rss"
        elif "io" in anomaly_type or "swap" in anomaly_type:
            sort_key = "memory_rss"  # Use memory as fallback
        else:
            sort_key = "cpu_percent"

        # Get previous process state for delta calculation
        prev_timestamp = timestamp - timedelta(seconds=30)
        prev_processes = self.db.get_process_metrics_at(prev_timestamp)
        prev_map = {}
        for p in prev_processes:
            prev_map[p.get("pid")] = p

        # Calculate contributions
        for proc in current_processes[:20]:  # Top 20
            pid = proc.get("pid")
            name = proc.get("name", "unknown")

            current_val = proc.get(sort_key, 0) or 0
            prev_proc = prev_map.get(pid, {})
            prev_val = prev_proc.get(sort_key, 0) or 0

            delta = current_val - prev_val
            is_new = pid not in prev_map

            contributor = {
                "pid": pid,
                "name": name,
                "current_value": current_val,
                "previous_value": prev_val,
                "delta": delta,
                "is_new_process": is_new,
                "metric": sort_key,
            }

            # Add formatted info
            if sort_key == "cpu_percent":
                contributor["display"] = f"{name} (PID {pid}): {current_val:.1f}% CPU"
                if is_new:
                    contributor["display"] += " (new process)"
                elif delta > 1:
                    contributor["display"] += f" (+{delta:.1f}%)"
            elif sort_key == "memory_rss":
                contributor["display"] = (
                    f"{name} (PID {pid}): {format_bytes(current_val)} memory"
                )
                if is_new:
                    contributor["display"] += " (new process)"
                elif delta > 1024 * 1024:
                    contributor["display"] += f" (+{format_bytes(delta)})"

            contributors.append(contributor)

        # Sort by absolute current value (descending)
        contributors.sort(key=lambda c: abs(c["current_value"]), reverse=True)
        return contributors[:10]  # Top 10

    def _build_process_tree(self, target_pid, current_processes):
        """
        Build the process tree (parent chain) for a given PID.
        Traces from the target process up to init/root.
        """
        proc_map = {}
        for p in current_processes:
            proc_map[p.get("pid")] = p

        tree = []
        visited = set()
        current_pid = target_pid

        while current_pid and current_pid not in visited:
            visited.add(current_pid)
            proc = proc_map.get(current_pid)
            if proc:
                tree.append({
                    "pid": current_pid,
                    "name": proc.get("name", "unknown"),
                    "cpu_percent": proc.get("cpu_percent", 0),
                    "memory_rss": proc.get("memory_rss", 0),
                })
                current_pid = proc.get("ppid")
                if current_pid == 0 or current_pid == current_pid:
                    break
            else:
                break

        tree.reverse()  # Root first
        return tree

    def _analyze_io(self, timestamp, current_processes):
        """
        Analyze I/O patterns for processes.
        Identify high I/O consumers and classify their I/O patterns.
        """
        if not current_processes:
            return None

        io_analysis = {
            "top_io_processes": [],
            "patterns": [],
        }

        # Find processes with I/O data
        io_procs = []
        for p in current_processes:
            read_bytes = p.get("io_read_bytes")
            write_bytes = p.get("io_write_bytes")
            if read_bytes is not None and write_bytes is not None:
                total_io = (read_bytes or 0) + (write_bytes or 0)
                io_procs.append({
                    "pid": p.get("pid"),
                    "name": p.get("name"),
                    "io_read_bytes": read_bytes,
                    "io_write_bytes": write_bytes,
                    "io_read_count": p.get("io_read_count", 0),
                    "io_write_count": p.get("io_write_count", 0),
                    "total_io": total_io,
                })

        # Sort by total I/O
        io_procs.sort(key=lambda x: x["total_io"], reverse=True)
        io_analysis["top_io_processes"] = io_procs[:10]

        # Classify patterns for top I/O processes
        for proc in io_procs[:5]:
            read_count = proc.get("io_read_count", 0) or 0
            read_bytes = proc.get("io_read_bytes", 0) or 0

            if read_count > 0:
                avg_read_size = read_bytes / read_count
                name = proc.get("name", "").lower()

                pattern = {
                    "pid": proc["pid"],
                    "name": proc["name"],
                    "avg_read_size": avg_read_size,
                }

                if avg_read_size < 32 * 1024:
                    pattern["classification"] = "small random reads (inefficient)"
                    if any(db in name for db in ["postgres", "mysql", "mongod", "mariadb"]):
                        pattern["likely_issue"] = "Missing database index (table scan)"
                    elif any(b in name for b in ["chrome", "firefox", "edge"]):
                        pattern["likely_issue"] = "Browser cache thrashing"
                    else:
                        pattern["likely_issue"] = "Fragmented I/O pattern"
                elif avg_read_size > 1024 * 1024:
                    pattern["classification"] = "large sequential reads (efficient)"
                    pattern["likely_issue"] = None
                else:
                    pattern["classification"] = "mixed I/O pattern"
                    pattern["likely_issue"] = None

                io_analysis["patterns"].append(pattern)

        return io_analysis

    def _generate_summary(self, anomaly, root_cause):
        """Generate a human-readable summary of the root cause analysis."""
        parts = []
        anomaly_type = anomaly.get("anomaly_type", "unknown")
        severity = anomaly.get("severity", "unknown")

        parts.append(
            f"[{severity.upper()}] {anomaly.get('description', 'Anomaly detected')}"
        )

        # Add top contributors
        contributors = root_cause.get("top_contributors", [])
        if contributors:
            parts.append("\nTop contributors:")
            for i, c in enumerate(contributors[:5], 1):
                parts.append(f"  {i}. {c.get('display', 'Unknown')}")

            # Calculate what top 3 account for
            if "cpu" in anomaly_type:
                total = sum(c.get("current_value", 0) for c in contributors[:3])
                parts.append(f"\n  Top 3 processes account for {total:.1f}% CPU")
            elif "memory" in anomaly_type:
                total = sum(c.get("current_value", 0) for c in contributors[:3])
                parts.append(
                    f"\n  Top 3 processes use {format_bytes(total)} memory"
                )

        # Add process tree info
        tree = root_cause.get("process_tree")
        if tree and len(tree) > 1:
            chain = " → ".join(
                f"{n['name']}({n['pid']})" for n in tree
            )
            parts.append(f"\nProcess chain: {chain}")

        # Add I/O analysis
        io_info = root_cause.get("io_analysis")
        if io_info:
            patterns = io_info.get("patterns", [])
            for p in patterns:
                if p.get("likely_issue"):
                    parts.append(
                        f"\nI/O issue: {p['name']} - {p['likely_issue']} "
                        f"({p['classification']})"
                    )

        return "\n".join(parts)
