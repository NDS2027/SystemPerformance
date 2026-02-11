# System Performance Analyzer

An intelligent performance monitoring tool that collects OS metrics, detects anomalies using statistical methods, performs root cause analysis, and generates optimization recommendations — all implemented in Python with no LLM/ML dependencies.

## Features

- **Real-time Monitoring** — CPU, memory, swap, disk I/O, and per-process metrics collected every 5 seconds
- **Anomaly Detection** — Z-score based detection with context-aware baselines (weekday morning vs weekend night)
- **Trend Detection** — Memory leak and swap thrashing identification
- **Root Cause Analysis** — Timeline reconstruction, process contribution ranking, process tree tracing
- **Smart Recommendations** — 5 rule-based heuristics:
  1. Database index suggestions (detects table scan I/O patterns)
  2. Memory upgrade (sustained high usage + swap pressure)
  3. Chrome tab management (excessive browser memory)
  4. Docker resource limits (unlimited containers)
  5. Build system optimization (underutilized CPU during compilation)
- **Console Dashboard** — Color-coded real-time display with progress bars
- **Summary Reports** — On-demand reports for any time range

## Quick Start

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Start Monitoring

```bash
python monitor.py
```

### Options

```bash
python monitor.py --verbose                          # Debug mode
python monitor.py --report                           # 24h summary report
python monitor.py --report --start-time "2026-02-10" # Report from specific date
python monitor.py --config ./my_config.json          # Custom config file
```

## Project Structure

```
SystemPerformance/
├── src/
│   ├── collector.py      # Metrics collection via psutil
│   ├── storage.py        # SQLite database manager
│   ├── analyzer.py       # Statistical analysis & anomaly detection
│   ├── root_cause.py     # Root cause analysis engine
│   ├── recommender.py    # Optimization recommendation engine
│   ├── reporter.py       # Console display & reports
│   └── utils.py          # Helper functions
├── config/
│   └── config.json       # Configuration settings
├── monitor.py            # Main entry point
├── requirements.txt      # Python dependencies
└── README.md             # This file
```

## Configuration

Edit `config/config.json` to customize:
- **Collection interval** (default: 5 seconds)
- **Data retention** (default: 7 days)
- **Anomaly thresholds** (z-score severity levels)
- **Recommendation cooldown** (default: 24 hours)
- **Display settings** (colors, top process count)

## Technology Stack

- **Python 3.9+**
- **psutil** — OS metrics collection
- **numpy** — Statistical calculations
- **SQLite** — Time-series data storage
- **matplotlib** — Optional visualization
