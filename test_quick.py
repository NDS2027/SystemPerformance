"""Quick test - writes results to file."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

output_lines = []

try:
    from src.utils import load_config, format_bytes, get_time_context, make_progress_bar
    output_lines.append("PASS: utils imports")
except Exception as e:
    output_lines.append(f"FAIL: utils imports - {e}")

try:
    from src.collector import MetricsCollector
    output_lines.append("PASS: collector imports")
except Exception as e:
    output_lines.append(f"FAIL: collector imports - {e}")

try:
    from src.storage import DatabaseManager
    output_lines.append("PASS: storage imports")
except Exception as e:
    output_lines.append(f"FAIL: storage imports - {e}")

try:
    from src.analyzer import Analyzer
    output_lines.append("PASS: analyzer imports")
except Exception as e:
    output_lines.append(f"FAIL: analyzer imports - {e}")

try:
    from src.root_cause import RootCauseAnalyzer
    output_lines.append("PASS: root_cause imports")
except Exception as e:
    output_lines.append(f"FAIL: root_cause imports - {e}")

try:
    from src.recommender import Recommender
    output_lines.append("PASS: recommender imports")
except Exception as e:
    output_lines.append(f"FAIL: recommender imports - {e}")

try:
    from src.reporter import Reporter
    output_lines.append("PASS: reporter imports")
except Exception as e:
    output_lines.append(f"FAIL: reporter imports - {e}")

# Test utils functions
try:
    assert format_bytes(1073741824) == "1.0 GB"
    ctx = get_time_context()
    output_lines.append(f"PASS: utils functions (context={ctx})")
except Exception as e:
    output_lines.append(f"FAIL: utils functions - {e}")

# Test config
try:
    config = load_config()
    output_lines.append(f"PASS: config loaded (keys={list(config.keys())})")
except Exception as e:
    output_lines.append(f"FAIL: config - {e}")

# Test collector
try:
    collector = MetricsCollector(config)
    data = collector.collect_all()
    cpu = data['system']['cpu_percent']
    mem = data['system']['memory_percent']
    procs = len(data['processes'])
    output_lines.append(f"PASS: collector (CPU={cpu}%, Mem={mem}%, Procs={procs})")
except Exception as e:
    output_lines.append(f"FAIL: collector - {e}")

# Test database
try:
    test_cfg = config.copy()
    test_cfg["storage"] = {"database_path": "./test_perf.db", "retention_days": 7}
    db = DatabaseManager(test_cfg)
    db.initialize()
    from datetime import datetime
    ts = datetime.now()
    db.store_system_metrics(ts, data["system"])
    db.store_process_metrics(ts, data["processes"][:5])
    rows = db.get_system_metrics(ts)
    output_lines.append(f"PASS: database (rows retrieved={len(rows)})")
    db.close()
    os.remove("./test_perf.db")
except Exception as e:
    output_lines.append(f"FAIL: database - {e}")

passed = sum(1 for l in output_lines if l.startswith("PASS"))
total = len(output_lines)
output_lines.append(f"\nRESULT: {passed}/{total} tests passed")

with open("test_results.txt", "w") as f:
    f.write("\n".join(output_lines))
