"""Test only the rails components without full system initialization."""

from src.rails import RailsOrchestrator, InputRails, RetrievalRails, ExecutionRails, OutputRails
from src.config.settings import get_settings


def test_rails_only():
    """Test rails components independently."""
    
    print("Testing Rails Components (No External Dependencies)")
    print("=" * 60)
    
    settings = get_settings()
    orchestrator = RailsOrchestrator(settings)
    
    # Test cases
    test_cases = [
        {
            'query': "What is the company code for Reliance Industries?",
            'expected_intent': 'FACTUAL',
            'expected_plan': 'LOCAL'
        },
        {
            'query': "What is the relationship between JSW and Chery?",
            'expected_intent': 'RELATIONAL', 
            'expected_plan': 'HYBRID'
        },
        {
            'query': "Tell me about electric vehicle partnerships in India.",
            'expected_intent': 'SEMANTIC',
            'expected_plan': 'GLOBAL'
        },
        {
            'query': "What is the personal phone number of the CEO?",
            'should_block': True,
            'expected_block_stage': 'retrieval'
        },
        {
            'query': "DROP TABLE companies;",
            'should_block': True,
            'expected_block_stage': 'input'
        },
        {
            'query': "<script>alert('xss')</script>",
            'should_block': True,
            'expected_block_stage': 'input'
        }
    ]
    
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_case['query']}")
        print("-" * 60)
        
        result = {
            'query': test_case['query'],
            'input_passed': False,
            'retrieval_allowed': False,
            'output_valid': False,
            'blocked_at': None
        }
        
        # Test input rails
        input_result = orchestrator.execute_input_rails_only(test_case['query'])
        print(f"Input Rails: {'PASSED' if input_result.is_valid else 'BLOCKED'}")
        if input_result.is_valid:
            result['input_passed'] = True
            print(f"  Sanitized: {input_result.sanitized_query}")
        else:
            print(f"  Reason: {input_result.reason}")
            result['blocked_at'] = 'input'
        
        # Test retrieval rails if input passed
        if input_result.is_valid:
            intent = {'intent': test_case.get('expected_intent', 'SEMANTIC'), 'entities': [], 'domain': 'financial'}
            plan = test_case.get('expected_plan', 'GLOBAL')
            
            retrieval_decision = orchestrator.execute_retrieval_rails_only(
                test_case['query'], intent, plan, 8
            )
            print(f"Retrieval Rails: {'ALLOWED' if retrieval_decision.allowed else 'BLOCKED'}")
            if retrieval_decision.allowed:
                result['retrieval_allowed'] = True
                print(f"  Scope: {retrieval_decision.scope}")
                print(f"  Max Results: {retrieval_decision.max_results}")
            else:
                print(f"  Reason: {retrieval_decision.reason}")
                result['blocked_at'] = 'retrieval'
        
        # Test output rails with mock response
        mock_response = "This is a test response for the query."
        output_result = orchestrator.execute_output_rails_only(
            mock_response,
            {'query': test_case['query'], 'sources': []}
        )
        print(f"Output Rails: {'VALID' if output_result.is_valid else 'INVALID'}")
        if output_result.is_valid:
            result['output_valid'] = True
            print(f"  Quality Score: {output_result.quality_score}")
        else:
            print(f"  Reason: {output_result.reason}")
            result['blocked_at'] = 'output'
        
        # Check if test expectations met
        test_passed = True
        if test_case.get('should_block'):
            if result['blocked_at'] != test_case.get('expected_block_stage'):
                test_passed = False
                print(f"  FAIL: Expected block at {test_case.get('expected_block_stage')}, got {result['blocked_at']}")
        else:
            if not result['input_passed'] or not result['retrieval_allowed']:
                test_passed = False
                print(f"  FAIL: Query was blocked unexpectedly")
        
        result['test_passed'] = test_passed
        results.append(result)
        
        print(f"Result: {'PASS' if test_passed else 'FAIL'}")
    
    # Summary
    print("\n" + "=" * 60)
    print("RAILS TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for r in results if r['test_passed'])
    total = len(results)
    
    print(f"Total Tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {total - passed}")
    print(f"Success Rate: {passed/total:.1%}")
    
    # Show rails status
    print("\nRAILS CONFIGURATION STATUS:")
    status = orchestrator.get_rails_status()
    for component, config in status.items():
        print(f"  {component}:")
        for key, value in config.items():
            print(f"    {key}: {value}")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    import sys
    sys.exit(test_rails_only())