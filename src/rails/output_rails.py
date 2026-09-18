"""Output Rails - validates and sanitizes final responses before sending to users.

Provides guardrails for:
- Response content validation
- Sensitive information filtering
- Harmful content detection
- Output format verification
- Response quality checks
- Source attribution validation
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class OutputValidationResult:
    """Result of output validation."""
    is_valid: bool
    sanitized_response: str
    reason: str | None = None
    severity: str = "low"  # low, medium, high
    filtered_content: list[str] | None = None
    quality_score: float = 1.0


class OutputRails:
    """Validates and sanitizes final responses before sending to users."""
    
    def __init__(self, max_response_length: int = 5000):
        self.max_response_length = max_response_length
        
        # Harmful content patterns
        self.harmful_patterns = [
            r"hate\s+speech",
            r"violence\s+incitement",
            r"illegal\s+activity",
            r"self\s+harm",
            r"dangerous\s+instructions",
            r"how\s+to\s+(kill|hurt|harm)",
            r"bomb\s+making",
            r"weapon\s+creation",
            r"create\s+dangerous",
            r"make\s+weapons",
        ]
        
        # Sensitive information patterns
        self.sensitive_patterns = [
            r"\d{3}-\d{2}-\d{4}",  # SSN pattern
            r"\d{16}",  # Credit card pattern
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
            r"\+?\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",  # Phone
        ]
        
        # Injection/markdown patterns
        self.injection_patterns = [
            r"<script[^>]*>.*?</script>",
            r"javascript:",
            r"data:text/html",
            r"on\w+\s*=",
        ]
    
    def validate_and_sanitize_response(
        self,
        response: str,
        context: dict[str, Any]
    ) -> OutputValidationResult:
        """Main validation and sanitization method for responses."""
        
        # Check response length
        if len(response) > self.max_response_length:
            return OutputValidationResult(
                is_valid=False,
                sanitized_response="",
                reason=f"Response too long ({len(response)} characters)",
                severity="medium",
                quality_score=0.0
            )
        
        # Check for harmful content
        harmful_found = self._check_harmful_content(response)
        if harmful_found:
            return OutputValidationResult(
                is_valid=False,
                sanitized_response="",
                reason=f"Harmful content detected: {harmful_found}",
                severity="high",
                quality_score=0.0
            )
        
        # Check for injection patterns
        injection_found = self._check_injection_patterns(response)
        if injection_found:
            return OutputValidationResult(
                is_valid=False,
                sanitized_response="",
                reason=f"Injection pattern detected: {injection_found}",
                severity="high",
                quality_score=0.0
            )
        
        # Sanitize the response
        sanitized, filtered = self._sanitize_response(response)
        
        # Calculate quality score
        quality_score = self._calculate_quality_score(sanitized, context)
        
        return OutputValidationResult(
            is_valid=True,
            sanitized_response=sanitized,
            reason=None,
            severity="low",
            filtered_content=filtered,
            quality_score=quality_score
        )
    
    def validate_source_attribution(
        self,
        response: str,
        sources: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Validate that response properly attributes sources."""
        validation = {
            "has_sources": len(sources) > 0,
            "response_mentions_sources": False,
            "source_consistency": True,
            "issues": []
        }
        
        # Check if response mentions sources
        source_indicators = ["source", "according to", "based on", "from", "reference"]
        validation["response_mentions_sources"] = any(
            indicator in response.lower() for indicator in source_indicators
        )
        
        # Check for consistency between response and sources
        if sources:
            source_entities = self._extract_entities_from_sources(sources)
            response_entities = self._extract_entities_from_text(response)
            
            # If we have specific entities in sources, check if they appear in response
            if source_entities and not response_entities:
                validation["source_consistency"] = False
                validation["issues"].append("Response doesn't reference source entities")
        
        return validation
    
    def validate_answer_quality(
        self,
        response: str,
        original_query: str,
        context: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate the quality of the answer."""
        quality_check = {
            "is_relevant": True,
            "is_complete": True,
            "is_accurate": True,
            "confidence": 0.8,
            "issues": []
        }
        
        # Check relevance
        if not self._is_relevant(response, original_query):
            quality_check["is_relevant"] = False
            quality_check["confidence"] -= 0.3
            quality_check["issues"].append("Response may not be relevant to query")
        
        # Check completeness
        if len(response) < 50:
            quality_check["is_complete"] = False
            quality_check["confidence"] -= 0.2
            quality_check["issues"].append("Response seems too short")
        
        # Check for hedging (which might indicate uncertainty)
        hedging_phrases = ["i think", "probably", "maybe", "possibly", "it seems"]
        if any(phrase in response.lower() for phrase in hedging_phrases):
            quality_check["confidence"] -= 0.1
            quality_check["issues"].append("Response contains hedging language")
        
        # Check for refusal
        refusal_phrases = ["i cannot", "i'm unable", "i don't have information"]
        if any(phrase in response.lower() for phrase in refusal_phrases):
            quality_check["is_complete"] = False
            quality_check["confidence"] -= 0.4
            quality_check["issues"].append("Response appears to be a refusal")
        
        # Ensure confidence doesn't go below 0
        quality_check["confidence"] = max(0.0, quality_check["confidence"])
        
        return quality_check
    
    def _check_harmful_content(self, text: str) -> str | None:
        """Check for harmful content patterns."""
        for pattern in self.harmful_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return pattern
        return None
    
    def _check_injection_patterns(self, text: str) -> str | None:
        """Check for injection patterns."""
        for pattern in self.injection_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return pattern
        return None
    
    def _sanitize_response(self, response: str) -> tuple[str, list[str]]:
        """Sanitize response by filtering sensitive information."""
        filtered_content = []
        sanitized = response
        
        # Filter sensitive information
        for pattern in self.sensitive_patterns:
            matches = re.findall(pattern, sanitized, re.IGNORECASE)
            if matches:
                filtered_content.extend(matches)
                # Redact sensitive info
                sanitized = re.sub(pattern, "***REDACTED***", sanitized, flags=re.IGNORECASE)
        
        # Clean up excessive whitespace
        sanitized = re.sub(r'\s+', ' ', sanitized)
        
        return sanitized, filtered_content
    
    def _calculate_quality_score(self, response: str, context: dict[str, Any]) -> float:
        """Calculate a quality score for the response."""
        score = 1.0
        
        # Length check
        if len(response) < 20:
            score -= 0.3
        elif len(response) > 2000:
            score -= 0.1
        
        # Structure check
        if not any(sentence_terminator in response for sentence_terminator in ['.', '!', '?']):
            score -= 0.2
        
        # Context check
        if context.get("blocked"):
            score -= 0.5
        
        # Source check
        if context.get("sources") and len(context["sources"]) == 0:
            score -= 0.1
        
        return max(0.0, score)
    
    def _extract_entities_from_sources(self, sources: list[dict[str, Any]]) -> list[str]:
        """Extract entity names from sources."""
        entities = []
        for source in sources:
            if isinstance(source, dict):
                # Look for company names, partner names, etc.
                for key in ["company_name", "chinese_partner", "partner", "name"]:
                    if key in source and source[key]:
                        entities.append(str(source[key]))
        return entities
    
    def _extract_entities_from_text(self, text: str) -> list[str]:
        """Extract potential entity names from text (capitalized words)."""
        words = text.split()
        entities = []
        for word in words:
            if word[0].isupper() and len(word) > 2 and word.isalpha():
                entities.append(word)
        return entities
    
    def _is_relevant(self, response: str, query: str) -> bool:
        """Check if response is relevant to the query."""
        # Simple check: response should contain some query terms
        query_words = set(query.lower().split())
        response_words = set(response.lower().split())
        
        # Check for at least some overlap
        overlap = query_words.intersection(response_words)
        return len(overlap) >= min(2, len(query_words))