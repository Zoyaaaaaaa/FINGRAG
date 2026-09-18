"""Input Rails - validates and sanitizes user queries before processing.

Provides comprehensive input validation including:
- Length limits
- Character safety checks
- Injection prevention
- Query structure validation
- Malicious pattern detection
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class InputValidationResult:
    """Result of input validation."""
    is_valid: bool
    sanitized_query: str
    reason: str | None = None
    severity: str = "low"  # low, medium, high


class InputRails:
    """Comprehensive input validation and sanitization."""
    
    def __init__(self, max_length: int = 2000, min_length: int = 1):
        self.max_length = max_length
        self.min_length = min_length
        
        # Malicious patterns to detect
        self.injection_patterns = [
            r"<script[^>]*>.*?</script>",  # Script injection
            r"javascript:",  # JavaScript protocol
            r"on\w+\s*=",  # Event handlers
            r"data:text/html",  # Data URLs
            r"eval\s*\(",  # eval calls
            r"document\.",  # Document access
            r"window\.",  # Window access
            r"__import__",  # Python imports
            r"exec\s*\(",  # exec calls
            r"system\s*\(",  # system calls
        ]
        
        # SQL injection patterns
        self.sql_patterns = [
            r"DROP\s+TABLE",
            r"DELETE\s+FROM",
            r"TRUNCATE\s+TABLE",
            r"ALTER\s+TABLE",
            r"INSERT\s+INTO",
            r"UPDATE\s+\w+\s+SET",
            r"UNION\s+SELECT",
            r"OR\s+1\s*=\s*1",
            r";\s*DROP",
            r";\s*DELETE",
        ]
        
        # Unsafe character sequences
        self.unsafe_chars = [
            "\x00",  # Null byte
            "\x1a",  # Control character
        ]
    
    def validate_and_sanitize(self, query: str) -> InputValidationResult:
        """Main validation and sanitization method."""
        # Check basic length
        if len(query) < self.min_length:
            return InputValidationResult(
                is_valid=False,
                sanitized_query="",
                reason=f"Query too short (minimum {self.min_length} characters)",
                severity="low"
            )
        
        if len(query) > self.max_length:
            return InputValidationResult(
                is_valid=False,
                sanitized_query="",
                reason=f"Query too long (maximum {self.max_length} characters)",
                severity="medium"
            )
        
        # Check for injection patterns
        for pattern in self.injection_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return InputValidationResult(
                    is_valid=False,
                    sanitized_query="",
                    reason=f"Potentially malicious pattern detected: {pattern}",
                    severity="high"
                )
        
        # Check for SQL injection patterns
        for pattern in self.sql_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return InputValidationResult(
                    is_valid=False,
                    sanitized_query="",
                    reason=f"SQL injection pattern detected: {pattern}",
                    severity="high"
                )
        
        # Check for unsafe characters
        for char in self.unsafe_chars:
            if char in query:
                return InputValidationResult(
                    is_valid=False,
                    sanitized_query="",
                    reason=f"Unsafe character detected in query",
                    severity="high"
                )
        
        # Sanitize the query
        sanitized = self._sanitize(query)
        
        return InputValidationResult(
            is_valid=True,
            sanitized_query=sanitized,
            reason=None
        )
    
    def _sanitize(self, query: str) -> str:
        """Sanitize the query by removing or replacing problematic elements."""
        # Remove excessive whitespace
        sanitized = re.sub(r'\s+', ' ', query)
        
        # Trim leading/trailing whitespace
        sanitized = sanitized.strip()
        
        # Remove control characters except newlines and tabs
        sanitized = ''.join(char for char in sanitized if char >= ' ' or char in '\n\t')
        
        return sanitized
    
    def check_query_structure(self, query: str) -> dict[str, Any]:
        """Analyze query structure for additional insights."""
        analysis = {
            "word_count": len(query.split()),
            "has_question_mark": "?" in query,
            "question_words": [],
            "has_financial_terms": False,
            "has_company_names": False,
            "potential_complexity": "simple"
        }
        
        # Check for question words
        question_words = ["what", "how", "why", "when", "where", "which", "who", "can", "could", "would", "should"]
        found_questions = [word for word in question_words if word in query.lower()]
        analysis["question_words"] = found_questions
        
        # Check for financial terms
        financial_terms = ["revenue", "profit", "loss", "investment", "deal", "partnership", "stake", "share"]
        analysis["has_financial_terms"] = any(term in query.lower() for term in financial_terms)
        
        # Check for potential company names (capitalized words)
        words = query.split()
        capitalized = [word for word in words if word[0].isupper() and len(word) > 2]
        analysis["has_company_names"] = len(capitalized) >= 2
        
        # Estimate complexity
        if analysis["word_count"] > 20 or len(found_questions) > 2:
            analysis["potential_complexity"] = "complex"
        elif analysis["word_count"] > 10:
            analysis["potential_complexity"] = "moderate"
        
        return analysis