"""Regresiones de las brechas observadas; se amplían con los contratos R1."""

import pytest

from geoqc.core.models import DispersionCurve
from geoqc.masw.contracts import MASWProtocol
from geoqc.masw.curves import merge_curves
from geoqc.masw.report import masw_diagnostics
from geoqc.qc.contracts import Window
from tests.synthetic.e5_support import shot


@pytest.mark.vid("V-E5-7")
@pytest.mark.rm("RM-02", "reference")
@pytest.mark.rm("RM-08", "report_trust")
def test_unresolved_reference_cannot_confirm_observed_mode():
    import numpy as np

    x, t = np.arange(24) * 2, np.arange(1000) * 0.001
    data = sum(np.cos(2 * np.pi * f * (t[None, :] - x[:, None] / 200)) for f in (8, 16))
    protocol = MASWProtocol(
        signal=Window(start_s=0, end_s=1),
        frequencies_hz=(8, 16),
        velocities_ms=(180, 200, 220),
        directions=(1,),
        mode_identity="CONFIRMED",
        mode_evidence_ref="arbitrary-text",
        provenance="audit regression",
    )
    report = masw_diagnostics(shot(data, x=x), protocol)
    assert report["curves"][0]["mode_identity"] == "UNKNOWN"
    assert report["curves"][0]["declared_mode_identity"] == "CONFIRMED"
    assert not report["eligible_for_acceptance"]
    assert report["curves"][0]["band_controls"]["mode"] == "UNKNOWN"


@pytest.mark.vid("V-E5-22")
@pytest.mark.rm("RM-03", "unknowns")
def test_legacy_union_preserves_covariance_and_abstains():
    common = dict(
        frequencies_hz=(8.0,),
        sigma_ms=(1.0,),
        valid_mask=(True,),
        reasons=("VALID",),
        mode_identity="CONFIRMED",
        band_refs=("site",),
        covariance_ref="unresolved-shared-rho-0.99",
    )
    curves = tuple(
        DispersionCurve(**common, velocities_ms=(v,), point_provenance=(name,))
        for v, name in ((100.0, "a"), (101.0, "b"))
    )
    union = merge_curves(curves)
    assert union["points"][0]["compatible_overlap"] is None
    assert union["points"][0]["contributions"][0]["covariance_ref"] == common["covariance_ref"]
    assert union["schema_version"] == "1.4-r1"


def r1curve(name, velocities=(100.0,), modes=("M0",)):
    from geoqc.masw.r1 import CurveR1

    return CurveR1(
        frequencies_hz=tuple(8.0 * (i + 1) for i in range(len(velocities))),
        velocities_ms=velocities,
        sigma_ms=(1.0,) * len(velocities),
        valid_mask=(True,) * len(velocities),
        reasons=("VALID",) * len(velocities),
        mode_identity="APPARENT",
        point_provenance=tuple(f"{name}:{i}" for i in range(len(velocities))),
        point_ids=tuple(f"{name}:{i}" for i in range(len(velocities))),
        mode_labels=modes,
        support_refs=("site:A:Z:d1",) * len(velocities),
        band_refs=("site:A",),
    )


@pytest.mark.vid("V-E5-22")
@pytest.mark.rm("RM-03", "covariance")
def test_correlated_difference_and_explicit_independence():
    from geoqc.masw.r1 import JointCovariance

    a, b = r1curve("a"), r1curve("b", (101.0,))
    for rho, expected in ((0, True), (0.99, False), (1.0, False)):
        cov = JointCovariance(point_ids=("a:0", "b:0"), matrix=((1, rho), (rho, 1)), provenance="known")
        result = merge_curves((a, b), covariance=cov, compatibility_sigma=3)
        assert result["points"][0]["compatible_overlap"] is expected
        assert result["covariance"]["matrix"] == [[1, rho], [rho, 1]]
        assert not result["eligible_for_acceptance"]


