"""Ejemplo E6 desde QC común real del fixture sintético E2; sin aceptación."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.core.config import load_config  # noqa: E402
from geoqc.core.models import QCReport  # noqa: E402
from geoqc.decision import DecisionInput, Requirement, aggregate, record_from_common_qc  # noqa: E402
from geoqc.io.readers import read_shot  # noqa: E402
from geoqc.qc import common_qc  # noqa: E402
from geoqc.qc.contracts import QCProtocol  # noqa: E402


def main() -> int:
    shot = read_shot(ROOT / "examples/e2/common_qc.sgy")
    config = load_config(ROOT / "configs/vs30_sitio.yaml")
    protocol = QCProtocol.model_validate_json((ROOT / "examples/e2/protocol.json").read_text(encoding="utf-8"))
    report = QCReport.model_validate(common_qc(shot, protocol, config)["report"])
    record = record_from_common_qc(shot, report)
    data = DecisionInput(
        profile_ref="vs30_sitio/DRAFT/common_qc_demo",
        scope_ref="synthetic_e2/observed_traces",
        scope_status="IN_SCOPE",
        records=(record,),
        selected_record_ids=(record.id,),
        requirements=tuple(
            Requirement(
                id=f"common/{m.id}",
                record_id=record.id,
                metric_id=m.id,
                unit=m.unit,
                support_refs=m.support_refs,
                technique=record.technique,
                component=record.component,
                mandatory=True,
                critical=m.critical,
                applicability="APPLICABLE",
                applicability_reason="Control por traza declarado para fixture E2",
                calibration_required=True,
            )
            for m in record.metrics
        ),
    )
    directory = ROOT / "examples/e6"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "input.json").write_text(data.model_dump_json(indent=2) + "\n", encoding="utf-8")
    result = aggregate(data)
    (directory / "report.json").write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"{directory.relative_to(ROOT)}: {result.verdict}, {result.evidence_status}, aceptación=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
