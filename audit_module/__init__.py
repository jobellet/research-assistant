"""Audit Module for My AI Research Assistant.

Provides automated prose quality auditing (AI connectives, empty negatives, voice, rhythm, spellings)
and numerical/timeline auditing (quantity drift, grant horizon overruns, sum checks, backwards ranges).
"""

from .prose_auditor import audit_prose
from .number_auditor import audit_numbers

__all__ = ["audit_prose", "audit_numbers"]