@pytest.mark.vid("V-E5-22")
@pytest.mark.rm("RM-03", "joint")
def test_joint_covariance_order_and_singular_nullspace():
    import numpy as np

    from geoqc.masw.r1 import JointCovariance

    a, b = r1curve("a", (100, 100), ("M0", "M0")), r1curve("b", (101, 99), ("M0", "M0"))
    ids = ("a:0", "a:1", "b:0", "b:1")
    cov = np.array([[1, 0.5, 0, 0], [0.5, 1, 0, 0], [0, 0, 1, 0.5], [0, 0, 0.5, 1]])
    for order in ([0, 1, 2, 3], [3, 1, 0, 2]):
        model = JointCovariance(
            point_ids=tuple(ids[i] for i in order), matrix=cov[np.ix_(order, order)], provenance="known"
        )
        result = merge_curves((a, b), covariance=model, compatibility_sigma=3)
        joint = result["overlap_statistic"]
        np.testing.assert_allclose(joint["difference_covariance"], [[2, 1], [1, 2]], atol=1e-12)
        assert joint["mahalanobis_squared"] == pytest.approx(2.0, abs=1e-12)
        assert joint["rank"] == 2
    singular = JointCovariance(point_ids=ids, matrix=np.ones((4, 4)), provenance="common exact error")
    joint = merge_curves((a, b), covariance=singular, compatibility_sigma=3)["overlap_statistic"]
    assert joint["rank"] == 0 and joint["nullspace_inconsistent"]
    assert joint["mahalanobis_squared"] is None


@pytest.mark.vid("V-E5-22")
@pytest.mark.rm("RM-03", "duplicates_modes")
def test_duplicates_modes_support_and_unknown_covariance():
    from geoqc.masw.r1 import JointCovariance

    a = r1curve("a")
    cov = JointCovariance(point_ids=("a:0",), matrix=((1,),), provenance="single observation")
    result = merge_curves((a, a), covariance=cov, compatibility_sigma=3)
    assert result["unique_observation_count"] == 1
    assert result["points"][0]["contributions"][1]["duplicate_of"] == "a:0"
    assert result["covariance"]["matrix"] == [[1]]
    for b in (r1curve("b", modes=("M1",)), r1curve("b").model_copy(update={"support_refs": ("site:B",)})):
        assert merge_curves((a, b))["points"][0]["compatible_overlap"] is False
    assert merge_curves((a, r1curve("b")))["points"][0]["compatible_overlap"] is None
    with pytest.raises(ValueError, match="identidad"):
        merge_curves((a, r1curve("a", (102,))))


@pytest.mark.vid("V-E0-9")
@pytest.mark.rm("RM-03", "validation")
@pytest.mark.parametrize("matrix", [((1, 2), (2, 1)), ((1, 0), (1, 1)), ((1, float("nan")), (0, 1)), ((1,),)])
def test_covariance_invalid_inputs(matrix):
    from geoqc.masw.r1 import JointCovariance

    with pytest.raises(ValueError):
        JointCovariance(point_ids=("a:0", "b:0"), matrix=matrix, provenance="bad")


@pytest.mark.vid("V-E0-9")
@pytest.mark.rm("RM-08", "migration")
def test_explicit_migration_and_unknown_schema():
    from geoqc.masw.r1 import CurveR1, migrate_curve

    old = DispersionCurve(
        frequencies_hz=(8,),
        velocities_ms=(100,),
        sigma_ms=(1,),
        valid_mask=(True,),
        reasons=("VALID",),
        mode_identity="CONFIRMED",
        point_provenance=("old",),
    )
    migrated = migrate_curve(old)
    assert migrated.schema_version == "1.4-r1"
    assert migrated.mode_labels == (None,) and migrated.mode_identity == "UNKNOWN"
    assert migrated.declared_mode_identity == "CONFIRMED"
    assert old.mode_identity == "CONFIRMED"
    with pytest.raises(ValueError):
        CurveR1.model_validate(migrated.model_dump() | {"schema_version": "2.0"})


