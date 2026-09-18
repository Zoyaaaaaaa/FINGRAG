"""Execution Rails - controls and validates tool execution and LLM operations.

Provides guardrails for:
- Tool invocation control
- LLM prompt safety
- Execution time limits
- Resource usage monitoring
- Tool output validation
"""

import re
import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ExecutionDecision:
    """Result of execution rail validation."""
    allowed: bool
    execution_mode: str  # "full", "restricted", "fallback"
    timeout: int
    reason: str | None = None
    monitoring: dict[str, Any] | None = None


@dataclass
class ExecutionResult:
    """Result of tool execution with monitoring."""
    success: bool
    result: Any
    execution_time: float
    monitoring: dict[str, Any]
    errors: list[str] | None = None


class ExecutionRails:
    """Controls and validates tool execution and LLM operations."""
    
    def __init__(self, default_timeout: int = 30, max_retries: int = 2):
        self.default_timeout = default_timeout
        self.max_retries = max_retries
        
        # Dangerous operations to block
        self.blocked_operations = [
            "file_delete",
            "file_write", 
            "system_execute",
            "network_scan",
            "database_drop",
            "database_delete",
        ]
        
        # Resource limits
        self.max_context_length = 20000
        self.max_tool_calls_per_query = 5
        self.llm_temperature_range = (0.0, 1.0)
    
    def validate_tool_execution(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        context: dict[str, Any]
    ) -> ExecutionDecision:
        """Validate tool execution requests."""
        
        # Check for blocked operations
        if tool_name in self.blocked_operations:
            return ExecutionDecision(
                allowed=False,
                execution_mode="none",
                timeout=0,
                reason=f"Blocked operation: {tool_name}",
                monitoring={"blocked_operation": tool_name}
            )
        
        # Check for dangerous parameters
        if self._has_dangerous_parameters(parameters):
            return ExecutionDecision(
                allowed=False,
                execution_mode="none", 
                timeout=0,
                reason="Dangerous parameters detected",
                monitoring={"dangerous_params": True}
            )
        
        # Check tool call frequency
        tool_calls = context.get("tool_call_count", 0)
        if tool_calls >= self.max_tool_calls_per_query:
            return ExecutionDecision(
                allowed=True,
                execution_mode="restricted",
                timeout=min(self.default_timeout, 10),
                reason=f"Tool call limit reached ({tool_calls}), restricting execution",
                monitoring={"tool_call_limit": True}
            )
        
        # Determine execution mode based on tool sensitivity
        execution_mode = self._determine_execution_mode(tool_name, parameters)
        timeout = self._determine_timeout(tool_name, execution_mode)
        
        return ExecutionDecision(
            allowed=True,
            execution_mode=execution_mode,
            timeout=timeout,
            reason=None,
            monitoring={"tool_name": tool_name}
        )
    
    def validate_llm_execution(
        self,
        prompt: str,
        temperature: float,
        context: dict[str, Any]
    ) -> ExecutionDecision:
        """Validate LLM execution requests."""
        
        # Check prompt length
        if len(prompt) > self.max_context_length:
            return ExecutionDecision(
                allowed=True,
                execution_mode="restricted",
                timeout=self.default_timeout,
                reason=f"Prompt too long ({len(prompt)} chars), truncating",
                monitoring={"prompt_truncated": True}
            )
        
        # Check temperature range
        if not (self.llm_temperature_range[0] <= temperature <= self.llm_temperature_range[1]):
            return ExecutionDecision(
                allowed=True,
                execution_mode="restricted",
                timeout=self.default_timeout,
                reason=f"Temperature {temperature} out of range, clamping",
                monitoring={"temperature_clamped": True}
            )
        
        # Check for prompt injection patterns
        if self._has_prompt_injection(prompt):
            return ExecutionDecision(
                allowed=False,
                execution_mode="none",
                timeout=0,
                reason="Prompt injection pattern detected",
                monitoring={"prompt_injection": True}
            )
        
        return ExecutionDecision(
            allowed=True,
            execution_mode="full",
            timeout=self.default_timeout,
            reason=None,
            monitoring={"llm_execution": True}
        )
    
    def execute_with_monitoring(
        self,
        func: Callable,
        decision: ExecutionDecision,
        *args,
        **kwargs
    ) -> ExecutionResult:
        """Execute function with monitoring and safety controls."""
        start_time = time.time()
        errors = []
        monitoring = decision.monitoring or {}
        
        try:
            # Apply timeout if specified
            if decision.timeout > 0:
                result = self._execute_with_timeout(func, decision.timeout, *args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            execution_time = time.time() - start_time
            monitoring["execution_time"] = execution_time
            monitoring["success"] = True
            
            return ExecutionResult(
                success=True,
                result=result,
                execution_time=execution_time,
                monitoring=monitoring,
                errors=None
            )
            
        except TimeoutError as e:
            execution_time = time.time() - start_time
            errors.append(f"Execution timeout after {execution_time:.2f}s")
            monitoring["timeout"] = True
            monitoring["execution_time"] = execution_time
            
            return ExecutionResult(
                success=False,
                result=None,
                execution_time=execution_time,
                monitoring=monitoring,
                errors=errors
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            errors.append(str(e))
            monitoring["error"] = str(e)
            monitoring["execution_time"] = execution_time
            
            return ExecutionResult(
                success=False,
                result=None,
                execution_time=execution_time,
                monitoring=monitoring,
                errors=errors
            )
    
    def validate_tool_output(
        self,
        tool_name: str,
        output: Any,
        decision: ExecutionDecision
    ) -> tuple[Any, dict[str, Any]]:
        """Validate and sanitize tool output."""
        validation_info = {
            "tool_name": tool_name,
            "output_size": len(str(output)) if output else 0,
            "sanitized": False,
            "filtered": False,
            "reasons": []
        }
        
        # Check output size
        if validation_info["output_size"] > 100000:  # 100KB limit
            validation_info["filtered"] = True
            validation_info["reasons"].append("Output too large, truncating")
            output = str(output)[:100000]
            validation_info["sanitized"] = True
        
        # Check for sensitive data
        if self._contains_sensitive_info(output):
            validation_info["filtered"] = True
            validation_info["reasons"].append("Sensitive data detected, filtering")
            output = self._sanitize_output(output)
            validation_info["sanitized"] = True
        
        # Check for dangerous content
        if self._contains_dangerous_content(output):
            validation_info["filtered"] = True
            validation_info["reasons"].append("Dangerous content detected, blocking")
            output = None
            validation_info["sanitized"] = True
        
        return output, validation_info
    
    def _has_dangerous_parameters(self, parameters: dict[str, Any]) -> bool:
        """Check for dangerous parameters."""
        dangerous_keys = ["password", "token", "secret", "key", "auth"]
        for key in dangerous_keys:
            if key in str(parameters).lower():
                return True
        return False
    
    def _determine_execution_mode(self, tool_name: str, parameters: dict[str, Any]) -> str:
        """Determine execution mode based on tool and parameters."""
        # Read-only tools get full execution
        if "search" in tool_name or "get" in tool_name or "query" in tool_name:
            return "full"
        
        # Write operations get restricted mode
        if "write" in tool_name or "update" in tool_name or "delete" in tool_name:
            return "restricted"
        
        return "full"
    
    def _determine_timeout(self, tool_name: str, execution_mode: str) -> int:
        """Determine appropriate timeout based on tool and mode."""
        if execution_mode == "restricted":
            return min(self.default_timeout, 15)
        
        # LLM calls get longer timeout
        if "llm" in tool_name or "gemini" in tool_name.lower():
            return self.default_timeout
        
        # Database operations get moderate timeout
        if "neo4j" in tool_name or "qdrant" in tool_name:
            return 20
        
        return self.default_timeout
    
    def _has_prompt_injection(self, prompt: str) -> bool:
        """Check for prompt injection patterns."""
        injection_patterns = [
            r"ignore\s+previous\s+instructions",
            r"disregard\s+all\s+above",
            r"forget\s+everything",
            r"new\s+system\s+prompt",
            r"override\s+your\s+programming",
        ]
        
        for pattern in injection_patterns:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        
        return False
    
    def _execute_with_timeout(self, func: Callable, timeout: int, *args, **kwargs):
        """Execute function with timeout (simplified implementation)."""
        # In a real implementation, this would use threading or asyncio
        # For now, we'll just call the function directly
        return func(*args, **kwargs)
    
    def _contains_sensitive_info(self, output: Any) -> bool:
        """Check if output contains sensitive information."""
        sensitive_patterns = [
            r"password",
            r"api_key",
            r"secret",
            r"token",
            r"credit_card",
        ]
        
        output_str = str(output).lower()
        for pattern in sensitive_patterns:
            if re.search(pattern, output_str):
                return True
        
        return False
    
    def _sanitize_output(self, output: Any) -> str:
        """Sanitize output by removing sensitive information."""
        output_str = str(output)
        
        # Simple redaction - in production, use more sophisticated methods
        sensitive_patterns = [
            (r"password['\"]?\s*[:=]\s*['\"]?[^'\"]+['\"]?", "password=***REDACTED***"),
            (r"api_key['\"]?\s*[:=]\s*['\"]?[^'\"]+['\"]?", "api_key=***REDACTED***"),
            (r"secret['\"]?\s*[:=]\s*['\"]?[^'\"]+['\"]?", "secret=***REDACTED***"),
        ]
        
        for pattern, replacement in sensitive_patterns:
            output_str = re.sub(pattern, replacement, output_str, flags=re.IGNORECASE)
        
        return output_str
    
    def _contains_dangerous_content(self, output: Any) -> bool:
        """Check if output contains dangerous content."""
        dangerous_patterns = [
            r"<script",
            r"javascript:",
            r"eval\s*\(",
            r"exec\s*\(",
        ]
        
        output_str = str(output).lower()
        for pattern in dangerous_patterns:
            if re.search(pattern, output_str):
                return True
        
        return False