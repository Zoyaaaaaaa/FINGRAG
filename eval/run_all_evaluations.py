"""Run all golden dataset evaluations and generate combined report."""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime


def run_evaluation(dataset_path: str, output_path: str, report_path: str, csv_results: str, csv_metrics: str) -> bool:
    """Run single evaluation and return success status."""
    cmd = [
        sys.executable, 
        "eval/evaluate_rag.py", 
        dataset_path,
        "--output", output_path,
        "--report", report_path,
        "--csv-results", csv_results,
        "--csv-metrics", csv_metrics
    ]
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"ERROR: {dataset_path} evaluation failed")
        print(result.stderr)
        return False
    
    print(result.stdout)
    return True


def main():
    eval_dir = Path("eval")
    results_dir = Path("eval/results")
    reports_dir = Path("eval/reports")
    history_dir = Path("eval/history")
    
    # Create directories
    results_dir.mkdir(exist_ok=True)
    reports_dir.mkdir(exist_ok=True)
    history_dir.mkdir(exist_ok=True)
    
    # Define datasets
    datasets = {
        "factual": "eval/golden_factual.csv",
        "relational": "eval/golden_relational.csv", 
        "semantic": "eval/golden_semantic.csv",
        "edge_cases": "eval/golden_edge_cases.csv",
        "multihop": "eval/golden_multihop.csv",
        "aggregation": "eval/golden_aggregation.csv",
        "cache": "eval/golden_cache.csv"
    }
    
    # Run evaluations
    print("=" * 80)
    print("FinGraphRAG Complete Evaluation Pipeline")
    print("=" * 80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    results = {}
    for name, dataset_path in datasets.items():
        if not Path(dataset_path).exists():
            print(f"WARNING: {dataset_path} not found, skipping")
            continue
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f"eval/results/{name}_results_{timestamp}.json"
        report_path = f"eval/reports/{name}_report_{timestamp}.txt"
        csv_results = f"eval/history/{name}_results_{timestamp}.csv"
        csv_metrics = f"eval/history/{name}_metrics_{timestamp}.csv"
        
        success = run_evaluation(dataset_path, output_path, report_path, csv_results, csv_metrics)
        results[name] = {
            "success": success,
            "output": output_path,
            "report": report_path,
            "csv_results": csv_results,
            "csv_metrics": csv_metrics
        }
        
        print(f"{'✓' if success else '✗'} {name}: {'PASSED' if success else 'FAILED'}")
        print()
    
    # Generate combined summary
    print("=" * 80)
    print("EVALUATION SUMMARY")
    print("=" * 80)
    
    total = len(results)
    passed = sum(1 for r in results.values() if r["success"])
    
    print(f"Total Datasets: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {total - passed}")
    print()
    
    # List individual reports
    print("Individual Reports:")
    for name, result in results.items():
        status = "✓ PASSED" if result["success"] else "✗ FAILED"
        print(f"  {name:15s}: {status}")
        print(f"    JSON:      {result['output']}")
        print(f"    Report:    {result['report']}")
        print(f"    CSV Res:   {result['csv_results']}")
        print(f"    CSV Met:   {result['csv_metrics']}")
    
    print()
    print(f"History files saved to: eval/history/")
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())