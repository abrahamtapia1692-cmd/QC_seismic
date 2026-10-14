"""Reglas E6: datos de prueba binarios, sin calibración empírica de campo."""

import json
import subprocess
import sys
from itertools import product
from pathlib import Path

import pytest
from pydantic import ValidationError

from geoqc.core.models import Metric, QCReport
from geoqc.decision import (
    DecisionInput,
    DecisionRecord,
    OperatorDecision,
    Requirement,
    Supersession,
    aggregate,
    annotate,
    recommend_alias_action,
    recommend_stack_action,
    record_from_common_qc,
)

H = "a" * 64


def metric(quality="PASS", *, validity="VALID", applicability="APPLICABLE", **changes):
    return Metric.model_validate(
        dict(
            id="integrity",
            unit="1",
            support_refs=("line/roi",),
            value=1 if validity == "VALID" else None,
            applicability=applicability,
            validity=validity,
            reason="Control binario de prueba",
            mandatory=True,
            critical=False,
            quality_status=quality if validity == "VALID" and applicability == "APPLICABLE" else None,
        )
        | changes
    )


def record(id="shot", metrics=None, **changes):
    return DecisionRecord.model_validate(
        dict(
            id=id,
            metrics=(metric(),) if metrics is None else metrics,
            technique="TRS",
            component="Z",
            geometry_hash=H,
            config_hash=H,
            code_hash=H,
            data_hashes=(H,),
            support_refs=("line/roi",),
            dependency_ids=(),
        )
        | changes
    )


def requirement(id="integrity", **changes):
    return Requirement.model_validate(
        dict(
            id=id,
            record_id="shot",
            metric_id="integrity",
            unit="1",
            support_refs=("line/roi",),
            technique="TRS",
            component="Z",
            mandatory=True,
            critical=False,
            applicability="APPLICABLE",
            applicability_reason="Control requerido por protocolo de prueba",
            calibration_required=False,
        )
        | changes
    )


def bundle(records=None, requirements=None, **changes):
    return DecisionInput.model_validate(
        dict(
            profile_ref="binary-diagnostic-test",
            scope_ref="line/roi",
            scope_status="IN_SCOPE",
            requirements=(requirement(),) if requirements is None else requirements,
            records=(record(),) if records is None else records,
            selected_record_ids=("shot",),
        )
        | changes
    )


@pytest.mark.vid("V-E6-1")
@pytest.mark.parametrize("quality", ["PASS", "WARN", "FAIL", None])
@pytest.mark.parametrize("critical", [False, True])
def test_quality_table(quality, critical):
    result = aggregate(
        bundle(records=(record(metrics=(metric(quality),)),), requirements=(requirement(critical=critical),))
    )
    assert result.quality_status == quality
    assert result.evidence_status == ("INCOMPLETE" if quality is None else "COMPLETE")
    assert result.verdict == ("RED" if quality == "FAIL" and critical else "YELLOW")
    assert result.eligible_for_acceptance is False
    assert result.satisfied_requirement_ids == (("integrity",) if quality == "PASS" else ())


@pytest.mark.vid("V-E6-1")
@pytest.mark.parametrize("validity", ["MISSING", "INVALID", "MODEL_INAPPLICABLE", "COMPUTATION_ERROR", "UNCALIBRATED"])
def test_unknown_validity_is_incomplete(validity):
    result = aggregate(bundle(records=(record(metrics=(metric(validity=validity),)),)))
    assert result.evidence_status == "INCOMPLETE"
    assert result.quality_status is None
    assert result.missing_requirement_ids == ("integrity",)


@pytest.mark.vid("V-E6-1")
def test_profile_na_and_unknown_cannot_be_supplied_by_metric():
    result = aggregate(
        bundle(records=(), selected_record_ids=(), requirements=(requirement(applicability="NOT_APPLICABLE"),))
    )
    assert result.evidence_status == "COMPLETE"
    assert result.not_applicable_requirement_ids == ("integrity",)
    for state in ("NOT_APPLICABLE", "UNKNOWN"):
        result = aggregate(bundle(records=(record(metrics=(metric(applicability=state),)),)))
        assert result.evidence_status == "INCOMPLETE"
    result = aggregate(bundle(requirements=(requirement(applicability="UNKNOWN"),)))
    assert result.evidence_status == "INCOMPLETE"
    with pytest.raises(ValidationError):
        requirement(applicability="NOT_APPLICABLE", applicability_reason=" ")


