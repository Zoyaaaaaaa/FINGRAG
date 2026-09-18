# FinGraphRAG Evaluation Pipeline

Comprehensive evaluation system for the FinGraphRAG RAG system using golden datasets.

## Overview

This evaluation pipeline tests your RAG system against curated golden datasets to measure:
- **Intent Classification Accuracy**: How well the system identifies FACTUAL/RELATIONAL/SEMANTIC intents
- **Query Planning Accuracy**: How well the system selects LOCAL/GLOBAL/HYBRID plans
- **Answer Relevance**: How relevant the answers are to expected responses
- **Retrieval Precision/Recall**: How well the system retrieves relevant documents
- **Cache Performance**: Effectiveness of the three-layer caching system
- **Rails Effectiveness**: How well security rails block malicious queries
- **Latency Metrics**: Response time performance

## Golden Datasets

### Dataset Files

| File | Tests | Purpose |
|------|-------|---------|
| `golden_factual.csv` | 40 | Test specific fact retrieval (LOCAL plan) |
| `golden_relational.csv` | 25 | Test relationship retrieval (HYBRID plan) |
| `golden_semantic.csv` | 30 | Test broad conceptual retrieval (GLOBAL plan) |
| `golden_edge_cases.csv` | 15 | Test rails and graceful failure |
| `golden_multihop.csv` | 10 | Test cross-row reasoning |
| `golden_aggregation.csv` | 10 | Test counting/grouping |
| `golden_cache.csv` | 5 | Test three-layer caching |

**Total**: 135 comprehensive test cases

### Dataset Format

Each CSV file contains:
- `id`: Unique test identifier
- `question`: User query to test
- `expected_answer`: Ground-truth answer
- `intent`: Expected intent (FACTUAL/RELATIONAL/SEMANTIC)
- `plan`: Expected query plan (LOCAL/GLOBAL/HYBRID)
- `source`: CSV source(s) for the answer

## Usage

### Run Single Dataset Evaluation

```bash
# Evaluate factual queries
python eval/evaluate_rag.py eval/golden_factual.csv --output results_factual.json --report report_factual.txt

# Evaluate relational queries
python eval/evaluate_rag.py eval/golden_relational.csv --output results_relational.json --report report_relational.txt

# Evaluate semantic queries
python eval/evaluate_rag.py eval/golden_semantic.csv --output results_semantic.json --report report_semantic.txt
```

### Run All Evaluations

```bash
# Run complete evaluation pipeline
python eval/run_all_evaluations.py
```

### Quick Evaluation

```bash
# Quick evaluation with console output only
python eval/evaluate_rag.py eval/golden_factual.csv
```

## Metrics Explained

### Classification Metrics

- **Intent Accuracy**: Percentage of correctly classified intents (FACTUAL/RELATIONAL/SEMANTIC)
- **Plan Accuracy**: Percentage of correctly selected query plans (LOCAL/GLOBAL/HYBRID)

### Retrieval Metrics

- **Precision**: Percentage of retrieved documents that are relevant
- **Recall**: Percentage of relevant documents that were retrieved
- **F1 Score**: Harmonic mean of precision and recall

### Answer Quality Metrics

- **Answer Relevance**: 0-1 score measuring how well the answer matches expected response
  - Uses multiple methods: exact match, contains check, semantic similarity, key term overlap
  - Combined with weighted scoring

### Performance Metrics

- **Average Latency**: Mean response time across all queries
- **Cached Latency**: Mean response time for cache hits
- **Uncached Latency**: Mean response time for cache misses
- **Cache Hit Rate**: Percentage of queries that hit any cache layer

### Security Metrics

- **Rails Effectiveness**: Percentage of adversarial queries correctly blocked
- **Blocked Rate**: Percentage of queries blocked by security rails

## Evaluation Targets

