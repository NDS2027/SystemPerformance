"""
Reporter & Display module for the System Performance Analyzer.
Provides real-time console dashboard with ASCII progress bars and color,
and summary report generation for specified time ranges.
"""

import logging
import os
import sys
from datetime import datetime, timedelta

from src.utils import (
    format_bytes, format_bytes_rate, format_duration,
    format_percent, make_progress_bar, is_windows
)

logger = logging.getLogger("performance_analyzer.reporter")


# ──────────────────────────── ANSI COLOR CODES ────────────────────────────────

class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"

    @classmethod
    def disable(cls):
        """Disable all colors (for non-color terminals)."""
        for attr in dir(cls):
            if attr.isupper() and not attr.startswith('_'):
                setattr(cls, attr, "")


class Reporter:
    """Handles console display and report generation."""

    def __init__(self, config, db_manager):
        self.config = config
        self.db = db_manager
        display_cfg = config.get("display", {})
        self.show_top_n = display_cfg.get("show_top_processes", 10)
        self.use_colors = display_cfg.get("use_colors", True)

        # Enable ANSI colors on Windows
        if is_windows():
            try:
                os.system('')  # Enables ANSI escape sequences on Windows 10+
            except Exception:
                pass

        if not self.use_colors:
            Colors.disable()

        self.cycle_count = 0
        logger.info("Reporter initialized.")

    # ──────────────────────── REAL-TIME DASHBOARD ─────────────────────────────

    def display_dashboard(self, data, anomalies=None, recommendations=None):
        """
        Display the real-time monitoring dashboard.
        Clears screen and renders current system state.
        """
        self.cycle_count += 1
        timestamp = data.get("timestamp", datetime.now())
        system = data.get("system", {})
        processes = data.get("processes", [])

        lines = []
        sep = "═" * 65

        # Header
        lines.append(f"\n{Colors.CYAN}{Colors.BOLD}{sep}{Colors.RESET}")
        lines.append(
            f"  {Colors.BOLD}{Colors.WHITE}SYSTEM PERFORMANCE MONITOR{Colors.RESET}"
        )
        lines.append(
            f"  Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}  "
            f"| Cycle: {self.cycle_count}"
        )
        lines.append(f"{Colors.CYAN}{sep}{Colors.RESET}")

        # System Metrics
        lines.append(f"\n{Colors.BOLD}  SYSTEM METRICS:{Colors.RESET}")

        # CPU
        cpu = system.get("cpu_percent", 0)
        cpu_color = self._severity_color(cpu, 80, 95)
        load_parts = []
        for key in ["load_avg_1min", "load_avg_5min", "load_avg_15min"]:
            val = system.get(key)
            if val is not None:
                load_parts.append(f"{val:.1f}")
        load_str = f"  Load: {', '.join(load_parts)}" if load_parts else ""
        lines.append(
            f"  {Colors.BOLD}CPU:{Colors.RESET}     "
            f"{cpu_color}{cpu:5.1f}%{Colors.RESET}  "
            f"{make_progress_bar(cpu)}{load_str}"
        )

        # Memory
        mem_pct = system.get("memory_percent", 0)
        mem_used = system.get("memory_used", 0)
        mem_total = system.get("memory_total", 0)
        mem_color = self._severity_color(mem_pct, 80, 95)
        lines.append(
            f"  {Colors.BOLD}Memory:{Colors.RESET}  "
            f"{mem_color}{mem_pct:5.1f}%{Colors.RESET}  "
            f"{make_progress_bar(mem_pct)} "
            f"{format_bytes(mem_used)} / {format_bytes(mem_total)}"
        )

        # Swap
        swap_pct = system.get("swap_percent", 0)
        swap_used = system.get("swap_used", 0)
        swap_total = system.get("swap_total", 0)
        swap_color = self._severity_color(swap_pct, 50, 80)
        lines.append(
            f"  {Colors.BOLD}Swap:{Colors.RESET}    "
            f"{swap_color}{swap_pct:5.1f}%{Colors.RESET}  "
            f"{make_progress_bar(swap_pct)} "
            f"{format_bytes(swap_used)} / {format_bytes(swap_total)}"
        )

        # Disk I/O
        read_rate = system.get("disk_read_rate", 0)
        write_rate = system.get("disk_write_rate", 0)
        lines.append(
            f"  {Colors.BOLD}Disk:{Colors.RESET}    "
            f"Read: {format_bytes_rate(read_rate)}  "
            f"Write: {format_bytes_rate(write_rate)}"
        )

        # Disk Usage
        disk_pct = system.get("disk_percent", 0)
        disk_used = system.get("disk_used", 0)
        disk_total = system.get("disk_total", 0)
        disk_color = self._severity_color(disk_pct, 80, 95)
        lines.append(
            f"  {Colors.BOLD}Storage:{Colors.RESET} "
            f"{disk_color}{disk_pct:5.1f}%{Colors.RESET}  "
            f"{make_progress_bar(disk_pct)} "
            f"{format_bytes(disk_used)} / {format_bytes(disk_total)}"
        )

        # Top Processes
        lines.append(f"\n{Colors.BOLD}  TOP PROCESSES (by CPU):{Colors.RESET}")
        lines.append(
            f"  {Colors.DIM}{'PID':>7}  {'Name':<20} {'CPU%':>6}  "
            f"{'Memory':>10}  {'User':<15}{Colors.RESET}"
        )
        lines.append(f"  {Colors.DIM}{'─' * 62}{Colors.RESET}")

        for proc in processes[:self.show_top_n]:
            pid = proc.get("pid", 0)
            name = (proc.get("name") or "unknown")[:20]
            proc_cpu = proc.get("cpu_percent", 0) or 0
            mem_rss = proc.get("memory_rss", 0) or 0
            user = (proc.get("username") or "unknown")[:15]

            cpu_c = self._severity_color(proc_cpu, 50, 90)
            lines.append(
                f"  {pid:>7}  {name:<20} "
                f"{cpu_c}{proc_cpu:5.1f}%{Colors.RESET}  "
                f"{format_bytes(mem_rss):>10}  {user:<15}"
            )

        # Active Alerts
        if anomalies:
            lines.append(f"\n{Colors.BOLD}  ACTIVE ALERTS:{Colors.RESET}")
            for a in anomalies[:5]:
                sev = a.get("severity", "medium")
                sev_color = self._alert_color(sev)
                icon = "🔴" if sev in ("critical", "high") else "⚠"
                desc = a.get("description", "Unknown anomaly")
                lines.append(
                    f"  {icon} {sev_color}{sev.upper()}{Colors.RESET}: {desc}"
                )

        # Recommendations
        recent_recs = recommendations or []
        if recent_recs:
            lines.append(f"\n{Colors.BOLD}  RECENT RECOMMENDATIONS:{Colors.RESET}")
            for r in recent_recs[:5]:
                pri = r.get("priority", "medium")
                pri_color = self._alert_color(pri)
                rec_type = r.get("recommendation_type", "unknown")
                impact = r.get("estimated_impact", "")
                lines.append(
                    f"  {pri_color}[{pri.upper()}]{Colors.RESET} "
                    f"{rec_type.replace('_', ' ').title()}"
                    f" - {impact}" if impact else ""
                )

        # Footer
        lines.append(f"\n{Colors.CYAN}{sep}{Colors.RESET}")
        lines.append(
            f"  {Colors.DIM}Press Ctrl+C to stop  |  "
            f"DB size: {self.db.get_database_size():.1f} MB{Colors.RESET}"
        )
        lines.append(f"{Colors.CYAN}{sep}{Colors.RESET}")

        # Clear and print
        self._clear_screen()
        output = "\n".join(lines)
        print(output)

    # ──────────────────────── SUMMARY REPORT ──────────────────────────────────

    def generate_report(self, start_time=None, end_time=None):
        """Generate a summary report for a time range."""
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = end_time - timedelta(hours=24)

        sep = "═" * 65
        lines = []

        lines.append(f"\n{sep}")
        lines.append("  PERFORMANCE SUMMARY REPORT")
        lines.append(
            f"  Period: {start_time.strftime('%Y-%m-%d %H:%M:%S')} to "
            f"{end_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(sep)

        # Query data
        metrics = self.db.get_system_metrics(start_time, end_time)

        if not metrics:
            lines.append("\n  No data available for the specified time range.")
            lines.append(f"\n{sep}")
            return "\n".join(lines)

        # System overview
        lines.append("\n  SYSTEM OVERVIEW:")

        # CPU stats
        cpu_values = [m.get("cpu_percent", 0) for m in metrics if m.get("cpu_percent") is not None]
        if cpu_values:
            lines.append(f"\n    CPU Usage:")
            lines.append(f"      Average: {sum(cpu_values)/len(cpu_values):.1f}%")
            max_cpu = max(cpu_values)
            max_cpu_idx = cpu_values.index(max_cpu)
            lines.append(
                f"      Peak: {max_cpu:.1f}% at {metrics[max_cpu_idx].get('timestamp', 'N/A')}"
            )
            lines.append(f"      Minimum: {min(cpu_values):.1f}%")

        # Memory stats
        mem_values = [m.get("memory_percent", 0) for m in metrics if m.get("memory_percent") is not None]
        mem_used_values = [m.get("memory_used", 0) for m in metrics if m.get("memory_used") is not None]
        if mem_values:
            avg_mem_used = sum(mem_used_values) / len(mem_used_values) if mem_used_values else 0
            lines.append(f"\n    Memory Usage:")
            lines.append(
                f"      Average: {format_bytes(avg_mem_used)} "
                f"({sum(mem_values)/len(mem_values):.1f}%)"
            )
            max_mem = max(mem_values)
            max_mem_idx = mem_values.index(max_mem)
            lines.append(
                f"      Peak: {max_mem:.1f}% at {metrics[max_mem_idx].get('timestamp', 'N/A')}"
            )

            # Memory trend
            if len(mem_values) > 10:
                first_quarter = sum(mem_values[:len(mem_values)//4]) / (len(mem_values)//4)
                last_quarter = sum(mem_values[-len(mem_values)//4:]) / (len(mem_values)//4)
                trend = last_quarter - first_quarter
                trend_dir = "↑" if trend > 0 else "↓"
                lines.append(f"      Trend: {trend_dir} {abs(trend):.1f}% change over period")

        # Disk I/O stats
        read_deltas = [m.get("disk_read_bytes_delta", 0) for m in metrics if m.get("disk_read_bytes_delta") is not None]
        write_deltas = [m.get("disk_write_bytes_delta", 0) for m in metrics if m.get("disk_write_bytes_delta") is not None]
        if read_deltas:
            lines.append(f"\n    Disk I/O:")
            lines.append(f"      Total read: {format_bytes(sum(read_deltas))}")
            lines.append(f"      Total written: {format_bytes(sum(write_deltas))}")

        # Anomalies
        anomalies = self.db.get_recent_anomalies(
            hours=int((end_time - start_time).total_seconds() / 3600) or 24
        )
        lines.append(f"\n  ANOMALIES DETECTED: {len(anomalies)}")
        if anomalies:
            type_counts = {}
            for a in anomalies:
                t = a.get("anomaly_type", "unknown")
                type_counts[t] = type_counts.get(t, 0) + 1
            for atype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
                lines.append(f"    {atype.replace('_', ' ').title()}: {count} occurrences")

        # Recommendations
        recs = self.db.get_active_recommendations()
        lines.append(f"\n  ACTIVE RECOMMENDATIONS: {len(recs)}")
        for r in recs[:5]:
            pri = r.get("priority", "medium")
            rec_type = r.get("recommendation_type", "unknown")
            lines.append(f"    [{pri.upper()}] {rec_type.replace('_', ' ').title()}")

        # Database stats
        db_size = self.db.get_database_size()
        row_counts = self.db.get_row_counts()
        lines.append(f"\n  DATABASE STATS:")
        lines.append(f"    Size: {db_size:.1f} MB")
        lines.append(f"    System snapshots: {row_counts.get('system_metrics', 0):,}")
        lines.append(f"    Process records: {row_counts.get('process_metrics', 0):,}")

        lines.append(f"\n{sep}")

        report = "\n".join(lines)
        print(report)
        return report

    # ──────────────────────── STARTUP BANNER ──────────────────────────────────

    def display_startup_banner(self, system_info):
        """Display startup information."""
        sep = "═" * 65
        print(f"\n{Colors.CYAN}{Colors.BOLD}{sep}{Colors.RESET}")
        print(f"  {Colors.BOLD}{Colors.WHITE}SYSTEM PERFORMANCE ANALYZER{Colors.RESET}")
        print(f"  {Colors.DIM}Intelligent Performance Monitoring Tool{Colors.RESET}")
        print(f"{Colors.CYAN}{sep}{Colors.RESET}")
        print(f"  Platform:  {system_info.get('platform', 'Unknown')} "
              f"{system_info.get('platform_version', '')[:30]}")
        print(f"  Processor: {system_info.get('processor', 'Unknown')[:45]}")
        print(f"  CPU Cores: {system_info.get('cpu_count_physical', '?')} physical, "
              f"{system_info.get('cpu_count_logical', '?')} logical")
        print(f"  Interval:  {self.config.get('collection', {}).get('interval_seconds', 5)} seconds")
        print(f"{Colors.CYAN}{sep}{Colors.RESET}")
        print(f"  {Colors.GREEN}Starting monitoring... Press Ctrl+C to stop.{Colors.RESET}\n")

    def display_shutdown_summary(self):
        """Display summary on graceful shutdown."""
        sep = "═" * 65
        print(f"\n{Colors.YELLOW}{sep}{Colors.RESET}")
        print(f"  {Colors.BOLD}Shutting down...{Colors.RESET}")
        print(f"  Total monitoring cycles: {self.cycle_count}")

        db_size = self.db.get_database_size()
        row_counts = self.db.get_row_counts()
        print(f"  Database size: {db_size:.1f} MB")
        print(f"  Data points collected: {row_counts.get('system_metrics', 0):,}")
        print(f"  Anomalies detected: {row_counts.get('anomalies', 0):,}")
        print(f"  Recommendations: {row_counts.get('recommendations', 0):,}")
        print(f"{Colors.YELLOW}{sep}{Colors.RESET}")
        print(f"  {Colors.GREEN}Goodbye!{Colors.RESET}\n")

    # ──────────────────────── HELPERS ─────────────────────────────────────────

    def _clear_screen(self):
        """Clear the terminal screen."""
        if is_windows():
            os.system('cls')
        else:
            print("\033[2J\033[H", end="")

    def _severity_color(self, value, warn_threshold, crit_threshold):
        """Return color code based on value and thresholds."""
        if value >= crit_threshold:
            return Colors.RED
        elif value >= warn_threshold:
            return Colors.YELLOW
        else:
            return Colors.GREEN

    def _alert_color(self, severity):
        """Return color code based on severity string."""
        colors = {
            "critical": Colors.RED + Colors.BOLD,
            "high": Colors.RED,
            "medium": Colors.YELLOW,
            "low": Colors.BLUE,
        }
        return colors.get(severity, Colors.WHITE)