@pytest.mark.vid("V-E6-1")
@pytest.mark.parametrize(
    "changes", [dict(unit="m"), dict(support_refs=("other",)), dict(technique="MASW"), dict(component="X")]
)
def test_requirement_context_must_match(changes):
    assert aggregate(bundle(requirements=(requirement(**changes),))).evidence_status == "INCOMPLETE"


@pytest.mark.vid("V-E6-1")
def test_calibration_reference_is_not_trust_and_out_of_scope_is_explicit():
    result = aggregate(
        bundle(
            records=(record(metrics=(metric(calibration_ref="claims-validated"),)),),
            requirements=(requirement(calibration_required=True),),
        )
    )
    assert result.evidence_status == "INCOMPLETE"
    assert "UNCALIBRATED" in result.requirement_results[0].reasons
    out = aggregate(bundle(scope_status="OUT_OF_SCOPE"))
    assert out.evidence_status == out.verdict == "OUT_OF_SCOPE"


@pytest.mark.vid("V-E6-2")
def test_cartesian_quality_and_optional_non_dilution():
    rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    for first, second in product(rank, repeat=2):
        requirements = (requirement(), requirement("second", metric_id="second"))
        records = (record(metrics=(metric(first), metric(second, id="second"))),)
        result = aggregate(bundle(records=records, requirements=requirements))
        assert rank[result.quality_status] == max(rank[first], rank[second])
        assert result.eligible_for_acceptance is False
    optional = tuple(metric(id=f"optional-{i}", mandatory=False) for i in range(100))
    result = aggregate(bundle(records=(record(metrics=optional),)))
    assert result.quality_status == "PASS"
    assert result.evidence_status == "INCOMPLETE"
    assert result.missing_requirement_ids == ("integrity",)
    # El perfil mantiene la obligación aunque la métrica intente hacerla opcional.
    result = aggregate(bundle(records=(record(metrics=(metric("FAIL", mandatory=False),)),)))
    assert result.blocked_requirement_ids == ("integrity",)


@pytest.mark.vid("V-E6-3")
def test_actions_have_units_conditions_and_no_universal_guarantees():
    result = recommend_stack_action(
        actual=4, snr_actual_db=6, snr_target_db=12, independent_noise=True, comparable=True, stack_kind="MEAN"
    )
    assert result.value == 16 and result.unit == "count" and result.validity == "VALID"
    assert result.assumptions and result.condition
    for independent, comparable, kind in [(False, True, "MEAN"), (True, False, "MEAN"), (True, True, "SUM")]:
        unknown = recommend_stack_action(
            actual=4,
            snr_actual_db=6,
            snr_target_db=12,
            independent_noise=independent,
            comparable=comparable,
            stack_kind=kind,
        )
        assert unknown.value is None and unknown.validity == "MODEL_INAPPLICABLE"
    alias = recommend_alias_action()
    assert alias.id == "REVIEW_SPATIAL_SAMPLING"
    assert "dx" in alias.description and "frecuencia" not in alias.description.lower()


@pytest.mark.vid("V-E6-4")
def test_critical_used_input_propagates_through_dependencies():
    original = record("bad", metrics=(metric("FAIL", critical=True, mandatory=False),))
    derived = record("shot", dependency_ids=("bad",))
    result = aggregate(bundle(records=(original, derived)))
    assert result.verdict == "RED" and result.quality_status == "FAIL"
    assert result.used_record_ids == ("bad", "shot")
    assert result.downstream_blocked_record_ids == ("shot",)
    assert "CRITICAL_FAIL:bad:integrity" in result.blockers


@pytest.mark.vid("V-E6-4")
@pytest.mark.parametrize(
    "records",
    [
        (record(dependency_ids=("absent",)),),
        (record(dependency_ids=("other",)), record("other", dependency_ids=("shot",))),
    ],
)
def test_invalid_dependency_graph_is_rejected(records):
    with pytest.raises(ValueError):
        aggregate(bundle(records=records))


