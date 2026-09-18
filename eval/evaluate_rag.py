"""RAG Evaluation Script using Golden Dataset.

Evaluates FinGraphRAG system against golden dataset with comprehensive metrics:
- Intent classification accuracy
- Query plan accuracy  
- Answer relevance (precision/recall/F1)
- Retrieval precision/recall
- Cache performance
- Rails effectiveness
- Latency metrics
"""

import csv
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher

from src.config.settings import get_settings
from src.orchestrator import FinGraphRAG
from src.tools.semantic_cache import MultiLayerCache


@dataclass
class EvaluationResult:
    """Result of evaluating a single query."""
    test_id: str
    question: str
    expected_answer: str
    expected_intent: str
    expected_plan: str
    actual_answer: str
    actual_intent: str
    actual_plan: str
    intent_correct: bool
    plan_correct: bool
    answer_relevance: float  # 0-1 score
    latency_ms: float
    cache_hit: bool
    cache_layer: str | None
    blocked: bool
    sources_count: int
    graph_context_count: int
    vector_context_count: int
    error: str | None = None


@dataclass
class EvaluationMetrics:
    """Overall evaluation metrics."""
    total_tests: int
    intent_accuracy: float
    plan_accuracy: float
    answer_relevance_avg: float
    retrieval_precision: float
    retrieval_recall: float
    f1_score: float
    cache_hit_rate: float
    blocked_rate: float
    avg_latency_ms: float
    avg_latency_cached_ms: float
    avg_latency_uncached_ms: float
    rails_effectiveness: float
    per_intent_metrics: dict[str, dict[str, float]]
    per_plan_metrics: dict[str, dict[str, float]]


