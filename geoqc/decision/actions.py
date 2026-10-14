"""Acciones diagnósticas condicionadas; no introducen umbrales de campo."""

from geoqc.decision.contracts import Action
from geoqc.qc.timing import required_stacks


def recommend_stack_action(
    *,
    actual: int,
    snr_actual_db: float,
    snr_target_db: float,
    independent_noise: bool,
    comparable: bool,
    stack_kind: str,
) -> Action:
    estimate = required_stacks(
        actual=actual,
        snr_actual_db=snr_actual_db,
        snr_target_db=snr_target_db,
        independent_noise=independent_noise,
        comparable=comparable,
        stack_kind=stack_kind,
    )
    return Action.model_validate(
        dict(
            id="REPEAT_STACK",
            description="Repetir la fuente y reevaluar SNR observado",
            condition="SNR neto observado menor al objetivo del protocolo",
            assumptions=(
                "Ruido independiente entre repeticiones",
                "Adquisición comparable y stack promedio",
                "Predicción condicionada; verificar mejora observada",
            ),
            validity=estimate.state,
            reason=estimate.reason,
            value=estimate.value,
            unit=estimate.unit,
        )
    )


def recommend_alias_action() -> Action:
    return Action(
        id="REVIEW_SPATIAL_SAMPLING",
        description="Reducir dx, limitar banda o rediseñar el arreglo",
        condition="Ambigüedad espacial detectada en el kernel de receptores activos",
        assumptions=(
            "Evaluar posiciones, máscaras, direcciones y pesos reales",
            "Verificar nuevamente banda y objetivo tras cambiar el diseño",
        ),
        validity="VALID",
        reason="Acción cualitativa; sin garantía de suficiencia ni espaciado universal",
        value=None,
        unit="1",
    )
