"""Retrieval Rails - controls and validates data retrieval operations.

Provides guardrails for:
- Retrieval scope control
- Data access limits
- Query complexity management
- Retrieval result validation
- PII detection and filtering
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class RetrievalDecision:
    """Result of retrieval rail validation."""
    allowed: bool
    scope: str  # "full", "limited", "none"
    max_results: int
    reason: str | None = None
    filters: dict[str, Any] | None = None


class RetrievalRails:
    """Controls and validates data retrieval operations."""
    
    def __init__(self, default_max_results: int = 10, max_complexity: int = 5):
        self.default_max_results = default_max_results
        self.max_complexity = max_complexity
        
        # Sensitive patterns that might indicate PII or sensitive data requests
        self.sensitive_patterns = [
            r"personal\s+information",
            r"phone\s+number",
            r"email\s+address",
            r"social\s+security",
            r"credit\s+card",
            r"bank\s+account",
            r"password",
            r"confidential",
            r"private\s+data",
        ]
        
        # Complex query indicators
        self.complexity_indicators = [
            r"and\s+",  # Boolean AND
            r"or\s+",   # Boolean OR
            r"not\s+",  # Boolean NOT
            r"between",  # Range queries
            r">",  # Greater than
            r"<",  # Less than
            r"=",  # Equals
        ]
    
    def validate_retrieval_request(
        self, 
        query: str, 
        intent: dict[str, Any],
        plan: str,
        requested_top_k: int | None = None
    ) -> RetrievalDecision:
        """Validate and control retrieval requests."""
        
        # Check for sensitive data requests
        for pattern in self.sensitive_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return RetrievalDecision(
                    allowed=False,
                    scope="none",
                    max_results=0,
                    reason=f"Sensitive data pattern detected: {pattern}",
                    filters={"sensitive": True}
                )
        
        # Analyze query complexity
        complexity = self._analyze_complexity(query)
        if complexity > self.max_complexity:
            return RetrievalDecision(
                allowed=True,
                scope="limited",
                max_results=min(5, self.default_max_results),
                reason=f"Query complexity too high ({complexity}), limiting results",
                filters={"complexity_limit": True}
            )
        
        # Determine appropriate scope based on intent
        scope = self._determine_scope(intent, plan)
        
        # Set appropriate max results
        max_results = self._determine_max_results(requested_top_k, scope, complexity)
        
        # Apply any necessary filters
        filters = self._build_filters(intent, scope)
        
        return RetrievalDecision(
            allowed=True,
            scope=scope,
            max_results=max_results,
            reason=None,
            filters=filters
        )
    
    def validate_retrieval_results(
        self, 
        results: list[dict[str, Any]],
        decision: RetrievalDecision
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Validate and filter retrieval results."""
        validation_info = {
            "total_results": len(results),
            "filtered_count": 0,
            "reasons": []
        }
        
        filtered_results = []
        
        for result in results:
            # Check if result respects scope limits
            if decision.scope == "limited" and len(filtered_results) >= decision.max_results:
                validation_info["filtered_count"] += 1
                validation_info["reasons"].append("Scope limit reached")
                continue
            
            # Check for sensitive data in results
            if self._contains_sensitive_data(result):
                validation_info["filtered_count"] += 1
                validation_info["reasons"].append("Sensitive data detected")
                continue
            
            # Check result quality
            if not self._validate_result_quality(result):
                validation_info["filtered_count"] += 1
                validation_info["reasons"].append("Low quality result")
                continue
            
            filtered_results.append(result)
        
        return filtered_results, validation_info
    
    def _analyze_complexity(self, query: str) -> int:
        """Analyze query complexity based on indicators."""
        complexity = 0
        for indicator in self.complexity_indicators:
            if re.search(indicator, query, re.IGNORECASE):
                complexity += 1
        
        # Add complexity for long queries
        if len(query.split()) > 15:
            complexity += 1
        
        return complexity
    
    def _determine_scope(self, intent: dict[str, Any], plan: str) -> str:
        """Determine retrieval scope based on intent and plan."""
        intent_type = intent.get("intent", "SEMANTIC")
        
        # Relational queries often need full scope
        if intent_type == "RELATIONAL":
            return "full"
        
        # Factual queries can be limited
        if intent_type == "FACTUAL":
            return "limited"
        
        # Semantic queries get moderate scope
        if plan == "GLOBAL":
            return "limited"
        
        if plan == "HYBRID":
            return "full"
        
        return "limited"
    
    def _determine_max_results(
        self, 
        requested: int | None, 
        scope: str, 
        complexity: int
    ) -> int:
        """Determine appropriate max results."""
        base = requested or self.default_max_results
        
        # Apply scope limits
        if scope == "limited":
            base = min(base, 5)
        elif scope == "full":
            base = min(base, 10)
        
        # Apply complexity reduction
        if complexity > 3:
            base = max(3, base - 2)
        
        return min(base, self.default_max_results)
    
    def _build_filters(self, intent: dict[str, Any], scope: str) -> dict[str, Any]:
        """Build retrieval filters based on intent and scope."""
        filters = {}
        
        # Add domain filter
        if intent.get("domain"):
            filters["domain"] = intent["domain"]
        
        # Add scope-specific filters
        if scope == "limited":
            filters["quality_threshold"] = 0.7
        
        return filters
    
    def _contains_sensitive_data(self, result: dict[str, Any]) -> bool:
        """Check if result contains sensitive data patterns."""
        result_text = str(result).lower()
        
        for pattern in self.sensitive_patterns:
            if re.search(pattern, result_text):
                return True
        
        return False
    
    def _validate_result_quality(self, result: dict[str, Any]) -> bool:
        """Validate result quality."""
        # Check if result has minimal required fields
        if not result:
            return False
        
        # Check for score in vector results
        if "score" in result:
            try:
                score = float(result["score"])
                if score < 0.1:  # Very low confidence
                    return False
            except (ValueError, TypeError):
                pass
        
        # Check for text content
        if "text" in result and not result["text"].strip():
            return False
        
        return True