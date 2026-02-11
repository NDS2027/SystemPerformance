"""
Utility functions for the System Performance Analyzer.
Provides formatting helpers, configuration loading, logging setup, and time context.
"""

import json
import logging
import os
import sys
from datetime import datetime


def format_bytes(byte_count):
    """Convert bytes to a human-readable string (e.g., '14.2 GB')."""
    if byte_count is None:
        return "N/A"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(byte_count) < 1024.0:
            return f"{byte_count:.1f} {unit}"
        byte_count /= 1024.0
    return f"{byte_count:.1f} PB"


def format_bytes_rate(bytes_per_sec):
    """Convert bytes/sec to a human-readable rate string (e.g., '145 MB/s')."""
    if bytes_per_sec is None:
        return "N/A"
    for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
        if abs(bytes_per_sec) < 1024.0:
            return f"{bytes_per_sec:.0f} {unit}"
        bytes_per_sec /= 1024.0
    return f"{bytes_per_sec:.1f} TB/s"


def format_duration(seconds):
    """Convert seconds to a human-readable duration (e.g., '2d 5h 30m')."""
    if seconds is None:
        return "N/A"
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def format_percent(value, decimals=1):
    """Format a percentage value."""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}%"


def get_time_context(dt=None):
    """
    Determine the time context for baseline calculation.

    Returns one of:
        'weekday_morning', 'weekday_afternoon', 'weekday_evening', 'weekday_night',
        'weekend_day', 'weekend_night'
    """
    if dt is None:
        dt = datetime.now()

    day_of_week = dt.weekday()  # 0=Monday, 6=Sunday
    hour = dt.hour

    if day_of_week < 5:  # Monday-Friday
        if 6 <= hour <= 11:
            return "weekday_morning"
        elif 12 <= hour <= 17:
            return "weekday_afternoon"
        elif 18 <= hour <= 22:
            return "weekday_evening"
        else:
            return "weekday_night"
    else:  # Saturday-Sunday
        if 8 <= hour <= 20:
            return "weekend_day"
        else:
            return "weekend_night"


def load_config(config_path=None):
    """
    Load configuration from a JSON file.
    Falls back to default config if file not found.
    """
    if config_path is None:
        # Look for config relative to the project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(project_root, "config", "config.json")

    default_config = {
        "collection": {
            "interval_seconds": 5,
            "enable_process_metrics": True,
            "enable_io_metrics": True,
            "max_processes_tracked": 500
        },
        "storage": {
            "database_path": "./performance.db",
            "retention_days": 7,
            "cleanup_frequency": "daily",
            "cleanup_time": "03:00"
        },
        "analysis": {
            "baseline_calculation_frequency": "hourly",
            "baseline_history_days": 7,
            "anomaly_z_threshold": 2.0,
            "anomaly_severity_levels": {
                "low": 1.5,
                "medium": 2.0,
                "high": 2.5,
                "critical": 3.0
            }
        },
        "recommendations": {
            "enable_recommendations": True,
            "recommendation_cooldown_hours": 24,
            "min_priority_to_display": "medium"
        },
        "display": {
            "console_refresh_rate": 5,
            "show_top_processes": 10,
            "use_colors": True,
            "log_level": "INFO"
        },
        "thresholds": {
            "cpu_critical": 95,
            "memory_critical": 95,
            "swap_warning": 50,
            "disk_io_high_mbps": 100
        }
    }

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        # Merge with defaults (fill in missing keys)
        merged = _deep_merge(default_config, config)
        return merged
    except FileNotFoundError:
        logging.warning(f"Config file not found at {config_path}, using defaults.")
        return default_config
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in config file: {e}. Using defaults.")
        return default_config


def _deep_merge(base, override):
    """Recursively merge override dict into base dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def setup_logging(log_level="INFO", log_file=None):
    """Configure logging for the application."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True
    )

    return logging.getLogger("performance_analyzer")


def make_progress_bar(percent, width=24):
    """Create an ASCII progress bar string. E.g., [████████████        ]"""
    if percent is None:
        percent = 0
    percent = max(0, min(100, percent))
    filled = int(width * percent / 100)
    bar = '█' * filled + ' ' * (width - filled)
    return f"[{bar}]"


def is_windows():
    """Check if running on Windows."""
    return sys.platform == 'win32'


def is_linux():
    """Check if running on Linux."""
    return sys.platform.startswith('linux')


def is_macos():
    """Check if running on macOS."""
    return sys.platform == 'darwin'


def safe_div(numerator, denominator, default=0):
    """Safe division that returns default on zero/None denominator."""
    if denominator is None or denominator == 0:
        return default
    return numerator / denominator
