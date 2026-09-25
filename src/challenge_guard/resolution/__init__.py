"""Ciclo de resolucao: capacidade, orcamento e validacao.

Este pacote responde "o que o guard pode fazer com o que viu" — e a resposta
nunca e "resolver". As capacidades sao sobre observar e esperar; o orcamento
limita rounds e tempo; a validacao exige observacao nova em vez de aceitar que
"a acao terminou" signifique progresso.
"""

from .capabilities import ChallengeCapability, capability_for, capability_matrix
from .limits import BudgetViolation, ResolutionBudget, RuntimeLimits
from .validator import ValidationResult, validate_not_premature, validate_progress

__all__ = [
    "BudgetViolation",
    "ChallengeCapability",
    "ResolutionBudget",
    "RuntimeLimits",
    "ValidationResult",
    "capability_for",
    "capability_matrix",
    "validate_not_premature",
    "validate_progress",
]
