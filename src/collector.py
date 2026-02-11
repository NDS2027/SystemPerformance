"""
Metrics Collection Engine for the System Performance Analyzer.
Gathers system-wide and process-level metrics from the OS using psutil.
"""

import logging
import platform
import time
from datetime import datetime

import psutil

from src.utils import is_windows, is_linux

logger = logging.getLogger("performance_analyzer.collector")


class MetricsCollector:
    """Collects system and process metrics using psutil."""

    def __init__(self, config):
        self.config = config
        self.collection_config = config.get("collection", {})
        self.interval = self.collection_config.get("interval_seconds", 5)
        self.enable_process = self.collection_config.get("enable_process_metrics", True)
        self.enable_io = self.collection_config.get("enable_io_metrics", True)
        self.max_processes = self.collection_config.get("max_processes_tracked", 500)

        # Previous I/O counters for delta calculations
        self._prev_disk_io = None
        self._prev_disk_io_time = None

        # System info (static)
        self.cpu_count_logical = psutil.cpu_count(logical=True)
        self.cpu_count_physical = psutil.cpu_count(logical=False)
        self.system_info = {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "processor": platform.processor(),
            "cpu_count_logical": self.cpu_count_logical,
            "cpu_count_physical": self.cpu_count_physical,
        }

        logger.info(
            f"MetricsCollector initialized | "
            f"Platform: {self.system_info['platform']} | "
            f"CPUs: {self.cpu_count_logical} logical, {self.cpu_count_physical} physical"
        )

    def collect_all(self):
        """
        Collect all metrics (system + processes) in one cycle.
        Returns a dict with 'timestamp', 'system', and 'processes' keys.
        """
        timestamp = datetime.now()

        system_metrics = self.collect_system_metrics()
        process_metrics = []
        if self.enable_process:
            process_metrics = self.collect_process_metrics()

        return {
            "timestamp": timestamp,
            "system": system_metrics,
            "processes": process_metrics,
        }

    def collect_system_metrics(self):
        """Collect system-wide CPU, memory, swap, disk I/O, and disk usage."""
        metrics = {}

        # --- CPU ---
        try:
            metrics["cpu_percent"] = psutil.cpu_percent(interval=1)
            metrics["per_core_cpu_percent"] = psutil.cpu_percent(interval=0, percpu=True)
            metrics["cpu_count_logical"] = self.cpu_count_logical
            metrics["cpu_count_physical"] = self.cpu_count_physical

            try:
                cpu_freq = psutil.cpu_freq()
                metrics["cpu_freq_current"] = cpu_freq.current if cpu_freq else None
            except Exception:
                metrics["cpu_freq_current"] = None

            # Load average (Unix only)
            try:
                load_avg = psutil.getloadavg()
                metrics["load_avg_1min"] = load_avg[0]
                metrics["load_avg_5min"] = load_avg[1]
                metrics["load_avg_15min"] = load_avg[2]
            except (AttributeError, OSError):
                metrics["load_avg_1min"] = None
                metrics["load_avg_5min"] = None
                metrics["load_avg_15min"] = None
        except Exception as e:
            logger.error(f"Error collecting CPU metrics: {e}")

        # --- Memory ---
        try:
            vm = psutil.virtual_memory()
            metrics["memory_total"] = vm.total
            metrics["memory_available"] = vm.available
            metrics["memory_used"] = vm.used
            metrics["memory_percent"] = vm.percent
            metrics["memory_cached"] = getattr(vm, 'cached', None)
            metrics["memory_buffers"] = getattr(vm, 'buffers', None)
        except Exception as e:
            logger.error(f"Error collecting memory metrics: {e}")

        # --- Swap ---
        try:
            swap = psutil.swap_memory()
            metrics["swap_total"] = swap.total
            metrics["swap_used"] = swap.used
            metrics["swap_percent"] = swap.percent
        except Exception as e:
            logger.error(f"Error collecting swap metrics: {e}")

        # --- Disk I/O (delta calculation) ---
        try:
            if self.enable_io:
                current_io = psutil.disk_io_counters(perdisk=False)
                current_time = time.time()

                if current_io and self._prev_disk_io:
                    time_delta = current_time - self._prev_disk_io_time
                    if time_delta > 0:
                        metrics["disk_read_bytes_delta"] = int(
                            (current_io.read_bytes - self._prev_disk_io.read_bytes)
                        )
                        metrics["disk_write_bytes_delta"] = int(
                            (current_io.write_bytes - self._prev_disk_io.write_bytes)
                        )
                        metrics["disk_read_ops_delta"] = int(
                            (current_io.read_count - self._prev_disk_io.read_count)
                        )
                        metrics["disk_write_ops_delta"] = int(
                            (current_io.write_count - self._prev_disk_io.write_count)
                        )
                        # Bytes per second (for display)
                        metrics["disk_read_rate"] = metrics["disk_read_bytes_delta"] / time_delta
                        metrics["disk_write_rate"] = metrics["disk_write_bytes_delta"] / time_delta
                    else:
                        metrics["disk_read_bytes_delta"] = 0
                        metrics["disk_write_bytes_delta"] = 0
                        metrics["disk_read_ops_delta"] = 0
                        metrics["disk_write_ops_delta"] = 0
                        metrics["disk_read_rate"] = 0
                        metrics["disk_write_rate"] = 0
                else:
                    metrics["disk_read_bytes_delta"] = 0
                    metrics["disk_write_bytes_delta"] = 0
                    metrics["disk_read_ops_delta"] = 0
                    metrics["disk_write_ops_delta"] = 0
                    metrics["disk_read_rate"] = 0
                    metrics["disk_write_rate"] = 0

                if current_io:
                    self._prev_disk_io = current_io
                    self._prev_disk_io_time = current_time
        except Exception as e:
            logger.error(f"Error collecting disk I/O metrics: {e}")

        # --- Disk Usage ---
        try:
            if is_windows():
                disk = psutil.disk_usage('C:\\')
            else:
                disk = psutil.disk_usage('/')
            metrics["disk_total"] = disk.total
            metrics["disk_used"] = disk.used
            metrics["disk_free"] = disk.free
            metrics["disk_percent"] = disk.percent
        except Exception as e:
            logger.error(f"Error collecting disk usage: {e}")

        return metrics

    def collect_process_metrics(self):
        """
        Collect per-process metrics for all running processes.
        Returns a list of dicts, one per process.
        """
        processes = []
        count = 0

        attrs = [
            'pid', 'name', 'username', 'status', 'cpu_percent',
            'memory_info', 'memory_percent', 'num_threads',
            'ppid', 'create_time'
        ]
        if self.enable_io:
            attrs.append('io_counters')

        for proc in psutil.process_iter(attrs=attrs):
            if count >= self.max_processes:
                break
            try:
                info = proc.info
                proc_data = {
                    "pid": info.get('pid'),
                    "name": info.get('name', 'unknown'),
                    "username": info.get('username', 'unknown'),
                    "status": info.get('status', 'unknown'),
                    "cpu_percent": info.get('cpu_percent', 0.0),
                    "memory_percent": info.get('memory_percent', 0.0),
                    "num_threads": info.get('num_threads', 0),
                    "ppid": info.get('ppid', 0),
                    "create_time": info.get('create_time'),
                }

                # Memory info
                mem_info = info.get('memory_info')
                if mem_info:
                    proc_data["memory_rss"] = mem_info.rss
                    proc_data["memory_vms"] = mem_info.vms
                else:
                    proc_data["memory_rss"] = 0
                    proc_data["memory_vms"] = 0

                # I/O counters
                if self.enable_io:
                    io_counters = info.get('io_counters')
                    if io_counters:
                        proc_data["io_read_bytes"] = io_counters.read_bytes
                        proc_data["io_write_bytes"] = io_counters.write_bytes
                        proc_data["io_read_count"] = io_counters.read_count
                        proc_data["io_write_count"] = io_counters.write_count
                    else:
                        proc_data["io_read_bytes"] = None
                        proc_data["io_write_bytes"] = None
                        proc_data["io_read_count"] = None
                        proc_data["io_write_count"] = None

                processes.append(proc_data)
                count += 1

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception as e:
                logger.debug(f"Error collecting process metrics: {e}")
                continue

        # Sort by CPU percent descending
        processes.sort(key=lambda p: p.get("cpu_percent", 0), reverse=True)
        return processes

    def get_system_info(self):
        """Return static system information."""
        return self.system_info
