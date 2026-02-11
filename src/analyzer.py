"""
Statistical Analysis & Anomaly Detection Engine for the System Performance Analyzer.
Calculates context-based baselines, detects anomalies using z-scores,
and identifies trends like memory leaks and swap thrashing.
"""

import logging
from datetime import datetime, timedelta

import numpy as np

from src.utils import get_time_context

logger = logging.getLogger("performance_analyzer.analyzer")


class Analyzer:
    """Performs statistical analysis, baseline calculation, and anomaly detection."""

    # Metrics to monitor for anomalies
    MONITORED_METRICS = [
        "cpu_percent",
        "memory_percent",
        "swap_percent",
    ]

    def __init__(self, config, db_manager):
        self.config = config
        self.db = db_manager

        analysis_cfg = config.get("analysis", {})
        self.baseline_history_days = analysis_cfg.get("baseline_history_days", 7)
        self.severity_levels = analysis_cfg.get("anomaly_severity_levels", {
            "low": 1.5, "medium": 2.0, "high": 2.5, "critical": 3.0
        })

        # Cache baselines in memory
        self._baselines_cache = {}
        self._last_baseline_update = None
        self._baseline_update_interval = timedelta(hours=1)

        # Memory leak detection state
        self._memory_history = []  # list of (timestamp, memory_used)
        self._memory_history_max_age = timedelta(hours=2)

        # Swap thrashing detection state
        self._swap_history = []  # list of (timestamp, swap_used)
        self._swap_history_max_age = timedelta(minutes=30)

        self._load_baselines_from_db()
        logger.info("Analyzer initialized.")

    def _load_baselines_from_db(self):
        """Load existing baselines from database into cache."""
        try:
            baselines = self.db.get_all_baselines()
            for b in baselines:
                key = (b["metric_name"], b["context"])
                self._baselines_cache[key] = {
                    "mean": b["mean_value"],
                    "std_dev": b["std_dev"],
                    "min": b["min_value"],
                    "max": b["max_value"],
                    "count": b["sample_count"],
                }
            logger.info(f"Loaded {len(self._baselines_cache)} baselines from database.")
        except Exception as e:
            logger.warning(f"Could not load baselines from DB: {e}")

    # ──────────────────────── BASELINE CALCULATION ────────────────────────────

    def update_baselines(self, force=False):
        """
        Recalculate baselines for all monitored metrics and all contexts.
        Only runs if enough time has passed since last update, unless forced.
        """
        now = datetime.now()
        if not force and self._last_baseline_update:
            if now - self._last_baseline_update < self._baseline_update_interval:
                return

        contexts = [
            "weekday_morning", "weekday_afternoon", "weekday_evening",
            "weekday_night", "weekend_day", "weekend_night"
        ]

        updated = 0
        for metric in self.MONITORED_METRICS:
            for context in contexts:
                try:
                    values = self.db.get_metric_values_for_context(
                        metric, context, days=self.baseline_history_days
                    )
                    if len(values) < 10:
                        continue  # Not enough data

                    arr = np.array(values)
                    stats = {
                        "mean": float(np.mean(arr)),
                        "std_dev": float(np.std(arr)),
                        "min": float(np.min(arr)),
                        "max": float(np.max(arr)),
                        "count": len(values),
                    }

                    # Ensure std_dev is never zero (avoid division by zero)
                    if stats["std_dev"] < 0.01:
                        stats["std_dev"] = 0.01

                    # Update DB and cache
                    self.db.update_baseline(metric, context, stats)
                    self._baselines_cache[(metric, context)] = stats
                    updated += 1

                except Exception as e:
                    logger.debug(f"Error updating baseline {metric}/{context}: {e}")

        self._last_baseline_update = now
        if updated > 0:
            logger.info(f"Updated {updated} baselines.")

    def get_baseline(self, metric_name, context=None):
        """Get baseline from cache for a metric and context."""
        if context is None:
            context = get_time_context()
        return self._baselines_cache.get((metric_name, context))

    # ──────────────────────── ANOMALY DETECTION ───────────────────────────────

    def analyze(self, timestamp, system_metrics):
        """
        Run anomaly detection on the current system metrics.
        Returns a list of detected anomalies (may be empty).
        """
        anomalies = []
        context = get_time_context(timestamp)

        for metric in self.MONITORED_METRICS:
            value = system_metrics.get(metric)
            if value is None:
                continue

            baseline = self.get_baseline(metric, context)
            if baseline is None:
                continue  # No baseline yet

            anomaly = self._check_zscore(timestamp, metric, value, baseline, context)
            if anomaly:
                anomalies.append(anomaly)

        # Trend-based detections
        trend_anomalies = self._detect_trends(timestamp, system_metrics)
        anomalies.extend(trend_anomalies)

        return anomalies

    def _check_zscore(self, timestamp, metric_name, value, baseline, context):
        """
        Calculate z-score and classify severity.
        Returns anomaly dict if severity >= medium, else None.
        """
        mean = baseline["mean"]
        std_dev = baseline["std_dev"]

        z_score = (value - mean) / std_dev

        severity = self._classify_severity(abs(z_score))
        if severity in ("normal", "low"):
            return None  # Not anomalous enough

        # Determine anomaly type
        anomaly_type = self._get_anomaly_type(metric_name, z_score)

        description = (
            f"{metric_name.replace('_', ' ').title()} at {value:.1f}% is "
            f"{abs(z_score):.1f} std devs {'above' if z_score > 0 else 'below'} "
            f"normal for {context.replace('_', ' ')} "
            f"(typical: {mean:.1f}% ± {std_dev:.1f}%)"
        )

        anomaly = {
            "timestamp": timestamp,
            "anomaly_type": anomaly_type,
            "severity": severity,
            "metric_name": metric_name,
            "metric_value": value,
            "baseline_mean": mean,
            "baseline_stddev": std_dev,
            "z_score": z_score,
            "description": description,
            "root_cause": None,
        }

        logger.warning(f"ANOMALY [{severity.upper()}]: {description}")
        return anomaly

    def _classify_severity(self, abs_z_score):
        """Map absolute z-score to severity level."""
        critical = self.severity_levels.get("critical", 3.0)
        high = self.severity_levels.get("high", 2.5)
        medium = self.severity_levels.get("medium", 2.0)
        low = self.severity_levels.get("low", 1.5)

        if abs_z_score >= critical:
            return "critical"
        elif abs_z_score >= high:
            return "high"
        elif abs_z_score >= medium:
            return "medium"
        elif abs_z_score >= low:
            return "low"
        else:
            return "normal"

    def _get_anomaly_type(self, metric_name, z_score):
        """Determine the anomaly type based on metric and z-score direction."""
        type_map = {
            "cpu_percent": "cpu_spike" if z_score > 0 else "cpu_drop",
            "memory_percent": "memory_pressure" if z_score > 0 else "memory_drop",
            "swap_percent": "swap_pressure" if z_score > 0 else "swap_drop",
        }
        return type_map.get(metric_name, "unknown_anomaly")

    # ──────────────────────── TREND DETECTION ─────────────────────────────────

    def _detect_trends(self, timestamp, system_metrics):
        """Detect memory leaks and swap thrashing."""
        anomalies = []

        # Update history buffers
        memory_used = system_metrics.get("memory_used")
        if memory_used is not None:
            self._memory_history.append((timestamp, memory_used))
            self._trim_history(self._memory_history, self._memory_history_max_age)

        swap_used = system_metrics.get("swap_used")
        if swap_used is not None:
            self._swap_history.append((timestamp, swap_used))
            self._trim_history(self._swap_history, self._swap_history_max_age)

        # Check for memory leak
        leak = self._detect_memory_leak(timestamp)
        if leak:
            anomalies.append(leak)

        # Check for swap thrashing
        thrash = self._detect_swap_thrashing(timestamp)
        if thrash:
            anomalies.append(thrash)

        return anomalies

    def _trim_history(self, history, max_age):
        """Remove entries older than max_age from a history buffer."""
        if not history:
            return
        cutoff = datetime.now() - max_age
        while history and history[0][0] < cutoff:
            history.pop(0)

    def _detect_memory_leak(self, timestamp):
        """
        Detect sustained memory growth over 2 hours.
        Divide into 12 buckets of 10 min each, check monotonic growth.
        """
        if len(self._memory_history) < 60:
            return None  # Need at least ~5 min of data

        # Create 12 buckets (10 min each)
        now = datetime.now()
        bucket_count = 12
        bucket_duration = timedelta(minutes=10)
        buckets = [[] for _ in range(bucket_count)]

        for ts, val in self._memory_history:
            age = now - ts
            bucket_idx = min(bucket_count - 1, int(age.total_seconds() / bucket_duration.total_seconds()))
            bucket_idx = bucket_count - 1 - bucket_idx  # Reverse: 0=oldest
            if 0 <= bucket_idx < bucket_count:
                buckets[bucket_idx].append(val)

        # Calculate averages per bucket
        averages = []
        for bucket in buckets:
            if bucket:
                averages.append(np.mean(bucket))

        if len(averages) < 6:
            return None  # Need at least 6 buckets

        # Check monotonic growth
        growth_count = 0
        for i in range(len(averages) - 1):
            if averages[i + 1] > averages[i]:
                growth_count += 1

        total_comparisons = len(averages) - 1
        if total_comparisons < 5:
            return None

        growth_ratio = growth_count / total_comparisons

        if growth_ratio >= 0.75:  # 75%+ of buckets show growth
            growth_bytes = averages[-1] - averages[0]
            growth_per_hour = growth_bytes * (3600 / (len(averages) * 600))
            growth_mb_per_hour = growth_per_hour / (1024 * 1024)

            if growth_mb_per_hour > 50:  # More than 50 MB/hour
                description = (
                    f"Potential memory leak detected: memory growing at "
                    f"{growth_mb_per_hour:.0f} MB/hour over the last "
                    f"{len(averages) * 10} minutes "
                    f"({growth_count}/{total_comparisons} intervals show growth)"
                )
                logger.warning(f"TREND: {description}")
                return {
                    "timestamp": timestamp,
                    "anomaly_type": "memory_leak",
                    "severity": "high" if growth_mb_per_hour > 100 else "medium",
                    "metric_name": "memory_used",
                    "metric_value": averages[-1],
                    "baseline_mean": averages[0],
                    "baseline_stddev": 0,
                    "z_score": 0,
                    "description": description,
                    "root_cause": None,
                }

        return None

    def _detect_swap_thrashing(self, timestamp):
        """
        Detect excessive swapping over last 30 minutes.
        Count how many times swap changed by > 100 MB between consecutive samples.
        """
        if len(self._swap_history) < 20:
            return None

        swap_changes = 0
        threshold = 100 * 1024 * 1024  # 100 MB

        for i in range(1, len(self._swap_history)):
            delta = abs(self._swap_history[i][1] - self._swap_history[i - 1][1])
            if delta > threshold:
                swap_changes += 1

        total_samples = len(self._swap_history) - 1
        if total_samples < 10:
            return None

        change_ratio = swap_changes / total_samples

        if change_ratio > 0.15:  # >15% of samples show large swap changes
            description = (
                f"Swap thrashing detected: {swap_changes} large swap changes "
                f"(>100 MB) in {total_samples} samples over the last 30 minutes. "
                f"System performance severely degraded."
            )
            logger.critical(f"TREND: {description}")
            return {
                "timestamp": timestamp,
                "anomaly_type": "swap_thrashing",
                "severity": "critical",
                "metric_name": "swap_used",
                "metric_value": self._swap_history[-1][1],
                "baseline_mean": 0,
                "baseline_stddev": 0,
                "z_score": 0,
                "description": description,
                "root_cause": None,
            }

        return None