| Metric | Target | Description |
|--------|--------|-------------|
| Intent Accuracy | ≥ 95% | Correct intent classification |
| Plan Accuracy | ≥ 95% | Correct query plan selection |
| Answer Relevance | ≥ 90% | Expected answer found in response |
| Retrieval Precision | ≥ 85% | Relevant docs retrieved |
| Retrieval Recall | ≥ 80% | All relevant docs retrieved |
| F1 Score | ≥ 82% | Balanced precision/recall |
| Cache Hit Rate | ≥ 40% | After warmup, repeated queries hit cache |
| Latency (cached) | < 50ms | Cache hit response time |
| Latency (uncached) | < 2000ms | Full RAG response time |
| Rails Effectiveness | 100% | All adversarial queries blocked |

## Output Files

### JSON Results (`--output`)
Detailed per-test results including:
- Actual vs expected answers
- Intent and plan classification
- Relevance scores
- Latency measurements
- Cache hit information
- Error details

### Text Report (`--report`)
Human-readable evaluation report including:
- Overall metrics summary
- Per-intent breakdown
- Per-plan breakdown
- Failed test analysis
- Error case listing

## Advanced Usage

### Custom Evaluation

```python
from eval.evaluate_rag import RAGEvaluator

# Initialize evaluator
evaluator = RAGEvaluator()

# Evaluate single query
test_case = {
    'id': 'CUSTOM001',
    'question': 'What is the relationship between Reliance and CATL?',
    'expected_answer': 'Technology_Partnership',
    'expected_intent': 'RELATIONAL',
    'expected_plan': 'HYBRID',
    'source': 'stock_company.csv + stock_report.csv'
}

result = evaluator.evaluate_query(test_case)
print(f"Intent: {result.actual_intent} (expected: {result.expected_intent})")
print(f"Plan: {result.actual_plan} (expected: {result.expected_plan})")
print(f"Relevance: {result.answer_relevance:.2f}")
```

### Batch Evaluation

```python
from eval.evaluate_rag import RAGEvaluator
import csv

evaluator = RAGEvaluator()

# Evaluate multiple CSV files
datasets = [
    'eval/golden_factual.csv',
    'eval/golden_relational.csv', 
    'eval/golden_semantic.csv'
]

all_results = []
for dataset in datasets:
    results = evaluator.evaluate_dataset(dataset)
    all_results.extend(results)

# Calculate combined metrics
metrics = evaluator.calculate_metrics(all_results)
report = evaluator.generate_report(all_results, metrics)
print(report)
```

## Troubleshooting

### Common Issues

**Issue**: "Connection errors to Neo4j/Qdrant"
- **Solution**: Ensure your databases are running and accessible
- **Check**: Sidebar "System Status" in Streamlit UI

**Issue**: "Low intent accuracy"
- **Solution**: Review the `_understand` function in `orchestrator.py`
- **Check**: Keyword patterns for intent detection

**Issue**: "Low answer relevance"
- **Solution**: Review retrieval parameters and context building
- **Check**: Top-k values, context length limits

**Issue**: "High latency"
- **Solution**: Check network latency to external services
- **Check**: Database query performance, embedding generation speed

## Continuous Integration

### GitHub Actions Example

```yaml
name: RAG Evaluation

on: [push, pull_request]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.14'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      - name: Run evaluation
        run: |
          python eval/evaluate_rag.py eval/golden_factual.csv --output results.json
      - name: Check metrics
        run: |
          python eval/check_metrics.py results.json --min-intent-accuracy 0.95
```

## Contributing

When adding new test cases to the golden datasets:

1. **Ground Truth**: Ensure answers are directly from the CSV files
2. **Clear Intent**: Assign appropriate intent (FACTUAL/RELATIONAL/SEMANTIC)
3. **Correct Plan**: Assign appropriate plan (LOCAL/GLOBAL/HYBRID)
4. **Unique IDs**: Use unique test IDs (F001, R001, S001, etc.)
5. **Source Tracking**: Specify which CSV file(s) contain the answer

## License

Part of the FinGraphRAG project.