"""
Database Storage Manager for the System Performance Analyzer.
Manages SQLite database with schema creation, CRUD operations, analysis queries,
and data retention cleanup.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

logger = logging.getLogger("performance_analyzer.storage")


class DatabaseManager:
    """Manages all database operations for the performance analyzer."""

    def __init__(self, config):
        self.config = config
        storage_config = config.get("storage", {})
        self.db_path = storage_config.get("database_path", "./performance.db")
        self.retention_days = storage_config.get("retention_days", 7)
        self.conn = None

    def initialize(self):
        """Create database connection and set up schema."""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self._create_tables()
            self._create_indexes()
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def _create_tables(self):
        """Create all required tables if they don't exist."""
        cursor = self.conn.cursor()

        # System metrics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_metrics (
                timestamp         DATETIME PRIMARY KEY,
                cpu_percent       REAL,
                cpu_count_logical INTEGER,
                cpu_count_physical INTEGER,
                load_avg_1min     REAL,
                load_avg_5min     REAL,
                load_avg_15min    REAL,
                memory_total      INTEGER,
                memory_available  INTEGER,
                memory_used       INTEGER,
                memory_percent    REAL,
                memory_cached     INTEGER,
                swap_total        INTEGER,
                swap_used         INTEGER,
                swap_percent      REAL,
                disk_read_bytes_delta   INTEGER,
                disk_write_bytes_delta  INTEGER,
                disk_read_ops_delta     INTEGER,
                disk_write_ops_delta    INTEGER,
                disk_total        INTEGER,
                disk_used         INTEGER,
                disk_percent      REAL
            )
        """)

        # Process metrics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS process_metrics (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        DATETIME,
                pid              INTEGER,
                name             TEXT,
                username         TEXT,
                status           TEXT,
                cpu_percent      REAL,
                memory_rss       INTEGER,
                memory_vms       INTEGER,
                memory_percent   REAL,
                num_threads      INTEGER,
                ppid             INTEGER,
                create_time      DATETIME,
                io_read_bytes    INTEGER,
                io_write_bytes   INTEGER,
                io_read_count    INTEGER,
                io_write_count   INTEGER,
                FOREIGN KEY (timestamp) REFERENCES system_metrics(timestamp)
            )
        """)

        # Anomalies table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS anomalies (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        DATETIME,
                anomaly_type     TEXT,
                severity         TEXT,
                metric_name      TEXT,
                metric_value     REAL,
                baseline_mean    REAL,
                baseline_stddev  REAL,
                z_score          REAL,
                description      TEXT,
                root_cause       TEXT
            )
        """)

        # Recommendations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp           DATETIME,
                recommendation_type TEXT,
                target_process      TEXT,
                target_pid          INTEGER,
                issue_description   TEXT,
                recommendation      TEXT,
                estimated_impact    TEXT,
                priority            TEXT,
                status              TEXT DEFAULT 'active'
            )
        """)

        # Baselines table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS baselines (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_name     TEXT,
                context         TEXT,
                mean_value      REAL,
                std_dev         REAL,
                min_value       REAL,
                max_value       REAL,
                sample_count    INTEGER,
                last_updated    DATETIME
            )
        """)

        self.conn.commit()

    def _create_indexes(self):
        """Create all performance indexes."""
        cursor = self.conn.cursor()
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_timestamp ON system_metrics(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_process_timestamp ON process_metrics(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_process_pid ON process_metrics(pid)",
            "CREATE INDEX IF NOT EXISTS idx_process_name ON process_metrics(name)",
            "CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp ON anomalies(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_anomaly_type ON anomalies(anomaly_type)",
            "CREATE INDEX IF NOT EXISTS idx_rec_timestamp ON recommendations(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_rec_status ON recommendations(status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_baseline ON baselines(metric_name, context)",
        ]
        for idx_sql in indexes:
            try:
                cursor.execute(idx_sql)
            except sqlite3.OperationalError:
                pass  # Index already exists
        self.conn.commit()

    # ──────────────────────────── WRITE OPERATIONS ────────────────────────────

    def store_system_metrics(self, timestamp, data):
        """Insert a system metrics snapshot."""
        try:
            ts = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            self.conn.execute("""
                INSERT OR REPLACE INTO system_metrics VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                ts,
                data.get("cpu_percent"),
                data.get("cpu_count_logical"),
                data.get("cpu_count_physical"),
                data.get("load_avg_1min"),
                data.get("load_avg_5min"),
                data.get("load_avg_15min"),
                data.get("memory_total"),
                data.get("memory_available"),
                data.get("memory_used"),
                data.get("memory_percent"),
                data.get("memory_cached"),
                data.get("swap_total"),
                data.get("swap_used"),
                data.get("swap_percent"),
                data.get("disk_read_bytes_delta"),
                data.get("disk_write_bytes_delta"),
                data.get("disk_read_ops_delta"),
                data.get("disk_write_ops_delta"),
                data.get("disk_total"),
                data.get("disk_used"),
                data.get("disk_percent"),
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error storing system metrics: {e}")

    def store_process_metrics(self, timestamp, processes):
        """Batch insert process metrics for a given timestamp."""
        try:
            ts = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            rows = []
            for p in processes:
                create_time = None
                if p.get("create_time"):
                    try:
                        create_time = datetime.fromtimestamp(p["create_time"]).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    except (OSError, ValueError):
                        create_time = None

                rows.append((
                    ts,
                    p.get("pid"),
                    p.get("name"),
                    p.get("username"),
                    p.get("status"),
                    p.get("cpu_percent", 0),
                    p.get("memory_rss", 0),
                    p.get("memory_vms", 0),
                    p.get("memory_percent", 0),
                    p.get("num_threads", 0),
                    p.get("ppid"),
                    create_time,
                    p.get("io_read_bytes"),
                    p.get("io_write_bytes"),
                    p.get("io_read_count"),
                    p.get("io_write_count"),
                ))

            self.conn.executemany("""
                INSERT INTO process_metrics (
                    timestamp, pid, name, username, status,
                    cpu_percent, memory_rss, memory_vms, memory_percent,
                    num_threads, ppid, create_time,
                    io_read_bytes, io_write_bytes, io_read_count, io_write_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error storing process metrics: {e}")

    def store_anomaly(self, anomaly_data):
        """Record a detected anomaly."""
        try:
            ts = anomaly_data["timestamp"].strftime("%Y-%m-%d %H:%M:%S") \
                if isinstance(anomaly_data["timestamp"], datetime) \
                else anomaly_data["timestamp"]

            root_cause = anomaly_data.get("root_cause")
            if isinstance(root_cause, dict):
                root_cause = json.dumps(root_cause)

            self.conn.execute("""
                INSERT INTO anomalies (
                    timestamp, anomaly_type, severity, metric_name,
                    metric_value, baseline_mean, baseline_stddev,
                    z_score, description, root_cause
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts,
                anomaly_data.get("anomaly_type"),
                anomaly_data.get("severity"),
                anomaly_data.get("metric_name"),
                anomaly_data.get("metric_value"),
                anomaly_data.get("baseline_mean"),
                anomaly_data.get("baseline_stddev"),
                anomaly_data.get("z_score"),
                anomaly_data.get("description"),
                root_cause,
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error storing anomaly: {e}")

    def store_recommendation(self, rec_data):
        """Store a recommendation."""
        try:
            ts = rec_data["timestamp"].strftime("%Y-%m-%d %H:%M:%S") \
                if isinstance(rec_data["timestamp"], datetime) \
                else rec_data["timestamp"]

            self.conn.execute("""
                INSERT INTO recommendations (
                    timestamp, recommendation_type, target_process, target_pid,
                    issue_description, recommendation, estimated_impact,
                    priority, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts,
                rec_data.get("recommendation_type"),
                rec_data.get("target_process"),
                rec_data.get("target_pid"),
                rec_data.get("issue_description"),
                rec_data.get("recommendation"),
                rec_data.get("estimated_impact"),
                rec_data.get("priority", "medium"),
                rec_data.get("status", "active"),
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error storing recommendation: {e}")

    def update_baseline(self, metric_name, context, stats):
        """Insert or update a baseline entry."""
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.conn.execute("""
                INSERT INTO baselines (
                    metric_name, context, mean_value, std_dev,
                    min_value, max_value, sample_count, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(metric_name, context) DO UPDATE SET
                    mean_value=excluded.mean_value,
                    std_dev=excluded.std_dev,
                    min_value=excluded.min_value,
                    max_value=excluded.max_value,
                    sample_count=excluded.sample_count,
                    last_updated=excluded.last_updated
            """, (
                metric_name, context,
                stats.get("mean"), stats.get("std_dev"),
                stats.get("min"), stats.get("max"),
                stats.get("count"), now,
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error updating baseline: {e}")

    # ──────────────────────────── READ OPERATIONS ─────────────────────────────

    def get_system_metrics(self, start_time, end_time=None):
        """Query system metrics within a time range. Returns list of Row dicts."""
        if end_time is None:
            end_time = datetime.now()
        st = start_time.strftime("%Y-%m-%d %H:%M:%S")
        et = end_time.strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.conn.execute(
            "SELECT * FROM system_metrics WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (st, et)
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_process_metrics_at(self, timestamp):
        """Get all processes at a specific timestamp."""
        ts = timestamp.strftime("%Y-%m-%d %H:%M:%S") \
            if isinstance(timestamp, datetime) else timestamp
        cursor = self.conn.execute(
            "SELECT * FROM process_metrics WHERE timestamp = ? ORDER BY cpu_percent DESC",
            (ts,)
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_baseline(self, metric_name, context):
        """Retrieve baseline stats for a given metric and context."""
        cursor = self.conn.execute(
            "SELECT * FROM baselines WHERE metric_name = ? AND context = ?",
            (metric_name, context)
        )
        columns = [desc[0] for desc in cursor.description]
        row = cursor.fetchone()
        return dict(zip(columns, row)) if row else None

    def get_all_baselines(self):
        """Get all baselines."""
        cursor = self.conn.execute("SELECT * FROM baselines")
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_recent_anomalies(self, hours=24):
        """Get anomalies from the last N hours."""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.conn.execute(
            "SELECT * FROM anomalies WHERE timestamp > ? ORDER BY timestamp DESC",
            (since,)
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_active_recommendations(self):
        """Get all recommendations that are still active."""
        cursor = self.conn.execute(
            "SELECT * FROM recommendations WHERE status = 'active' ORDER BY timestamp DESC"
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_recent_recommendations(self, hours=24):
        """Get recommendations from the last N hours."""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.conn.execute(
            "SELECT * FROM recommendations WHERE timestamp > ? ORDER BY timestamp DESC",
            (since,)
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_top_processes_by_cpu(self, timestamp, limit=10):
        """Get top N processes by CPU usage at a timestamp."""
        ts = timestamp.strftime("%Y-%m-%d %H:%M:%S") \
            if isinstance(timestamp, datetime) else timestamp
        cursor = self.conn.execute(
            "SELECT * FROM process_metrics WHERE timestamp = ? ORDER BY cpu_percent DESC LIMIT ?",
            (ts, limit)
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_top_processes_by_memory(self, timestamp, limit=10):
        """Get top N processes by memory usage at a timestamp."""
        ts = timestamp.strftime("%Y-%m-%d %H:%M:%S") \
            if isinstance(timestamp, datetime) else timestamp
        cursor = self.conn.execute(
            "SELECT * FROM process_metrics WHERE timestamp = ? ORDER BY memory_rss DESC LIMIT ?",
            (ts, limit)
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_process_history(self, pid, hours=2):
        """Track a single process over the last N hours."""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.conn.execute(
            "SELECT * FROM process_metrics WHERE pid = ? AND timestamp > ? ORDER BY timestamp",
            (pid, since)
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def calculate_avg_metric(self, metric_name, hours=1):
        """Calculate average of a system metric over the last N hours."""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.conn.execute(
            f"SELECT AVG({metric_name}) FROM system_metrics WHERE timestamp > ?",
            (since,)
        )
        result = cursor.fetchone()
        return result[0] if result and result[0] is not None else None

    def get_metric_values_for_context(self, metric_name, context, days=7):
        """
        Get all values of a metric that match a given time context
        from the last N days. Used for baseline calculation.
        """
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.conn.execute(
            f"SELECT timestamp, {metric_name} FROM system_metrics WHERE timestamp > ? ORDER BY timestamp",
            (since,)
        )
        from src.utils import get_time_context
        values = []
        for row in cursor.fetchall():
            try:
                ts = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                if get_time_context(ts) == context:
                    if row[1] is not None:
                        values.append(row[1])
            except (ValueError, TypeError):
                continue
        return values

    def has_recent_recommendation(self, recommendation_type, cooldown_hours=24):
        """Check if a recommendation of this type was already generated recently."""
        since = (datetime.now() - timedelta(hours=cooldown_hours)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM recommendations WHERE recommendation_type = ? AND timestamp > ?",
            (recommendation_type, since)
        )
        count = cursor.fetchone()[0]
        return count > 0

    # ──────────────────────────── MAINTENANCE ─────────────────────────────────

    def cleanup_old_data(self):
        """Delete data older than retention period."""
        try:
            # Detailed data: retention_days
            cutoff = (datetime.now() - timedelta(days=self.retention_days)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            self.conn.execute(
                "DELETE FROM system_metrics WHERE timestamp < ?", (cutoff,)
            )
            self.conn.execute(
                "DELETE FROM process_metrics WHERE timestamp < ?", (cutoff,)
            )

            # Anomalies and recommendations: 30 days
            cutoff_30 = (datetime.now() - timedelta(days=30)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            self.conn.execute(
                "DELETE FROM anomalies WHERE timestamp < ?", (cutoff_30,)
            )
            self.conn.execute(
                "DELETE FROM recommendations WHERE timestamp < ?", (cutoff_30,)
            )

            self.conn.commit()
            logger.info(
                f"Cleanup complete: removed data older than {self.retention_days} days "
                f"(anomalies/recs older than 30 days)"
            )
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def vacuum_database(self):
        """Optimize database file size."""
        try:
            self.conn.execute("VACUUM")
            logger.info("Database vacuumed successfully.")
        except Exception as e:
            logger.error(f"Error vacuuming database: {e}")

    def get_database_size(self):
        """Return database file size in MB."""
        try:
            size_bytes = os.path.getsize(self.db_path)
            return size_bytes / (1024 * 1024)
        except OSError:
            return 0.0

    def get_row_counts(self):
        """Get row counts for all tables."""
        counts = {}
        for table in ["system_metrics", "process_metrics", "anomalies",
                       "recommendations", "baselines"]:
            try:
                cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cursor.fetchone()[0]
            except Exception:
                counts[table] = 0
        return counts

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")