@pytest.mark.vid("V-E5-7")
@pytest.mark.rm("RM-02", "reference")
def test_modal_evidence_authority_scope_tampering_and_partial_support():
    from geoqc.core.evidence import canonical_hash
    from geoqc.masw.r1 import ModalApproval, ModalEvidence, resolve_modes

    evidence = ModalEvidence(
        id="record",
        shot_hash="a" * 64,
        protocol_hash="b" * 64,
        estimator_hash="c" * 64,
        domain_id="domain",
        direction=1,
        frequencies_hz=(8,),
        support_hashes=("d" * 64,),
        mode_labels=("M0",),
        authority_id="reviewer",
        method="manual external review",
        source_kind="HUMAN",
        alternatives=("M1", "mixture"),
        limitations="synthetic only",
    )
    approval = ModalApproval(content_hash=canonical_hash(evidence), authority_id="reviewer", active=True)
    context = dict(
        reference="record",
        requested="CONFIRMED",
        shot_hash="a" * 64,
        protocol_hash="b" * 64,
        estimator_hash="c" * 64,
        domain_id="domain",
        direction=1,
        frequencies_hz=(8, 16),
        support_hashes=("d" * 64, "d" * 64),
        observed=(True, True),
    )
    valid = resolve_modes(**context, evidence={"record": evidence}, approvals={"record": approval})
    assert valid["point_mode_identity"] == ["CONFIRMED", "UNKNOWN"]
    assert valid["mode_labels"] == ["M0", None]
    assert valid["mode_identity"] == "UNKNOWN"
    for changes in (
        {"direction": -1},
        {"shot_hash": "e" * 64},
        {"domain_id": "other"},
        {"support_hashes": ("e" * 64,) * 2},
        {"observed": (False, False)},
    ):
        invalid = resolve_modes(**(context | changes), evidence={"record": evidence}, approvals={"record": approval})
        assert "CONFIRMED" not in invalid["point_mode_identity"]
    for documents, approvals in (
        ({"record": evidence}, {}),
        ({"record": evidence.model_copy(update={"mode_labels": ("M1",)})}, {"record": approval}),
        ({"record": evidence}, {"record": approval.model_copy(update={"active": False})}),
    ):
        invalid = resolve_modes(**context, evidence=documents, approvals=approvals)
        assert "CONFIRMED" not in invalid["point_mode_identity"]


@pytest.mark.vid("V-E0-10")
@pytest.mark.rm("RM-08", "runner")
def test_supplement_requires_real_phases_revision_and_all_criteria():
    from geoqc.core.revisions import evaluate_supplement

    context = dict(supplement_hash="a" * 64, code_hash="b" * 64, protocol_hash="c" * 64)
    criteria = {"RM-02": ("reference", "population")}
    envelope = dict(
        document_revision="MASW-R1",
        **context,
        pytest_exit_code=0,
        tests=[
            {
                "nodeid": "test_reference",
                "status": "PASSED",
                "phases": dict(setup="passed", call="passed", teardown="passed"),
                "supplement_criteria": [["RM-02", "reference"]],
            },
        ],
    )
    assert evaluate_supplement(envelope, criteria, **context)["RM-02"] == "INCOMPLETE"
    envelope["tests"].append(
        envelope["tests"][0] | {"nodeid": "test_population", "supplement_criteria": [["RM-02", "population"]]}
    )
    assert evaluate_supplement(envelope, criteria, **context)["RM-02"] == "PASSED"
    for bad in (
        envelope | {"supplement_hash": "d" * 64},
        envelope | {"document_revision": "1.4"},
        envelope | {"tests": [dict(id="RM-02", status="PASSED")]},
        envelope | {"pytest_exit_code": 1},
    ):
        assert evaluate_supplement(bad, criteria, **context)["RM-02"] != "PASSED"
    envelope["tests"][1]["phases"]["call"] = "skipped"
    assert evaluate_supplement(envelope, criteria, **context)["RM-02"] != "PASSED"


@pytest.mark.vid("V-E0-10")
@pytest.mark.rm("RM-08", "runner")
def test_base_passed_never_closes_expanded_g5_or_descendants():
    import json
    from pathlib import Path

    from geoqc.core.revisions import expanded_gates

    manifest = json.loads(Path("docs/validation_manifest_v1_4.json").read_text(encoding="utf-8"))
    base = dict.fromkeys(manifest["gates"], "PASSED")
    required = tuple(f"RM-{i:02}" for i in range(1, 9))
    results = dict.fromkeys(required[:-1], "PASSED")
    expanded = expanded_gates(base, manifest, results, required)
    assert expanded["G4"] == "PASSED"
    assert all(expanded[gate] == "INCOMPLETE" for gate in ("G5", "G6", "G7", "G8", "G9", "G10"))


