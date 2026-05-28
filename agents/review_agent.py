"""Security and code quality review agent.

Performs security scans, whitelist checks, code quality analysis,
and returns approved/rejected decisions with reasoning.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from core.config import get_config
from core.events import Event, EventType, get_event_bus

logger = logging.getLogger(__name__)


class ReviewDecision(Enum):
    """Review decision outcomes."""

    APPROVED = "approved"
    REJECTED = "rejected"
    CONDITIONAL = "conditional"
    NEEDS_REVIEW = "needs_review"


@dataclass
class SecurityViolation:
    """A detected security violation."""

    rule: str
    severity: str
    description: str
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "rule": self.rule,
            "severity": self.severity,
            "description": self.description,
            "line_number": self.line_number,
            "code_snippet": self.code_snippet,
        }


@dataclass
class ReviewResult:
    """Result of a code review."""

    decision: ReviewDecision = ReviewDecision.NEEDS_REVIEW
    violations: List[SecurityViolation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    score: float = 0.0
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "decision": self.decision.value,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": self.warnings,
            "score": self.score,
            "reasoning": self.reasoning,
            "metadata": self.metadata,
        }


class ReviewAgent:
    """Security and quality review agent.

    Performs comprehensive security scans, whitelist validation,
    code quality checks, and provides review decisions.

    Attributes:
        config: Application configuration.
        event_bus: Event bus for agent communication.
        _whitelist_patterns: Compiled whitelist patterns.
    """

    # Security rules for detection
    DANGEROUS_PATTERNS = {
        "shell_injection": [
            (r";\s*(rm|del|format)", "Shell command injection"),
            (r"&&\s*(rm|del|format)", "Shell command injection"),
            (r"\|\|\s*(rm|del|format)", "Shell command injection"),
            (r"`.*`", "Command substitution injection"),
            (r"\$\(.*\)", "Command substitution injection"),
        ],
        "path_traversal": [
            (r"\.\./", "Path traversal attempt"),
            (r"\.\.\\", "Path traversal attempt"),
            (r"[A-Za-z]:\\{2}", "Absolute path abuse"),
        ],
        "network_access": [
            (r"socket\.(connect|bind)", "Direct socket access"),
            (r"requests\.(get|post|put|delete)", "Unrestricted HTTP requests"),
            (r"http\.client", "Raw HTTP client"),
            (r"urlopen", "URL opening"),
            (r"fetch\s*\(", "Fetch API (browser)"),
        ],
        "file_system": [
            (r"open\s*\([^,]+,\s*['\"]w['\"]", "File write operation"),
            (r"chmod\s*\(", "Permission modification"),
            (r"chown\s*\(", "Ownership modification"),
            (r"mknod\s*\(", "Device file creation"),
        ],
        "code_execution": [
            (r"eval\s*\(", "Dynamic code evaluation"),
            (r"exec\s*\(", "Dynamic code execution"),
            (r"compile\s*\(", "Dynamic code compilation"),
            (r"__import__\s*\(", "Dynamic module import"),
        ],
        "data_exfiltration": [
            (r"base64\.encode", "Base64 encoding"),
            (r"subprocess.*>", "Output redirection"),
            (r"os\.environ", "Environment variable access"),
        ],
    }

    # Language-specific patterns to flag
    APPROVED_LANGUAGES = {"python", "javascript", "typescript", "go", "ruby", "java", "c", "cpp", "rust"}
    APPROVED_MODULES = {
        "python": {
            "os": {"path": True, "system": False},
            "sys": {"path": True, "executable": True},
            "json": {"loads": True, "dumps": True},
            "re": {"compile": True, "search": True},
            "math": {"*": True},
            "collections": {"*": True},
        },
        "javascript": {
            "fs": {"readFile": True, "readFileSync": True},
            "path": {"join": True, "resolve": True},
            "crypto": {"randomBytes": True},
        },
    }

    def __init__(self) -> None:
        """Initialize ReviewAgent."""
        self.config = get_config()
        self.event_bus = get_event_bus()
        self._whitelist_patterns: List[re.Pattern] = []
        self._compile_whitelist()
        logger.info("ReviewAgent initialized")

    def _compile_whitelist(self) -> None:
        """Compile whitelist patterns from configuration."""
        # Add default safe patterns
        safe_patterns = [
            r"^[a-zA-Z0-9_\s]+$",  # Alphanumeric and spaces only
            r"^(?!.*[<>'\";&|`$]).*$",  # Block dangerous characters
        ]

        for pattern in safe_patterns:
            try:
                self._whitelist_patterns.append(re.compile(pattern))
            except re.error as e:
                logger.warning(f"Invalid whitelist pattern: {e}")

    async def review(
        self,
        code: str,
        language: str,
        task_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ReviewResult:
        """Perform a comprehensive code review.

        Args:
            code: Code to review.
            language: Programming language.
            task_id: Optional task ID for tracking.
            context: Optional review context.

        Returns:
            ReviewResult: Review decision with violations and reasoning.
        """
        logger.info(f"Starting review for task {task_id or 'unknown'}")
        start_time = datetime.utcnow()

        result = ReviewResult()

        # Perform security scan
        result.violations = await self._security_scan(code, language)

        # Perform whitelist check
        whitelist_violations = await self._whitelist_check(code, language)
        result.violations.extend(whitelist_violations)

        # Check language approval
        if language.lower() not in self.APPROVED_LANGUAGES:
            result.violations.append(
                SecurityViolation(
                    rule="language_approval",
                    severity="high",
                    description=f"Language '{language}' is not in approved list",
                )
            )

        # Check for code quality issues
        result.warnings = await self._check_quality(code, language)

        # Calculate score
        result.score = self._calculate_score(result.violations)

        # Determine decision
        result.decision = self._determine_decision(result.violations, result.score)

        # Generate reasoning
        result.reasoning = self._generate_reasoning(result)

        result.metadata = {
            "task_id": task_id,
            "language": language,
            "code_length": len(code),
            "review_duration_ms": int(
                (datetime.utcnow() - start_time).total_seconds() * 1000
            ),
            "context": context,
        }

        # Publish review event
        event = Event(
            event_type=EventType.TASK_REVIEWED,
            agent="review_agent",
            task_id=task_id,
            data={
                "decision": result.decision.value,
                "violation_count": len(result.violations),
                "score": result.score,
            },
        )
        await self.event_bus.publish(event)

        logger.info(
            f"Review completed: {result.decision.value} "
            f"(score: {result.score}, violations: {len(result.violations)})"
        )
        return result

    async def _security_scan(
        self,
        code: str,
        language: str,
    ) -> List[SecurityViolation]:
        """Scan code for security violations.

        Args:
            code: Code to scan.
            language: Programming language.

        Returns:
            List[SecurityViolation]: Detected violations.
        """
        violations = []
        lines = code.split("\n")

        for category, patterns in self.DANGEROUS_PATTERNS.items():
            for pattern, description in patterns:
                try:
                    regex = re.compile(pattern, re.IGNORECASE)
                    for line_num, line in enumerate(lines, start=1):
                        matches = regex.finditer(line)
                        for match in matches:
                            # Check if this is a false positive
                            if not self._is_false_positive(category, match.group(), language):
                                violations.append(
                                    SecurityViolation(
                                        rule=f"{category}.{description.lower().replace(' ', '_')}",
                                        severity=self._severity_for_category(category),
                                        description=description,
                                        line_number=line_num,
                                        code_snippet=line.strip(),
                                    )
                                )
                except re.error as e:
                    logger.warning(f"Regex error in security scan: {e}")

        return violations

    async def _whitelist_check(
        self,
        code: str,
        language: str,
    ) -> List[SecurityViolation]:
        """Check code against whitelist patterns.

        Args:
            code: Code to check.
            language: Programming language.

        Returns:
            List[SecurityViolation]: Whitelist violations.
        """
        violations = []
        lines = code.split("\n")

        for line_num, line in enumerate(lines, start=1):
            # Skip empty lines and comments
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue

            # Check against whitelist patterns
            for pattern in self._whitelist_patterns:
                if not pattern.match(line):
                    violations.append(
                        SecurityViolation(
                            rule="whitelist_violation",
                            severity="medium",
                            description="Code does not match whitelist pattern",
                            line_number=line_num,
                            code_snippet=line.strip()[:50],
                        )
                    )

        return violations

    async def _check_quality(
        self,
        code: str,
        language: str,
    ) -> List[str]:
        """Check code quality.

        Args:
            code: Code to check.
            language: Programming language.

        Returns:
            List[str]: Quality warnings.
        """
        warnings = []

        lines = code.split("\n")

        # Check for very long lines
        for i, line in enumerate(lines, start=1):
            if len(line) > 120:
                warnings.append(f"Line {i} exceeds 120 characters")

        # Check for TODO/FIXME
        if "TODO" in code or "FIXME" in code:
            warnings.append("Code contains TODO or FIXME comments")

        # Check for hardcoded credentials
        if re.search(r"(password|secret|api_key|token)\s*=\s*['\"][^'\"]{8,}", code, re.I):
            warnings.append("Potential hardcoded credentials detected")

        # Check for empty catch blocks
        if re.search(r"except.*:\s*\n\s*\n\s*pass", code, re.M):
            warnings.append("Empty exception handlers detected")

        # Check function/variable naming
        if language.lower() == "python":
            if re.search(r"[A-Z][A-Z_]+", code):  # SCREAMING_CASE variables
                warnings.append("Screaming case variable names detected")

        return warnings

    def _is_false_positive(
        self,
        category: str,
        match: str,
        language: str,
    ) -> bool:
        """Check if a match is a false positive.

        Args:
            category: Rule category.
            match: Matched text.
            language: Programming language.

        Returns:
            bool: True if false positive.
        """
        # Common false positives
        false_positive_strings = {
            "rm -rf /tmp",  # Cleanup of temp directory
            "rmdir",  # Directory removal
            "subprocess.run",  # Controlled subprocess
            "requests.get(",  # HTTP GET
        }

        return match in false_positive_strings

    def _severity_for_category(self, category: str) -> str:
        """Get severity level for a category.

        Args:
            category: Rule category.

        Returns:
            str: Severity level.
        """
        severity_map = {
            "shell_injection": "critical",
            "code_execution": "critical",
            "data_exfiltration": "high",
            "network_access": "high",
            "file_system": "medium",
            "path_traversal": "medium",
        }
        return severity_map.get(category, "medium")

    def _calculate_score(self, violations: List[SecurityViolation]) -> float:
        """Calculate code quality score.

        Args:
            violations: List of violations.

        Returns:
            float: Score from 0.0 to 1.0 (1.0 = perfect).
        """
        if not violations:
            return 1.0

        severity_weights = {
            "critical": 0.3,
            "high": 0.2,
            "medium": 0.1,
            "low": 0.05,
        }

        total_penalty = sum(
            severity_weights.get(v.severity, 0.1) for v in violations
        )

        return max(0.0, 1.0 - total_penalty)

    def _determine_decision(
        self,
        violations: List[SecurityViolation],
        score: float,
    ) -> ReviewDecision:
        """Determine review decision based on violations and score.

        Args:
            violations: Detected violations.
            score: Quality score.

        Returns:
            ReviewDecision: Review decision.
        """
        if not violations:
            return ReviewDecision.APPROVED

        # Check for critical violations
        critical_count = sum(1 for v in violations if v.severity == "critical")
        if critical_count > 0:
            return ReviewDecision.REJECTED

        # Check for high severity violations
        high_count = sum(1 for v in violations if v.severity == "high")
        if high_count > 2:
            return ReviewDecision.REJECTED

        if high_count > 0 or score < 0.7:
            return ReviewDecision.CONDITIONAL

        if score < 0.9:
            return ReviewDecision.NEEDS_REVIEW

        return ReviewDecision.APPROVED

    def _generate_reasoning(self, result: ReviewResult) -> str:
        """Generate human-readable reasoning for the decision.

        Args:
            result: Review result.

        Returns:
            str: Reasoning text.
        """
        parts = []

        if not result.violations:
            parts.append("Code passed all security checks with no violations detected.")
        else:
            parts.append(f"Found {len(result.violations)} violation(s):")

            # Group by severity
            by_severity = {}
            for v in result.violations:
                if v.severity not in by_severity:
                    by_severity[v.severity] = []
                by_severity[v.severity].append(v)

            for severity in ["critical", "high", "medium", "low"]:
                if severity in by_severity:
                    violations = by_severity[severity]
                    parts.append(f"\n{severity.upper()}: {len(violations)} violation(s)")
                    for v in violations[:3]:  # Show first 3 per severity
                        parts.append(f"  - {v.description} (line {v.line_number})")

        if result.warnings:
            parts.append(f"\nWarnings: {len(result.warnings)} issue(s)")
            for warning in result.warnings[:3]:
                parts.append(f"  - {warning}")

        parts.append(f"\nQuality score: {result.score:.2f}/1.00")
        parts.append(f"Decision: {result.decision.value}")

        return "\n".join(parts)

    async def batch_review(
        self,
        code_items: List[Dict[str, str]],
    ) -> List[ReviewResult]:
        """Perform batch review of multiple code items.

        Args:
            code_items: List of {"code": str, "language": str, "task_id": str}.

        Returns:
            List[ReviewResult]: Results for each item.
        """
        tasks = []
        for item in code_items:
            task = self.review(
                code=item.get("code", ""),
                language=item.get("language", "python"),
                task_id=item.get("task_id"),
                context=item.get("context"),
            )
            tasks.append(task)

        return await asyncio.gather(*tasks, return_exceptions=True)

    def get_supported_languages(self) -> Set[str]:
        """Get set of supported languages for review.

        Returns:
            Set[str]: Set of supported language names.
        """
        return self.APPROVED_LANGUAGES.copy()


# Global review agent instance
_review_agent: Optional[ReviewAgent] = None


def get_review_agent() -> ReviewAgent:
    """Get the global review agent instance.

    Returns:
        ReviewAgent: The global review agent instance.
    """
    global _review_agent
    if _review_agent is None:
        _review_agent = ReviewAgent()
    return _review_agent