@pytest.mark.vid("V-E6-5")
def test_operator_annotation_preserves_warning_digest_and_export():
    result = aggregate(bundle(records=(record(metrics=(metric("WARN"),)),)))
    event = OperatorDecision(
        decision="ACCEPTED",
        responsible="operador",
        scope_ref="line/roi",
        caveats=("Requiere repetición",),
        reason="Anotación de campo",
        scientific_digest=result.scientific_digest,
        timestamp="2026-10-13T12:00:00-06:00",
    )
    annotated = annotate(result, event)
    assert annotated.assessment.quality_status == "WARN"
    assert annotated.assessment.scientific_digest == result.scientific_digest
    assert annotated.assessment.eligible_for_acceptance is False
    assert '"WARN"' in annotated.model_dump_json()
    for changes in (dict(responsible=""), dict(scope_ref=""), dict(caveats=())):
        with pytest.raises(ValidationError):
            OperatorDecision.model_validate(event.model_dump() | changes)
    for changes in (dict(scientific_digest="b" * 64), dict(scope_ref="other")):
        with pytest.raises(ValueError):
            annotate(result, OperatorDecision.model_validate(event.model_dump() | changes))


def replacement(**changes):
    return Supersession.model_validate(
        dict(
            original_id="shot",
            replacement_id="repeat",
            resolved_metric_ids=("integrity",),
            responsible="operator",
            reason="Receptor reacoplado; repetición comparable",
        )
        | changes
    )


@pytest.mark.vid("V-E6-6")
def test_supersession_preserves_history_and_requires_explicit_mapping():
    records = (record(metrics=(metric("FAIL", critical=True),)), record("repeat"))
    without = aggregate(bundle(records=records, selected_record_ids=("repeat",)))
    assert without.missing_requirement_ids == ("integrity",)
    result = aggregate(bundle(records=records, selected_record_ids=("repeat",), supersessions=(replacement(),)))
    assert result.quality_status == "PASS" and result.evidence_status == "COMPLETE"
    assert result.used_record_ids == ("repeat",)
    assert result.input.records[0].metrics[0].quality_status == "FAIL"
    assert result.requirement_results[0].effective_record_id == "repeat"
    # Un producto no recalculado sigue usando el original, incluso con repetición válida.
    derived = record("derived", dependency_ids=("shot",))
    result = aggregate(
        bundle(records=(*records, derived), selected_record_ids=("repeat", "derived"), supersessions=(replacement(),))
    )
    assert result.verdict == "RED" and "derived" in result.downstream_blocked_record_ids


@pytest.mark.vid("V-E6-6")
@pytest.mark.parametrize(
    "changes",
    [
        dict(geometry_hash="b" * 64),
        dict(config_hash="b" * 64),
        dict(component="X"),
        dict(support_refs=("other",)),
        dict(metrics=(metric("WARN"),)),
        dict(metrics=()),
    ],
)
def test_incompatible_or_unresolved_supersession_rejected(changes):
    records = (record(metrics=(metric("FAIL"),)), record("repeat", **changes))
    with pytest.raises(ValueError):
        aggregate(bundle(records=records, selected_record_ids=("repeat",), supersessions=(replacement(),)))


@pytest.mark.vid("V-E6-4")
def test_upstream_missing_and_legacy_masw_never_complete():
    for changes in (
        dict(upstream_missing_requirement_ids=("site_resolution",)),
        dict(technique="MASW"),
        dict(technique="MASW", source_schema_version="1.4-r1", document_revision="MASW-R1", supplement_hash="b" * 64),
    ):
        result = aggregate(bundle(records=(record(**changes),)))
        assert result.evidence_status == "INCOMPLETE"
        assert result.eligible_for_acceptance is False