@pytest.mark.vid("V-E5-22")
@pytest.mark.rm("RM-03", "validation")
def test_covariance_binding_sigmas_and_missing_criterion():
    from geoqc.masw.r1 import JointCovariance

    a, b = r1curve("a"), r1curve("b")
    for ids, matrix in ((("x", "y"), ((1, 0), (0, 1))), (("a:0", "b:0"), ((2, 0), (0, 1)))):
        covariance = JointCovariance(point_ids=ids, matrix=matrix, provenance="test")
        with pytest.raises(ValueError):
            merge_curves((a, b), covariance=covariance, compatibility_sigma=3)
    covariance = JointCovariance(point_ids=("a:0", "b:0"), matrix=((1, 0), (0, 1)), provenance="test")
    assert merge_curves((a, b), covariance=covariance)["points"][0]["compatible_overlap"] is None
    for threshold in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            merge_curves((a, b), compatibility_sigma=threshold)


@pytest.mark.vid("V-E5-7")
@pytest.mark.rm("RM-02", "reference")
@pytest.mark.rm("RM-08", "report_trust")
def test_report_uses_external_approval_but_never_enables_acceptance():
    import numpy as np

    from geoqc.core.evidence import canonical_hash
    from geoqc.masw.r1 import ModalApproval, ModalEvidence
    from geoqc.masw.statistics import estimator_hash

    x, t = np.arange(24) * 2, np.arange(1000) * 0.001
    data = sum(np.cos(2 * np.pi * f * (t[None, :] - x[:, None] / 200)) for f in (8, 16))
    waveform = shot(data, x=x)
    protocol = MASWProtocol(
        signal=Window(start_s=0, end_s=1),
        frequencies_hz=(8, 16),
        velocities_ms=(180, 200, 220),
        directions=(1, -1),
        mode_identity="CONFIRMED",
        mode_evidence_ref="external",
        domain_id="test",
        provenance="known plane",
    )
    evidence = ModalEvidence(
        id="external",
        shot_hash=canonical_hash(waveform),
        protocol_hash=canonical_hash(protocol.model_dump(mode="json")),
        estimator_hash=estimator_hash(),
        domain_id="test",
        direction=1,
        frequencies_hz=(8, 16),
        support_hashes=(canonical_hash(waveform.acquisition.receiver_ids),) * 2,
        mode_labels=("M0",) * 2,
        authority_id="test-reviewer",
        method="known synthetic truth",
        source_kind="HUMAN",
        alternatives=("M1", "mixture"),
        limitations="test only",
    )
    approved = ModalApproval(content_hash=canonical_hash(evidence), authority_id="test-reviewer", active=True)
    report = masw_diagnostics(
        waveform, protocol, modal_evidence={"external": evidence}, modal_approvals={"external": approved}
    )
    assert report["curves"][0]["mode_identity"] == "CONFIRMED"
    assert report["curves"][0]["mode_labels"] == ["M0", "M0"]
    assert report["curves"][1]["mode_identity"] == "UNKNOWN"
    assert not report["eligible_for_acceptance"] and report["vs30_sufficiency"] == "NOT_ESTABLISHED"
    import hashlib
    from pathlib import Path

    assert report["supplement_hash"] == hashlib.sha256(Path("docs/validation_masw_r1.json").read_bytes()).hexdigest()


@pytest.mark.vid("V-E0-9")
@pytest.mark.rm("RM-03", "validation")
@pytest.mark.rm("RM-08", "migration")
def test_r1_contract_arrays_are_immutable_and_validate_shape():
    import numpy as np

    from geoqc.masw.r1 import CurveR1, JointCovariance, ModalEvidence

    matrix = np.eye(2)
    covariance = JointCovariance(point_ids=("a", "b"), matrix=matrix, provenance="known")
    matrix[0, 0] = 42
    assert covariance.matrix[0][0] == 1
    with pytest.raises(ValueError):
        JointCovariance(point_ids=("a", "a"), matrix=np.eye(2), provenance="known")
    a = r1curve("a")
    for change in (
        {"frequencies_hz": ()},
        {"valid_mask": (True,), "reasons": ("MISSING",)},
        {"mode_labels": ("unknown-id",)},
    ):
        with pytest.raises(ValueError):
            CurveR1.model_validate(a.model_dump() | change)
    with pytest.raises(ValueError):
        ModalEvidence.model_validate({"schema_version": "2.0"})