class RAGEvaluator:
    """Evaluates RAG system against golden dataset."""
    
    def __init__(self, settings: Any = None):
        self.settings = settings or get_settings()
        self.rag_system = FinGraphRAG(self.settings)
        self.cache = MultiLayerCache(self.settings)
        
    def _calculate_answer_relevance(self, expected: str, actual: str) -> float:
        """Calculate answer relevance using multiple methods."""
        if not actual or not expected:
            return 0.0
        
        # Method 1: Exact match
        if expected.lower() == actual.lower():
            return 1.0
        
        # Method 2: Contains check
        if expected.lower() in actual.lower():
            return 0.9
        
        # Method 3: Semantic similarity (difflib)
        similarity = SequenceMatcher(None, expected.lower(), actual.lower()).ratio()
        
        # Method 4: Key term overlap
        expected_terms = set(expected.lower().split())
        actual_terms = set(actual.lower().split())
        overlap = len(expected_terms & actual_terms) / max(len(expected_terms), 1)
        
        # Combine methods with weights
        relevance = (similarity * 0.6) + (overlap * 0.4)
        return min(relevance, 1.0)
    
    def _calculate_retrieval_metrics(self, expected_sources: str, actual_sources: list) -> dict[str, float]:
        """Calculate retrieval precision and recall."""
        if not expected_sources or not actual_sources:
            return {"precision": 0.0, "recall": 0.0}
        
        # Parse expected sources
        expected_files = set()
        for source in expected_sources.split('+'):
            expected_files.add(source.strip().lower())
        
        # Get actual source files
        actual_files = set()
        for source in actual_sources:
            if isinstance(source, dict):
                source_file = source.get('metadata', {}).get('source', '')
                if source_file:
                    actual_files.add(source_file.lower())
        
        if not expected_files:
            return {"precision": 1.0, "recall": 1.0}
        
        # Calculate precision and recall
        true_positives = len(expected_files & actual_files)
        false_positives = len(actual_files - expected_files)
        false_negatives = len(expected_files - actual_files)
        
        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0.0
        
        return {"precision": precision, "recall": recall}
    
    def evaluate_query(self, test_case: dict[str, str]) -> EvaluationResult:
        """Evaluate a single query against the RAG system."""
        start_time = time.time()
        
        try:
            # Check cache first
            cache_entry, cache_layer = self.cache.lookup(test_case['question'])
            
            if cache_entry:
                # Cache hit - use cached answer
                actual_answer = cache_entry.answer
                actual_intent = "CACHED"
                actual_plan = "CACHED"
                cache_hit = True
                latency_ms = (time.time() - start_time) * 1000
                blocked = False
                sources = []
                graph_context = []
                vector_context = []
            else:
                # Cache miss - run full RAG
                response = self.rag_system.query(
                    test_case['question'],
                    session_id="evaluation",
                    top_k=8
                )
                
                actual_answer = response.get('answer', '')
                actual_intent = response.get('intent', {}).get('intent', 'UNKNOWN')
                actual_plan = response.get('plan', 'UNKNOWN')
                cache_hit = False
                latency_ms = (time.time() - start_time) * 1000
                blocked = response.get('blocked', False)
                sources = response.get('sources', [])
                graph_context = response.get('graph_context', [])
                vector_context = response.get('vector_context', [])
                
                # Store in cache (only if not blocked and successful)
                if not blocked and actual_answer and actual_intent != 'ERROR':
                    try:
                        self.cache.put_response(test_case['question'], actual_answer)
                    except Exception:
                        pass  # Cache storage failure shouldn't break evaluation
            
            # Calculate metrics
            intent_correct = actual_intent == test_case['expected_intent']
            plan_correct = actual_plan == test_case['expected_plan']
            answer_relevance = self._calculate_answer_relevance(
                test_case['expected_answer'], 
                actual_answer
            )
            
            # Get retrieval metrics
            retrieval_metrics = self._calculate_retrieval_metrics(
                test_case['source'],
                sources
            )
            
            return EvaluationResult(
                test_id=test_case['id'],
                question=test_case['question'],
                expected_answer=test_case['expected_answer'],
                expected_intent=test_case['expected_intent'],
                expected_plan=test_case['expected_plan'],
                actual_answer=actual_answer,
                actual_intent=actual_intent,
                actual_plan=actual_plan,
                intent_correct=intent_correct,
                plan_correct=plan_correct,
                answer_relevance=answer_relevance,
                latency_ms=latency_ms,
                cache_hit=cache_hit,
                cache_layer=cache_layer if cache_hit else None,
                blocked=blocked,
                sources_count=len(sources),
                graph_context_count=len(graph_context),
                vector_context_count=len(vector_context),
                retrieval_precision=retrieval_metrics['precision'],
                retrieval_recall=retrieval_metrics['recall'],
                error=None
            )
            
        except Exception as e:
            # Handle connection errors gracefully
            error_msg = str(e)
            if "Neo4j" in error_msg or "connection" in error_msg.lower():
                actual_intent = "CONNECTION_ERROR"
                actual_plan = "CONNECTION_ERROR"
            else:
                actual_intent = "ERROR"
                actual_plan = "ERROR"
                
            return EvaluationResult(
                test_id=test_case['id'],
                question=test_case['question'],
                expected_answer=test_case['expected_answer'],
                expected_intent=test_case['expected_intent'],
                expected_plan=test_case['expected_plan'],
                actual_answer='',
                actual_intent=actual_intent,
                actual_plan=actual_plan,
                intent_correct=False,
                plan_correct=False,
                answer_relevance=0.0,
                latency_ms=(time.time() - start_time) * 1000,
                cache_hit=False,
                cache_layer=None,
                blocked=False,
                sources_count=0,
                graph_context_count=0,
                vector_context_count=0,
                error=error_msg
            )
    
    def evaluate_dataset(self, csv_path: str) -> list[EvaluationResult]:
        """Evaluate entire golden dataset CSV."""
        results = []
        
        with open(csv_path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                result = self.evaluate_query(row)
                results.append(result)
                print(f"Evaluated {result.test_id}: {result.actual_intent} / {result.actual_plan} - Relevance: {result.answer_relevance:.2f}")
        
        return results
    
    def calculate_metrics(self, results: list[EvaluationResult]) -> EvaluationMetrics:
        """Calculate overall evaluation metrics."""
        if not results:
            return EvaluationMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, {}, {})
        
        total = len(results)
        
        # Basic metrics
        intent_correct = sum(r.intent_correct for r in results)
        plan_correct = sum(r.plan_correct for r in results)
        avg_relevance = sum(r.answer_relevance for r in results) / total
        cache_hits = sum(r.cache_hit for r in results)
        blocked = sum(r.blocked for r in results)
        
        # Retrieval metrics
        retrieval_precision = sum(r.retrieval_precision for r in results) / total
        retrieval_recall = sum(r.retrieval_recall for r in results) / total
        
        # F1 score
        f1 = 2 * (retrieval_precision * retrieval_recall) / (retrieval_precision + retrieval_recall) if (retrieval_precision + retrieval_recall) > 0 else 0.0
        
        # Latency metrics
        cached_latencies = [r.latency_ms for r in results if r.cache_hit]
        uncached_latencies = [r.latency_ms for r in results if not r.cache_hit]
        avg_latency = sum(r.latency_ms for r in results) / total
        avg_cached = sum(cached_latencies) / len(cached_latencies) if cached_latencies else 0.0
        avg_uncached = sum(uncached_latencies) / len(uncached_latencies) if uncached_latencies else 0.0
        
        # Rails effectiveness (edge cases)
        edge_case_results = [r for r in results if r.test_id.startswith('E')]
        rails_effective = 0.0
        if edge_case_results:
            rails_correct = sum(1 for r in edge_case_results if r.blocked or 'BLOCKED' in r.actual_answer.upper())
            rails_effective = rails_correct / len(edge_case_results)
        
        # Per-intent metrics
        per_intent = {}
        for intent in ['FACTUAL', 'RELATIONAL', 'SEMANTIC']:
            intent_results = [r for r in results if r.expected_intent == intent]
            if intent_results:
                per_intent[intent] = {
                    'count': len(intent_results),
                    'accuracy': sum(r.intent_correct for r in intent_results) / len(intent_results),
                    'avg_relevance': sum(r.answer_relevance for r in intent_results) / len(intent_results),
                    'avg_latency': sum(r.latency_ms for r in intent_results) / len(intent_results)
                }
        
        # Per-plan metrics
        per_plan = {}
        for plan in ['LOCAL', 'GLOBAL', 'HYBRID']:
            plan_results = [r for r in results if r.expected_plan == plan]
            if plan_results:
                per_plan[plan] = {
                    'count': len(plan_results),
                    'accuracy': sum(r.plan_correct for r in plan_results) / len(plan_results),
                    'avg_relevance': sum(r.answer_relevance for r in plan_results) / len(plan_results),
                    'avg_latency': sum(r.latency_ms for r in plan_results) / len(plan_results)
                }
        
        return EvaluationMetrics(
            total_tests=total,
            intent_accuracy=intent_correct / total,
            plan_accuracy=plan_correct / total,
            answer_relevance_avg=avg_relevance,
            retrieval_precision=retrieval_precision,
            retrieval_recall=retrieval_recall,
            f1_score=f1,
            cache_hit_rate=cache_hits / total,
            blocked_rate=blocked / total,
            avg_latency_ms=avg_latency,
            avg_latency_cached_ms=avg_cached,
            avg_latency_uncached_ms=avg_uncached,
            rails_effectiveness=rails_effective,
            per_intent_metrics=per_intent,
            per_plan_metrics=per_plan
        )
    
    def save_results_csv(self, results: list[EvaluationResult], csv_path: str):
        """Save evaluation results to CSV file with timestamp."""
        # Create directory if it doesn't exist
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'test_id', 'question', 'expected_answer', 'actual_answer',
                'expected_intent', 'actual_intent', 'intent_correct',
                'expected_plan', 'actual_plan', 'plan_correct',
                'answer_relevance', 'latency_ms', 'cache_hit', 'cache_layer',
                'blocked', 'sources_count', 'graph_context_count', 'vector_context_count',
                'retrieval_precision', 'retrieval_recall', 'error'
            ])
            
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for result in results:
                writer.writerow([
                    timestamp,
                    result.test_id,
                    result.question,
                    result.expected_answer,
                    result.actual_answer,
                    result.expected_intent,
                    result.actual_intent,
                    result.intent_correct,
                    result.expected_plan,
                    result.actual_plan,
                    result.plan_correct,
                    f"{result.answer_relevance:.4f}",
                    f"{result.latency_ms:.2f}",
                    result.cache_hit,
                    result.cache_layer or '',
                    result.blocked,
                    result.sources_count,
                    result.graph_context_count,
                    result.vector_context_count,
                    f"{result.retrieval_precision:.4f}",
                    f"{result.retrieval_recall:.4f}",
                    result.error or ''
                ])
    
    def save_metrics_csv(self, metrics: EvaluationMetrics, csv_path: str):
        """Save evaluation metrics to CSV file with timestamp."""
        # Create directory if it doesn't exist
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Overall metrics
            writer.writerow(['timestamp', 'metric', 'value'])
            writer.writerow([timestamp, 'total_tests', metrics.total_tests])
            writer.writerow([timestamp, 'intent_accuracy', f"{metrics.intent_accuracy:.4f}"])
            writer.writerow([timestamp, 'plan_accuracy', f"{metrics.plan_accuracy:.4f}"])
            writer.writerow([timestamp, 'answer_relevance_avg', f"{metrics.answer_relevance_avg:.4f}"])
            writer.writerow([timestamp, 'retrieval_precision', f"{metrics.retrieval_precision:.4f}"])
            writer.writerow([timestamp, 'retrieval_recall', f"{metrics.retrieval_recall:.4f}"])
            writer.writerow([timestamp, 'f1_score', f"{metrics.f1_score:.4f}"])
            writer.writerow([timestamp, 'cache_hit_rate', f"{metrics.cache_hit_rate:.4f}"])
            writer.writerow([timestamp, 'blocked_rate', f"{metrics.blocked_rate:.4f}"])
            writer.writerow([timestamp, 'avg_latency_ms', f"{metrics.avg_latency_ms:.2f}"])
            writer.writerow([timestamp, 'avg_latency_cached_ms', f"{metrics.avg_latency_cached_ms:.2f}"])
            writer.writerow([timestamp, 'avg_latency_uncached_ms', f"{metrics.avg_latency_uncached_ms:.2f}"])
            writer.writerow([timestamp, 'rails_effectiveness', f"{metrics.rails_effectiveness:.4f}"])
            
            # Per-intent metrics
            for intent, intent_metrics in metrics.per_intent_metrics.items():
                writer.writerow([timestamp, f'intent_{intent}_count', intent_metrics['count']])
                writer.writerow([timestamp, f'intent_{intent}_accuracy', f"{intent_metrics['accuracy']:.4f}"])
                writer.writerow([timestamp, f'intent_{intent}_relevance', f"{intent_metrics['avg_relevance']:.4f}"])
                writer.writerow([timestamp, f'intent_{intent}_latency', f"{intent_metrics['avg_latency']:.2f}"])
            
            # Per-plan metrics
            for plan, plan_metrics in metrics.per_plan_metrics.items():
                writer.writerow([timestamp, f'plan_{plan}_count', plan_metrics['count']])
                writer.writerow([timestamp, f'plan_{plan}_accuracy', f"{plan_metrics['accuracy']:.4f}"])
                writer.writerow([timestamp, f'plan_{plan}_relevance', f"{plan_metrics['avg_relevance']:.4f}"])
                writer.writerow([timestamp, f'plan_{plan}_latency', f"{plan_metrics['avg_latency']:.2f}"])
    
    def generate_report(self, results: list[EvaluationResult], metrics: EvaluationMetrics) -> str:
        """Generate comprehensive evaluation report."""
        report = []
        report.append("=" * 80)
        report.append("FinGraphRAG Evaluation Report")
        report.append("=" * 80)
        report.append("")
        
        # Overall metrics
        report.append("OVERALL METRICS")
        report.append("-" * 40)
        report.append(f"Total Tests: {metrics.total_tests}")
        report.append(f"Intent Accuracy: {metrics.intent_accuracy:.2%}")
        report.append(f"Plan Accuracy: {metrics.plan_accuracy:.2%}")
        report.append(f"Answer Relevance: {metrics.answer_relevance_avg:.2%}")
        report.append(f"Retrieval Precision: {metrics.retrieval_precision:.2%}")
        report.append(f"Retrieval Recall: {metrics.retrieval_recall:.2%}")
        report.append(f"F1 Score: {metrics.f1_score:.2%}")
        report.append(f"Cache Hit Rate: {metrics.cache_hit_rate:.2%}")
        report.append(f"Rails Effectiveness: {metrics.rails_effectiveness:.2%}")
        report.append("")
        
        # Latency metrics
        report.append("LATENCY METRICS")
        report.append("-" * 40)
        report.append(f"Average Latency: {metrics.avg_latency_ms:.2f}ms")
        report.append(f"Cached Latency: {metrics.avg_latency_cached_ms:.2f}ms")
        report.append(f"Uncached Latency: {metrics.avg_latency_uncached_ms:.2f}ms")
        report.append("")
        
        # Per-intent metrics
        report.append("PER-INTENT METRICS")
        report.append("-" * 40)
        for intent, intent_metrics in metrics.per_intent_metrics.items():
            report.append(f"{intent}:")
            report.append(f"  Count: {intent_metrics['count']}")
            report.append(f"  Accuracy: {intent_metrics['accuracy']:.2%}")
            report.append(f"  Relevance: {intent_metrics['avg_relevance']:.2%}")
            report.append(f"  Latency: {intent_metrics['avg_latency']:.2f}ms")
        report.append("")
        
        # Per-plan metrics
        report.append("PER-PLAN METRICS")
        report.append("-" * 40)
        for plan, plan_metrics in metrics.per_plan_metrics.items():
            report.append(f"{plan}:")
            report.append(f"  Count: {plan_metrics['count']}")
            report.append(f"  Accuracy: {plan_metrics['accuracy']:.2%}")
            report.append(f"  Relevance: {plan_metrics['avg_relevance']:.2%}")
            report.append(f"  Latency: {plan_metrics['avg_latency']:.2f}ms")
        report.append("")
        
        # Failed tests
        failed_tests = [r for r in results if not r.intent_correct or not r.plan_correct or r.answer_relevance < 0.5]
        if failed_tests:
            report.append("FAILED TESTS")
            report.append("-" * 40)
            for result in failed_tests[:10]:  # Show first 10 failures
                report.append(f"{result.test_id}: {result.question}")
                report.append(f"  Intent: {result.expected_intent} -> {result.actual_intent} ({'OK' if result.intent_correct else 'FAIL'})")
                report.append(f"  Plan: {result.expected_plan} -> {result.actual_plan} ({'OK' if result.plan_correct else 'FAIL'})")
                report.append(f"  Relevance: {result.answer_relevance:.2f}")
                if result.error:
                    report.append(f"  Error: {result.error}")
            report.append("")
        
        # Error cases
        error_cases = [r for r in results if r.error]
        if error_cases:
            report.append("ERROR CASES")
            report.append("-" * 40)
            for result in error_cases:
                report.append(f"{result.test_id}: {result.error}")
            report.append("")
        
        return "\n".join(report)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Evaluate FinGraphRAG against golden dataset")
    parser.add_argument("dataset", help="Path to golden dataset CSV file")
    parser.add_argument("--output", help="Output JSON file for detailed results")
    parser.add_argument("--report", help="Output text file for evaluation report")
    parser.add_argument("--csv-results", help="Output CSV file for detailed results with timestamp")
    parser.add_argument("--csv-metrics", help="Output CSV file for metrics with timestamp")
    
    args = parser.parse_args()
    
    # Generate timestamp-based filenames if not provided
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dataset_name = Path(args.dataset).stem
    
    if not args.csv_results:
        args.csv_results = f"eval/history/{dataset_name}_results_{timestamp}.csv"
    
    if not args.csv_metrics:
        args.csv_metrics = f"eval/history/{dataset_name}_metrics_{timestamp}.csv"
    
    print("Initializing RAG system...")
    evaluator = RAGEvaluator()
    
    print(f"Evaluating dataset: {args.dataset}")
    results = evaluator.evaluate_dataset(args.dataset)
    
    print("Calculating metrics...")
    metrics = evaluator.calculate_metrics(results)
    
    print("Generating report...")
    report = evaluator.generate_report(results, metrics)
    print(report)
    
    # Save CSV results with timestamp
    print(f"Saving CSV results to: {args.csv_results}")
    evaluator.save_results_csv(results, args.csv_results)
    
    # Save CSV metrics with timestamp
    print(f"Saving CSV metrics to: {args.csv_metrics}")
    evaluator.save_metrics_csv(metrics, args.csv_metrics)
    
    # Save detailed JSON results if requested
    if args.output:
        detailed_results = [
            {
                'test_id': r.test_id,
                'question': r.question,
                'expected_answer': r.expected_answer,
                'actual_answer': r.actual_answer,
                'expected_intent': r.expected_intent,
                'actual_intent': r.actual_intent,
                'expected_plan': r.expected_plan,
                'actual_plan': r.actual_plan,
                'intent_correct': r.intent_correct,
                'plan_correct': r.plan_correct,
                'answer_relevance': r.answer_relevance,
                'latency_ms': r.latency_ms,
                'cache_hit': r.cache_hit,
                'blocked': r.blocked,
                'error': r.error
            }
            for r in results
        ]
        
        with open(args.output, 'w') as f:
            json.dump(detailed_results, f, indent=2)
        print(f"Detailed results saved to: {args.output}")
    
    # Save report if requested
    if args.report:
        with open(args.report, 'w') as f:
            f.write(report)
        print(f"Report saved to: {args.report}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())