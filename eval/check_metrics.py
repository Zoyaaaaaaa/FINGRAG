"""Check evaluation results against defined thresholds."""

import argparse
import json
import sys


def check_metrics(results_path: str, thresholds: dict[str, float]) -> dict[str, any]:
    """Check evaluation results against thresholds."""
    
    with open(results_path, 'r') as f:
        results = json.load(f)
    
    # Calculate metrics from results
    total = len(results)
    if total == 0:
        return {"error": "No results to check"}
    
    intent_correct = sum(1 for r in results if r.get('intent_correct', False))
    plan_correct = sum(1 for r in results if r.get('plan_correct', False))
    avg_relevance = sum(r.get('answer_relevance', 0) for r in results) / total
    
    metrics = {
        "intent_accuracy": intent_correct / total,
        "plan_accuracy": plan_correct / total,
        "answer_relevance": avg_relevance
    }
    
    # Check against thresholds
    checks = {}
    all_passed = True
    
    for metric, threshold in thresholds.items():
        actual_value = metrics.get(metric, 0)
        passed = actual_value >= threshold
        checks[metric] = {
            "threshold": threshold,
            "actual": actual_value,
            "passed": passed
        }
        if not passed:
            all_passed = False
    
    return {
        "metrics": metrics,
        "checks": checks,
        "all_passed": all_passed
    }


def main():
    parser = argparse.ArgumentParser(description="Check evaluation metrics against thresholds")
    parser.add_argument("results", help="Path to evaluation results JSON file")
    parser.add_argument("--min-intent-accuracy", type=float, default=0.95, help="Minimum intent accuracy threshold")
    parser.add_argument("--min-plan-accuracy", type=float, default=0.95, help="Minimum plan accuracy threshold")
    parser.add_argument("--min-answer-relevance", type=float, default=0.90, help="Minimum answer relevance threshold")
    
    args = parser.parse_args()
    
    thresholds = {
        "intent_accuracy": args.min_intent_accuracy,
        "plan_accuracy": args.min_plan_accuracy,
        "answer_relevance": args.min_answer_relevance
    }
    
    result = check_metrics(args.results, thresholds)
    
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1
    
    print("METRIC CHECK RESULTS")
    print("=" * 40)
    
    for metric, check in result["checks"].items():
        status = "✓ PASS" if check["passed"] else "✗ FAIL"
        print(f"{metric}:")
        print(f"  Threshold: {check['threshold']:.2%}")
        print(f"  Actual:    {check['actual']:.2%}")
        print(f"  Status:    {status}")
        print()
    
    overall_status = "✓ ALL CHECKS PASSED" if result["all_passed"] else "✗ SOME CHECKS FAILED"
    print("=" * 40)
    print(overall_status)
    
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())