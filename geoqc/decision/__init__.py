"""Motor E6 diagnóstico de requisitos y decisiones humanas separadas."""

from geoqc.decision.actions import recommend_alias_action, recommend_stack_action
from geoqc.decision.adapters import record_from_common_qc
from geoqc.decision.aggregator import aggregate, annotate
from geoqc.decision.contracts import (
    DecisionInput,
    DecisionRecord,
    OperatorDecision,
    Requirement,
    Supersession,
)

__all__ = [
    "DecisionInput",
    "DecisionRecord",
    "OperatorDecision",
    "Requirement",
    "Supersession",
    "aggregate",
    "annotate",
    "recommend_alias_action",
    "recommend_stack_action",
    "record_from_common_qc",
]
