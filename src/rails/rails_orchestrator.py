"""Rails Orchestrator - unified coordination of all rails components.

Orchestrates the complete rails flow:
- Input validation and sanitization
- Retrieval control and validation
- Execution safety and monitoring
- Output validation and sanitization

Provides a single interface for the RAG system to use all rails consistently.
"""

from dataclasses import dataclass
from typing import Any

from src.rails.input_rails import InputRails, InputValidationResult
from src.rails.retrieval_rails import RetrievalRails, RetrievalDecision
from src.rails.execution_rails import ExecutionRails, ExecutionDecision, ExecutionResult
from src.rails.output_rails import OutputRails, OutputValidationResult


@dataclass
class RailsExecutionResult:
    """Complete result of rails execution through all stages."""
    success: bool
    final_response: str | None
    blocked_at_stage: str | None  # "input", "retrieval", "execution", "output", or None
    input_result: InputValidationResult | None
    retrieval_decision: RetrievalDecision | None
    execution_decision: ExecutionDecision | None
    execution_result: ExecutionResult | None
    output_result: OutputValidationResult | None
    trace: dict[str, Any]
    errors: list[str] | None = None


class RailsOrchestrator:
    """Unified orchestration of all rails components."""
    
    def __init__(self, settings: Any = None):
        self.settings = settings
        
        # Initialize individual rails
        self.input_rails = InputRails(
            max_length=getattr(settings, 'max_query_length', 2000) if settings else 2000,
            min_length=getattr(settings, 'min_query_length', 1) if settings else 1
        )
        
        self.retrieval_rails = RetrievalRails(
            default_max_results=getattr(settings, 'default_max_results', 10) if settings else 10,
            max_complexity=getattr(settings, 'max_query_complexity', 5) if settings else 5
        )
        
        self.execution_rails = ExecutionRails(
            default_timeout=getattr(settings, 'default_timeout', 30) if settings else 30,
            max_retries=getattr(settings, 'max_retries', 2) if settings else 2
        )
        
        self.output_rails = OutputRails(
            max_response_length=getattr(settings, 'max_response_length', 5000) if settings else 5000
        )
    
    def execute_full_rails_flow(
        self,
        query: str,
        intent: dict[str, Any],
        plan: str,
        retriever_func: callable,
        llm_func: callable,
        context: dict[str, Any]
    ) -> RailsExecutionResult:
        """Execute the complete rails flow from input to output."""
        
        trace = {
            "stages": [],
            "decisions": {},
            "monitoring": {}
        }
        errors = []
        
        # Stage 1: Input Rails
        trace["stages"].append("input_validation")
        input_result = self.input_rails.validate_and_sanitize(query)
        trace["decisions"]["input"] = {
            "is_valid": input_result.is_valid,
            "sanitized": input_result.sanitized_query != query,
            "reason": input_result.reason
        }
        
        if not input_result.is_valid:
            return RailsExecutionResult(
                success=False,
                final_response=None,
                blocked_at_stage="input",
                input_result=input_result,
                retrieval_decision=None,
                execution_decision=None,
                execution_result=None,
                output_result=None,
                trace=trace,
                errors=[input_result.reason or "Input validation failed"]
            )
        
        sanitized_query = input_result.sanitized_query
        context["sanitized_query"] = sanitized_query
        
        # Stage 2: Retrieval Rails
        trace["stages"].append("retrieval_validation")
        retrieval_decision = self.retrieval_rails.validate_retrieval_request(
            sanitized_query,
            intent,
            plan,
            context.get("top_k")
        )
        trace["decisions"]["retrieval"] = {
            "allowed": retrieval_decision.allowed,
            "scope": retrieval_decision.scope,
            "max_results": retrieval_decision.max_results,
            "reason": retrieval_decision.reason
        }
        
        if not retrieval_decision.allowed:
            return RailsExecutionResult(
                success=False,
                final_response=None,
                blocked_at_stage="retrieval",
                input_result=input_result,
                retrieval_decision=retrieval_decision,
                execution_decision=None,
                execution_result=None,
                output_result=None,
                trace=trace,
                errors=[retrieval_decision.reason or "Retrieval not allowed"]
            )
        
        # Apply retrieval decision to context
        context["retrieval_scope"] = retrieval_decision.scope
        context["max_results"] = retrieval_decision.max_results
        context["retrieval_filters"] = retrieval_decision.filters or {}
        
        # Execute retrieval with rails monitoring
        try:
            retrieval_results = retriever_func(sanitized_query, context)
            
            # Validate retrieval results
            filtered_results, retrieval_validation = self.retrieval_rails.validate_retrieval_results(
                retrieval_results,
                retrieval_decision
            )
            trace["monitoring"]["retrieval"] = retrieval_validation
            context["filtered_results"] = filtered_results
            
        except Exception as e:
            errors.append(f"Retrieval failed: {str(e)}")
            return RailsExecutionResult(
                success=False,
                final_response=None,
                blocked_at_stage="retrieval",
                input_result=input_result,
                retrieval_decision=retrieval_decision,
                execution_decision=None,
                execution_result=None,
                output_result=None,
                trace=trace,
                errors=errors
            )
        
        # Stage 3: Execution Rails
        trace["stages"].append("execution_validation")
        
        # Validate LLM execution
        prompt = context.get("prompt", "")
        temperature = context.get("temperature", 0.1)
        execution_decision = self.execution_rails.validate_llm_execution(
            prompt,
            temperature,
            context
        )
        trace["decisions"]["execution"] = {
            "allowed": execution_decision.allowed,
            "mode": execution_decision.execution_mode,
            "timeout": execution_decision.timeout,
            "reason": execution_decision.reason
        }
        
        if not execution_decision.allowed:
            return RailsExecutionResult(
                success=False,
                final_response=None,
                blocked_at_stage="execution",
                input_result=input_result,
                retrieval_decision=retrieval_decision,
                execution_decision=execution_decision,
                execution_result=None,
                output_result=None,
                trace=trace,
                errors=[execution_decision.reason or "Execution not allowed"]
            )
        
        # Execute LLM with monitoring
        execution_result = self.execution_rails.execute_with_monitoring(
            llm_func,
            execution_decision,
            context
        )
        trace["monitoring"]["execution"] = execution_result.monitoring
        
        if not execution_result.success:
            errors.extend(execution_result.errors or [])
            return RailsExecutionResult(
                success=False,
                final_response=None,
                blocked_at_stage="execution",
                input_result=input_result,
                retrieval_decision=retrieval_decision,
                execution_decision=execution_decision,
                execution_result=execution_result,
                output_result=None,
                trace=trace,
                errors=errors
            )
        
        # Validate LLM output
        llm_output, output_validation = self.execution_rails.validate_tool_output(
            "llm_synthesis",
            execution_result.result,
            execution_decision
        )
        trace["monitoring"]["llm_output"] = output_validation
        
        if llm_output is None:
            return RailsExecutionResult(
                success=False,
                final_response=None,
                blocked_at_stage="execution",
                input_result=input_result,
                retrieval_decision=retrieval_decision,
                execution_decision=execution_decision,
                execution_result=execution_result,
                output_result=None,
                trace=trace,
                errors=["LLM output validation failed"]
            )
        
        # Stage 4: Output Rails
        trace["stages"].append("output_validation")
        context["raw_response"] = str(llm_output)
        output_result = self.output_rails.validate_and_sanitize_response(
            str(llm_output),
            context
        )
        trace["decisions"]["output"] = {
            "is_valid": output_result.is_valid,
            "quality_score": output_result.quality_score,
            "filtered": len(output_result.filtered_content or []) > 0,
            "reason": output_result.reason
        }
        
        if not output_result.is_valid:
            return RailsExecutionResult(
                success=False,
                final_response=None,
                blocked_at_stage="output",
                input_result=input_result,
                retrieval_decision=retrieval_decision,
                execution_decision=execution_decision,
                execution_result=execution_result,
                output_result=output_result,
                trace=trace,
                errors=[output_result.reason or "Output validation failed"]
            )
        
        # Additional quality checks
        source_validation = self.output_rails.validate_source_attribution(
            output_result.sanitized_response,
            context.get("sources", [])
        )
        quality_validation = self.output_rails.validate_answer_quality(
            output_result.sanitized_response,
            sanitized_query,
            context
        )
        
        trace["monitoring"]["source_validation"] = source_validation
        trace["monitoring"]["quality_validation"] = quality_validation
        
        return RailsExecutionResult(
            success=True,
            final_response=output_result.sanitized_response,
            blocked_at_stage=None,
            input_result=input_result,
            retrieval_decision=retrieval_decision,
            execution_decision=execution_decision,
            execution_result=execution_result,
            output_result=output_result,
            trace=trace,
            errors=None
        )
    
    def execute_input_rails_only(self, query: str) -> InputValidationResult:
        """Execute only input rails for early validation."""
        return self.input_rails.validate_and_sanitize(query)
    
    def execute_retrieval_rails_only(
        self,
        query: str,
        intent: dict[str, Any],
        plan: str,
        top_k: int | None = None
    ) -> RetrievalDecision:
        """Execute only retrieval rails for validation."""
        return self.retrieval_rails.validate_retrieval_request(query, intent, plan, top_k)
    
    def execute_output_rails_only(
        self,
        response: str,
        context: dict[str, Any]
    ) -> OutputValidationResult:
        """Execute only output rails for validation."""
        return self.output_rails.validate_and_sanitize_response(response, context)
    
    def get_rails_status(self) -> dict[str, Any]:
        """Get status of all rails components."""
        return {
            "input_rails": {
                "max_length": self.input_rails.max_length,
                "min_length": self.input_rails.min_length,
                "injection_patterns": len(self.input_rails.injection_patterns)
            },
            "retrieval_rails": {
                "default_max_results": self.retrieval_rails.default_max_results,
                "max_complexity": self.retrieval_rails.max_complexity,
                "sensitive_patterns": len(self.retrieval_rails.sensitive_patterns)
            },
            "execution_rails": {
                "default_timeout": self.execution_rails.default_timeout,
                "max_retries": self.execution_rails.max_retries,
                "blocked_operations": len(self.execution_rails.blocked_operations)
            },
            "output_rails": {
                "max_response_length": self.output_rails.max_response_length,
                "harmful_patterns": len(self.output_rails.harmful_patterns),
                "sensitive_patterns": len(self.output_rails.sensitive_patterns)
            }
        }