@pytest.mark.vid("V-E6-4")
def test_profile_critical_flag_stays_with_original_used_by_derivative():
    records = (record(metrics=(metric("FAIL"),)), record("repeat"), record("derived", dependency_ids=("shot",)))
    result = aggregate(
        bundle(
            records=records,
            requirements=(requirement(critical=True),),
            selected_record_ids=("repeat", "derived"),
            supersessions=(replacement(),),
        )
    )
    assert result.verdict == "RED"


@pytest.mark.vid("V-E6-6")
def test_supersession_cycles_and_unresolved_other_failure_rejected():
    with pytest.raises(ValueError, match="cíclica"):
        aggregate(
            bundle(
                records=(record(), record("repeat")),
                supersessions=(replacement(), replacement(original_id="repeat", replacement_id="shot")),
            )
        )
    records = (record(metrics=(metric("FAIL"), metric("FAIL", id="other"))), record("repeat"))
    with pytest.raises(ValueError, match="todos los bloqueos"):
        aggregate(bundle(records=records, supersessions=(replacement(),), selected_record_ids=("repeat",)))


@pytest.mark.vid("V-E6-1")
@pytest.mark.parametrize(
    "changes",
    [
        dict(requirements=()),
        dict(selected_record_ids=("shot", "shot")),
        dict(records=(record(), record())),
        dict(eligible_for_acceptance=True),
    ],
)
def test_invalid_or_injected_input_is_rejected(changes):
    with pytest.raises(ValidationError):
        bundle(**changes)


@pytest.mark.vid("V-E6-5")
def test_annotation_recomputes_tampered_payload():
    result = aggregate(bundle(records=(record(metrics=(metric("WARN"),)),)))
    event = OperatorDecision(
        decision="REPEAT",
        responsible="op",
        scope_ref="line/roi",
        caveats=(),
        reason="Repetir",
        scientific_digest=result.scientific_digest,
        timestamp="2026-10-13T12:00:00-06:00",
    )
    tampered = result.model_copy(update={"quality_status": "PASS"})
    with pytest.raises(ValueError):
        annotate(tampered, event)
    assert aggregate(bundle()).scientific_digest == aggregate(bundle()).scientific_digest


@pytest.mark.vid("V-E6-5")
def test_cli_exports_diagnostic_and_rejects_forged_eligibility(tmp_path):
    path = tmp_path / "decision.json"
    path.write_text(bundle().model_dump_json(), encoding="utf-8")
    args = [sys.executable, "-m", "geoqc", "decision", "--input", str(path)]
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["eligible_for_acceptance"] is False and payload["verdict"] == "YELLOW"
    path.write_text(json.dumps(bundle().model_dump(mode="json") | {"eligible_for_acceptance": True}), encoding="utf-8")
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 2 and not result.stdout


@pytest.mark.vid("V-E6-4")
def test_common_qc_adapter_retains_trace_support_and_upstream_missing():
    from geoqc.core.config import load_config
    from geoqc.io.readers import read_shot
    from geoqc.qc import common_qc
    from geoqc.qc.contracts import QCProtocol

    shot = read_shot(Path("examples/e2/common_qc.sgy"))
    protocol = QCProtocol.model_validate_json(Path("examples/e2/protocol.json").read_text(encoding="utf-8"))
    report = QCReport.model_validate(common_qc(shot, protocol, load_config(Path("configs/vs30_sitio.yaml")))["report"])
    adapted = record_from_common_qc(shot, report)
    assert len(adapted.metrics) == len(report.metrics)
    assert len({m.id for m in adapted.metrics}) == len(report.metrics)
    assert adapted.upstream_missing_requirement_ids == report.missing_requirement_ids
    req = requirement(
        record_id=shot.id,
        metric_id=adapted.metrics[0].id,
        technique=shot.acquisition.technique,
        unit=adapted.metrics[0].unit,
        support_refs=adapted.metrics[0].support_refs,
        calibration_required=True,
    )
    result = aggregate(bundle(records=(adapted,), requirements=(req,), selected_record_ids=(shot.id,)))
    assert result.evidence_status == "INCOMPLETE"
    assert result.eligible_for_acceptance is False
    with pytest.raises(ValueError, match="hashes"):
        record_from_common_qc(shot, report.model_copy(update={"data_hashes": ("b" * 64,)}))
