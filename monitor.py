"""
System Performance Analyzer - Main Entry Point

An intelligent performance monitoring tool that:
- Collects OS metrics (CPU, memory, swap, disk I/O, processes)
- Detects anomalies using statistical methods (z-scores, baselines)
- Performs root cause analysis
- Generates optimization recommendations via rule-based heuristics

Usage:
    python monitor.py                    # Start monitoring
    python monitor.py --verbose          # Verbose/debug mode
    python monitor.py --report           # Generate summary report
    python monitor.py --config path.json # Custom config file
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta

# Add project root to path
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import load_config, setup_logging
from src.collector import MetricsCollector
from src.storage import DatabaseManager
from src.analyzer import Analyzer
from src.root_cause import RootCauseAnalyzer
from src.recommender import Recommender
from src.reporter import Reporter

logger = logging.getLogger("performance_analyzer")


class PerformanceMonitor:
    """Main orchestrator for the System Performance Analyzer."""

    def __init__(self, config_path=None, verbose=False):
        # Load configuration
        self.config = load_config(config_path)

        # Setup logging
        log_level = "DEBUG" if verbose else self.config.get("display", {}).get("log_level", "INFO")
        self.logger = setup_logging(log_level)

        # Initialize components
        self.collector = MetricsCollector(self.config)
        self.db = DatabaseManager(self.config)
        self.db.initialize()

        self.analyzer = Analyzer(self.config, self.db)
        self.root_cause = RootCauseAnalyzer(self.config, self.db)
        self.recommender = Recommender(self.config, self.db)
        self.reporter = Reporter(self.config, self.db)

        # State
        self.running = False
        self.cycle_count = 0
        self.interval = self.config.get("collection", {}).get("interval_seconds", 5)

        # Scheduling
        self._last_cleanup = datetime.now()
        self._cleanup_interval = timedelta(hours=24)
        self._last_baseline_update = datetime.now()
        self._baseline_interval = timedelta(hours=1)

        logger.info("PerformanceMonitor initialized.")

    def run(self):
        """Start the main monitoring loop."""
        self.running = True

        # Display startup banner
        self.reporter.display_startup_banner(self.collector.get_system_info())

        # Register signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            while self.running:
                cycle_start = time.time()
                self.cycle_count += 1

                # ── Step 1: Collect metrics ──
                data = self.collector.collect_all()
                timestamp = data["timestamp"]
                system_metrics = data["system"]
                processes = data["processes"]

                # ── Step 2: Store in database ──
                self.db.store_system_metrics(timestamp, system_metrics)
                if processes:
                    # Store only top processes to keep DB manageable
                    top_processes = processes[:50]
                    self.db.store_process_metrics(timestamp, top_processes)

                # ── Step 3: Run anomaly detection ──
                anomalies = self.analyzer.analyze(timestamp, system_metrics)

                # ── Step 4: Root cause analysis for detected anomalies ──
                for anomaly in anomalies:
                    self.root_cause.analyze(anomaly, processes)
                    self.db.store_anomaly(anomaly)

                # ── Step 5: Generate recommendations ──
                new_recs = self.recommender.generate_recommendations(
                    timestamp, system_metrics, processes
                )

                # ── Step 6: Update baselines periodically ──
                now = datetime.now()
                if now - self._last_baseline_update >= self._baseline_interval:
                    self.analyzer.update_baselines()
                    self._last_baseline_update = now

                # ── Step 7: Display dashboard ──
                recent_recs = self.db.get_recent_recommendations(hours=24)
                self.reporter.display_dashboard(data, anomalies, recent_recs)

                # ── Step 8: Periodic cleanup ──
                if now - self._last_cleanup >= self._cleanup_interval:
                    self.db.cleanup_old_data()
                    self._last_cleanup = now

                # ── Step 9: Sleep for remainder of interval ──
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.interval - elapsed)
                if sleep_time > 0 and self.running:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}", exc_info=True)
        finally:
            self._shutdown()

    def generate_report(self, start_time=None, end_time=None):
        """Generate and display a summary report."""
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = end_time - timedelta(hours=24)

        self.reporter.generate_report(start_time, end_time)

    def _signal_handler(self, signum, frame):
        """Handle termination signals for graceful shutdown."""
        self.running = False

    def _shutdown(self):
        """Graceful shutdown."""
        self.running = False
        self.reporter.display_shutdown_summary()
        self.db.close()
        logger.info("PerformanceMonitor shut down successfully.")


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="System Performance Analyzer - Intelligent Performance Monitoring Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python monitor.py                                    # Start monitoring
  python monitor.py --verbose                          # Debug mode
  python monitor.py --report                           # 24h summary report
  python monitor.py --report --start-time "2026-02-10" # Report from date
  python monitor.py --config ./my_config.json          # Custom config
        """
    )

    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to custom configuration JSON file"
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Generate a summary report and exit (default: last 24 hours)"
    )
    parser.add_argument(
        "--start-time", type=str, default=None,
        help="Report start time (format: 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD')"
    )
    parser.add_argument(
        "--end-time", type=str, default=None,
        help="Report end time (format: 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD')"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable verbose/debug logging"
    )

    return parser.parse_args()


def parse_datetime(dt_str):
    """Parse a datetime string in various formats."""
    if dt_str is None:
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: '{dt_str}'. Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'")


def main():
    """Main entry point."""
    args = parse_args()

    try:
        monitor = PerformanceMonitor(
            config_path=args.config,
            verbose=args.verbose
        )

        if args.report:
            # Report mode: generate report and exit
            start_time = parse_datetime(args.start_time)
            end_time = parse_datetime(args.end_time)
            monitor.generate_report(start_time, end_time)
        else:
            # Monitoring mode: start the main loop
            monitor.run()

    except Exception as e:
        print(f"\nFatal error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
