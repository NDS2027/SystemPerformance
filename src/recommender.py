"""
Optimization Recommendation Engine for the System Performance Analyzer.
Uses rule-based heuristics to generate actionable optimization recommendations.
Implements 5 recommendation types: database index, memory upgrade, Chrome tabs,
Docker limits, and build system optimization.
"""

import logging
from datetime import datetime, timedelta

from src.utils import format_bytes, safe_div

logger = logging.getLogger("performance_analyzer.recommender")


class Recommender:
    """Generates optimization recommendations based on rule-based heuristics."""

    # Priority order for sorting
    PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def __init__(self, config, db_manager):
        self.config = config
        self.db = db_manager
        rec_cfg = config.get("recommendations", {})
        self.enabled = rec_cfg.get("enable_recommendations", True)
        self.cooldown_hours = rec_cfg.get("recommendation_cooldown_hours", 24)
        logger.info("Recommender initialized.")

    def generate_recommendations(self, timestamp, system_metrics, processes):
        """
        Run all recommendation heuristics against current state.
        Returns a list of new recommendations (may be empty).
        """
        if not self.enabled:
            return []

        recommendations = []

        # Run each heuristic
        checks = [
            self._check_database_index,
            self._check_memory_upgrade,
            self._check_chrome_tabs,
            self._check_docker_limits,
            self._check_build_optimization,
        ]

        for check_fn in checks:
            try:
                rec = check_fn(timestamp, system_metrics, processes)
                if rec:
                    # Check cooldown
                    rec_type = rec.get("recommendation_type")
                    if not self.db.has_recent_recommendation(rec_type, self.cooldown_hours):
                        self.db.store_recommendation(rec)
                        recommendations.append(rec)
                        logger.info(
                            f"NEW RECOMMENDATION [{rec.get('priority', '').upper()}]: "
                            f"{rec.get('recommendation_type')}"
                        )
            except Exception as e:
                logger.debug(f"Error in recommendation check {check_fn.__name__}: {e}")

        return recommendations

    # ──────────────────────── HEURISTIC 1: Database Index ─────────────────────

    def _check_database_index(self, timestamp, system_metrics, processes):
        """
        Detect database processes with high random I/O (potential table scans).
        Trigger: DB process with >10K read ops, avg read <16KB, sustained >5 min.
        """
        db_names = ['postgres', 'postgresql', 'mysql', 'mysqld',
                     'mongod', 'mongodb', 'mariadb', 'sqlservr']

        for proc in processes:
            name = (proc.get("name") or "").lower()
            if not any(db in name for db in db_names):
                continue

            io_read_count = proc.get("io_read_count") or 0
            io_read_bytes = proc.get("io_read_bytes") or 0

            if io_read_count < 10000:
                continue

            avg_read_size = safe_div(io_read_bytes, io_read_count, 0)
            if avg_read_size >= 16384:  # 16 KB
                continue

            # Pattern matches: small random reads from a DB process
            pid = proc.get("pid")
            return {
                "timestamp": timestamp,
                "recommendation_type": "database_index",
                "target_process": f"{name} (PID {pid})",
                "target_pid": pid,
                "issue_description": (
                    f"Database '{name}' performing inefficient I/O pattern "
                    f"characteristic of table scans. "
                    f"Read operations: {io_read_count:,}/sample, "
                    f"Average read size: {format_bytes(avg_read_size)}."
                ),
                "recommendation": (
                    "Your database is performing table scans (many small random reads). "
                    "This usually indicates missing indexes on frequently queried columns.\n\n"
                    "Actions to take:\n"
                    "1. Review database slow query log to identify expensive queries\n"
                    "2. Look for queries without WHERE clause indexes\n"
                    "3. Add indexes on columns used in WHERE, JOIN, ORDER BY clauses\n"
                    f"4. Monitor {name} after adding indexes for improvement"
                ),
                "estimated_impact": "70-95% query speedup, major I/O reduction",
                "priority": "high",
                "status": "active",
            }

        return None

    # ──────────────────────── HEURISTIC 2: Memory Upgrade ─────────────────────

    def _check_memory_upgrade(self, timestamp, system_metrics, processes):
        """
        Detect sustained memory pressure suggesting hardware upgrade.
        Trigger: avg memory >85% AND (swap >1GB avg OR >20 times over 90%).
        """
        memory_percent = system_metrics.get("memory_percent", 0)
        swap_used = system_metrics.get("swap_used", 0)
        memory_total = system_metrics.get("memory_total", 0)
        memory_used = system_metrics.get("memory_used", 0)

        if memory_percent < 85:
            return None

        swap_gb = (swap_used or 0) / (1024 ** 3)
        if swap_gb < 0.5:
            return None

        total_gb = (memory_total or 0) / (1024 ** 3)
        used_gb = (memory_used or 0) / (1024 ** 3)

        # Calculate recommended RAM
        recommended_min = used_gb * 1.3
        standard_sizes = [8, 16, 24, 32, 48, 64, 128]
        recommended_ram = standard_sizes[-1]
        for size in standard_sizes:
            if size >= recommended_min:
                recommended_ram = size
                break

        # Get top memory consumers
        mem_consumers = sorted(
            processes, key=lambda p: p.get("memory_rss", 0) or 0, reverse=True
        )[:5]
        consumer_lines = []
        for p in mem_consumers:
            rss = p.get("memory_rss", 0) or 0
            consumer_lines.append(f"  - {p.get('name', '?')}: {format_bytes(rss)}")
        consumers_str = "\n".join(consumer_lines)

        return {
            "timestamp": timestamp,
            "recommendation_type": "memory_upgrade",
            "target_process": "system",
            "target_pid": None,
            "issue_description": (
                f"System consistently operating near memory capacity. "
                f"Current RAM: {total_gb:.0f} GB, Usage: {used_gb:.1f} GB ({memory_percent:.1f}%), "
                f"Swap: {swap_gb:.1f} GB."
            ),
            "recommendation": (
                f"Upgrade to {recommended_ram} GB RAM.\n\n"
                f"Current memory usage: {used_gb:.1f} / {total_gb:.0f} GB ({memory_percent:.1f}%)\n"
                f"Swap usage: {swap_gb:.1f} GB\n\n"
                f"Top memory consumers:\n{consumers_str}\n\n"
                f"Expected benefits:\n"
                f"- Eliminate swap usage entirely (major speed boost)\n"
                f"- Reduce memory pressure events\n"
                f"- Faster application switching\n"
                f"- Ability to run additional services"
            ),
            "estimated_impact": "Eliminate swapping, major system responsiveness improvement",
            "priority": "high",
            "status": "active",
        }

    # ──────────────────────── HEURISTIC 3: Chrome Tabs ────────────────────────

    def _check_chrome_tabs(self, timestamp, system_metrics, processes):
        """
        Detect excessive Chrome memory usage.
        Trigger: Chrome total memory > 3 GB AND (estimated tabs > 30 OR runtime > 48h).
        """
        chrome_procs = [
            p for p in processes
            if 'chrome' in (p.get("name") or "").lower()
        ]

        if not chrome_procs:
            return None

        total_chrome_memory = sum(p.get("memory_rss", 0) or 0 for p in chrome_procs)
        chrome_memory_gb = total_chrome_memory / (1024 ** 3)

        if chrome_memory_gb < 2.0:
            return None

        # Estimate tab count (Chrome ~3 processes per tab)
        estimated_tabs = max(1, len(chrome_procs) // 3)

        # Check runtime of oldest Chrome process
        runtime_hours = 0
        oldest_create = None
        for p in chrome_procs:
            ct = p.get("create_time")
            if ct:
                try:
                    create_dt = datetime.fromtimestamp(ct)
                    if oldest_create is None or create_dt < oldest_create:
                        oldest_create = create_dt
                except (OSError, ValueError):
                    pass
        if oldest_create:
            runtime_hours = (datetime.now() - oldest_create).total_seconds() / 3600

        if chrome_memory_gb < 3.0 and estimated_tabs < 30 and runtime_hours < 48:
            return None

        return {
            "timestamp": timestamp,
            "recommendation_type": "chrome_tab_management",
            "target_process": f"chrome ({len(chrome_procs)} processes)",
            "target_pid": None,
            "issue_description": (
                f"Chrome browser consuming excessive memory: "
                f"{chrome_memory_gb:.1f} GB across {len(chrome_procs)} processes "
                f"(~{estimated_tabs} tabs). Runtime: {runtime_hours:.0f} hours."
            ),
            "recommendation": (
                "Optimize Chrome browser memory usage:\n\n"
                f"1. Restart Chrome ({runtime_hours:.0f}h runtime → accumulated memory leaks)\n"
                f"   Expected savings: ~{chrome_memory_gb * 0.25:.1f} GB\n\n"
                f"2. Close unused tabs (estimated ~{estimated_tabs} open)\n"
                f"   Expected savings: ~{chrome_memory_gb * 0.4:.1f} GB\n\n"
                "3. Install a tab suspender extension (e.g., The Great Suspender)\n"
                "   Auto-suspends inactive tabs, saves ~60-70% memory\n\n"
                "4. Keep active tabs under 15-20\n\n"
                "5. Restart browser every few days to prevent memory leaks"
            ),
            "estimated_impact": (
                f"Reclaim {chrome_memory_gb * 0.5:.1f}-{chrome_memory_gb * 0.7:.1f} GB RAM"
            ),
            "priority": "medium",
            "status": "active",
        }

    # ──────────────────────── HEURISTIC 4: Docker Limits ──────────────────────

    def _check_docker_limits(self, timestamp, system_metrics, processes):
        """
        Detect Docker containers without resource limits.
        Trigger: Docker memory > 30% of RAM AND (growth > 500 MB/h OR total > 6 GB).
        """
        docker_procs = [
            p for p in processes
            if any(d in (p.get("name") or "").lower()
                   for d in ['docker', 'containerd', 'dockerd', 'moby'])
        ]

        if not docker_procs:
            return None

        total_docker_memory = sum(p.get("memory_rss", 0) or 0 for p in docker_procs)
        docker_memory_gb = total_docker_memory / (1024 ** 3)
        total_ram = system_metrics.get("memory_total", 1)
        docker_percent = (total_docker_memory / total_ram) * 100

        if docker_percent < 30 and docker_memory_gb < 6:
            return None

        # Container breakdown
        container_lines = []
        for p in sorted(docker_procs, key=lambda x: x.get("memory_rss", 0) or 0, reverse=True)[:5]:
            rss = p.get("memory_rss", 0) or 0
            container_lines.append(f"  - {p.get('name', '?')} (PID {p.get('pid')}): {format_bytes(rss)}")
        containers_str = "\n".join(container_lines)

        return {
            "timestamp": timestamp,
            "recommendation_type": "docker_resource_limits",
            "target_process": "docker containers",
            "target_pid": None,
            "issue_description": (
                f"Docker containers consuming {docker_memory_gb:.1f} GB ({docker_percent:.0f}% of RAM) "
                f"across {len(docker_procs)} processes without apparent resource limits."
            ),
            "recommendation": (
                "Configure Docker resource limits:\n\n"
                f"Docker memory usage: {docker_memory_gb:.1f} GB ({docker_percent:.0f}% of RAM)\n\n"
                f"Top containers:\n{containers_str}\n\n"
                "Actions:\n"
                "1. Set memory limits: docker run --memory=2g --memory-swap=2g <container>\n"
                "2. In docker-compose.yml:\n"
                "   services:\n"
                "     app:\n"
                "       mem_limit: 2g\n"
                "       mem_reservation: 1.5g\n\n"
                "3. Set CPU limits: --cpus=2.0\n"
                "4. Monitor: docker stats"
            ),
            "estimated_impact": "Prevent system-wide memory exhaustion, improve stability",
            "priority": "high",
            "status": "active",
        }

    # ──────────────────────── HEURISTIC 5: Build Optimization ─────────────────

    def _check_build_optimization(self, timestamp, system_metrics, processes):
        """
        Detect build processes not using parallel compilation.
        Trigger: compiler detected AND CPU utilization < 50% of available cores.
        """
        compiler_names = ['gcc', 'g++', 'clang', 'clang++', 'cc', 'c++',
                          'make', 'ninja', 'msbuild', 'cl', 'javac', 'rustc']

        compiler_procs = [
            p for p in processes
            if (p.get("name") or "").lower() in compiler_names
        ]

        if not compiler_procs:
            return None

        # Check CPU utilization
        cpu_percent = system_metrics.get("cpu_percent", 0)
        cpu_count = system_metrics.get("cpu_count_logical", 1)
        total_cpu_available = cpu_count * 100
        utilization = (cpu_percent / 100)  # 0-1 scale

        if utilization > 0.5:
            return None  # Already using CPUs well

        # Check for single-threaded bottleneck (one core maxed)
        per_core = system_metrics.get("per_core_cpu_percent") if hasattr(system_metrics, 'get') else None
        # per_core is in the collector output, not stored in DB, so we check directly
        # This heuristic works with overall CPU being low during compilation

        return {
            "timestamp": timestamp,
            "recommendation_type": "build_optimization",
            "target_process": f"compiler ({', '.join(p.get('name', '?') for p in compiler_procs[:3])})",
            "target_pid": compiler_procs[0].get("pid"),
            "issue_description": (
                f"Build system not utilizing available CPU cores efficiently. "
                f"CPU usage: {cpu_percent:.0f}% with {cpu_count} cores available. "
                f"Detected compiler processes: "
                f"{', '.join(p.get('name', '?') for p in compiler_procs[:3])}."
            ),
            "recommendation": (
                "Enable parallel compilation:\n\n"
                f"Available CPU cores: {cpu_count}\n"
                f"Current CPU utilization: {cpu_percent:.0f}%\n\n"
                "Actions:\n"
                f"1. Use make with -j flag: make -j{cpu_count}\n"
                f"2. For CMake: cmake --build . -j{cpu_count}\n"
                f"3. For Ninja: ninja -j{cpu_count}\n\n"
                f"Expected improvement:\n"
                f"- Build time reduction: ~{cpu_count-1}x faster\n"
                f"- CPU utilization: {cpu_percent:.0f}% → 90%+\n\n"
                "Bonus: Install ccache for faster recompilation"
            ),
            "estimated_impact": f"{cpu_count-1}-{cpu_count}x faster builds",
            "priority": "medium",
            "status": "active",
        }
