#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server Benchmark
-----------------------------------
This script benchmarks the MCP server's performance and responsiveness.
It measures:
- Connection time
- Response time for various operations
- Stability under load
- Memory usage

Usage:
    python benchmark_server.py [--iterations=N] [--delay=SECONDS]

Requirements:
    - DaVinci Resolve must be running with a project open
    - DaVinci Resolve MCP Server must be running
    - requests, psutil modules (pip install requests psutil)
"""

import time
import json
import argparse
import statistics
import requests
import logging
import psutil
from typing import Dict, Any, Tuple
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(
            f"mcp_benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Server configuration
SERVER_URL = "http://localhost:8000/api"


def send_request(
    tool_name: str, params: Dict[str, Any]
) -> Tuple[Dict[str, Any], float]:
    """Send a request to the MCP server and measure response time."""
    try:
        payload = {"tool": tool_name, "params": params}
        start_time = time.time()
        response = requests.post(SERVER_URL, json=payload)
        end_time = time.time()
        response_time = end_time - start_time

        response.raise_for_status()
        return response.json(), response_time
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return {"success": False, "error": str(e)}, time.time() - start_time


def measure_system_resources() -> Dict[str, float]:
    """Measure system resources used by the server process."""
    resources = {}

    try:
        # Find the server process
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            if proc.info["cmdline"] and any(
                "resolve_mcp_server.py" in cmd for cmd in proc.info["cmdline"] if cmd
            ):
                # Get memory usage
                process = psutil.Process(proc.info["pid"])
                mem_info = process.memory_info()
                resources["memory_mb"] = mem_info.rss / (1024 * 1024)  # Convert to MB
                resources["cpu_percent"] = process.cpu_percent(interval=0.5)
                resources["threads"] = process.num_threads()
                resources["connections"] = len(process.connections())
                break
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        logger.error(f"Error measuring system resources: {e}")

    return resources


def benchmark_operation(
    operation_name: str,
    tool_name: str,
    params: Dict[str, Any],
    iterations: int = 10,
    delay: float = 0.5,
) -> Dict[str, Any]:
    """Benchmark a specific operation."""
    logger.info(f"Benchmarking {operation_name}...")

    response_times = []
    success_count = 0
    error_count = 0
    error_messages = []

    for i in range(iterations):
        logger.info(f"  Iteration {i+1}/{iterations}")
        result, response_time = send_request(tool_name, params)

        response_times.append(response_time)

        if "error" not in result or not result["error"]:
            success_count += 1
        else:
            error_count += 1
            error_message = str(result.get("error", "Unknown error"))
            error_messages.append(error_message)
            logger.warning(f"  Error: {error_message}")

        if i < iterations - 1:  # Don't delay after the last iteration
            time.sleep(delay)

    # Calculate statistics
    stats = {
        "min_time": min(response_times),
        "max_time": max(response_times),
        "avg_time": statistics.mean(response_times),
        "median_time": statistics.median(response_times),
        "std_dev": statistics.stdev(response_times) if len(response_times) > 1 else 0,
        "success_rate": success_count / iterations,
        "error_rate": error_count / iterations,
        "error_messages": error_messages[:5],  # Limit to first 5 errors
    }

    # Log results
    logger.info(f"Results for {operation_name}:")
    logger.info(f"  Success rate: {stats['success_rate'] * 100:.1f}%")
    logger.info(f"  Avg response time: {stats['avg_time'] * 1000:.2f}ms")
    logger.info(
        f"  Min/Max: {stats['min_time'] * 1000:.2f}ms / {stats['max_time'] * 1000:.2f}ms"
    )

    return stats


def run_benchmarks(iterations: int = 10, delay: float = 0.5) -> Dict[str, Any]:
    """Run benchmarks for various operations."""
    benchmark_results = {}

    # Measure system resources at start
    initial_resources = measure_system_resources()
    benchmark_results["initial_resources"] = initial_resources

    # Define operations to benchmark
    operations = [
        {
            "name": "Get Current Page",
            "tool": "mcp_davinci_resolve_switch_page",
            "params": {"page": "media"},
        },
        {
            "name": "Switch to Edit Page",
            "tool": "mcp_davinci_resolve_switch_page",
            "params": {"page": "edit"},
        },
        {
            "name": "List Timelines",
            "tool": "mcp_davinci_resolve_list_timelines_tool",
            "params": {"random_string": "benchmark"},
        },
        {
            "name": "Project Settings - Integer",
            "tool": "mcp_davinci_resolve_set_project_setting",
            "params": {"setting_name": "timelineFrameRate", "setting_value": 24},
        },
        {
            "name": "Project Settings - String",
            "tool": "mcp_davinci_resolve_set_project_setting",
            "params": {"setting_name": "timelineFrameRate", "setting_value": "24"},
        },
        {
            "name": "Clear Render Queue",
            "tool": "mcp_davinci_resolve_clear_render_queue",
            "params": {"random_string": "benchmark"},
        },
    ]

    # Run benchmarks for each operation
    for op in operations:
        benchmark_results[op["name"]] = benchmark_operation(
            op["name"], op["tool"], op["params"], iterations, delay
        )

    # Measure system resources at end
    final_resources = measure_system_resources()
    benchmark_results["final_resources"] = final_resources

    # Calculate resource usage difference
    resource_diff = {}
    for key in initial_resources:
        if key in final_resources:
            resource_diff[key] = final_resources[key] - initial_resources[key]

    benchmark_results["resource_change"] = resource_diff

    return benchmark_results


def print_summary(results: Dict[str, Any]) -> None:
    """Print a summary of benchmark results."""
    logger.info("\n" + "=" * 50)
    logger.info("BENCHMARK SUMMARY")
    logger.info("=" * 50)

    # Calculate overall statistics
    response_times = []
    success_rates = []

    for key, value in results.items():
        if key not in [
            "initial_resources",
            "final_resources",
            "resource_change",
        ] and isinstance(value, dict):
            if "avg_time" in value:
                response_times.append(value["avg_time"])
            if "success_rate" in value:
                success_rates.append(value["success_rate"])

    # Overall stats
    if response_times:
        logger.info(
            f"Overall average response time: {statistics.mean(response_times) * 1000:.2f}ms"
        )
    if success_rates:
        logger.info(
            f"Overall success rate: {statistics.mean(success_rates) * 100:.1f}%"
        )

    # Operation ranking by speed
    operation_times = []
    for key, value in results.items():
        if key not in [
            "initial_resources",
            "final_resources",
            "resource_change",
        ] and isinstance(value, dict):
            if "avg_time" in value:
                operation_times.append((key, value["avg_time"]))

    if operation_times:
        logger.info("\nOperations ranked by speed (fastest first):")
        for op, time in sorted(operation_times, key=lambda x: x[1]):
            logger.info(f"  {op}: {time * 1000:.2f}ms")

    # Resource usage
    if "resource_change" in results and results["resource_change"]:
        logger.info("\nResource usage change during benchmark:")
        for key, value in results["resource_change"].items():
            if key == "memory_mb":
                logger.info(f"  Memory: {value:.2f}MB")
            elif key == "cpu_percent":
                logger.info(f"  CPU: {value:.1f}%")
            else:
                logger.info(f"  {key}: {value}")

    logger.info("=" * 50)


def main() -> None:
    """Run the benchmark suite."""
    parser = argparse.ArgumentParser(
        description="Benchmark the DaVinci Resolve MCP Server"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Number of iterations for each benchmark (default: 10)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between benchmark iterations in seconds (default: 0.5)",
    )
    args = parser.parse_args()

    logger.info("Starting DaVinci Resolve MCP Server Benchmark")
    logger.info("=" * 50)
    logger.info(f"Iterations: {args.iterations}, Delay: {args.delay}s")

    # Run benchmarks
    results = run_benchmarks(args.iterations, args.delay)

    # Print summary
    print_summary(results)

    # Save results to file
    result_file = f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"Benchmark results saved to {result_file}")


if __name__ == "__main__":
    main()
