import json
import subprocess
import sys

import numpy as np
import pytest

from geoqc.io.writers import write_segy
from geoqc.trs.contracts import TRSProtocol
from tests.synthetic.e4_support import pick_protocol, realization, trs_shot


@pytest.mark.vid("V-E4-17")
def test_trs_cli_unvalidated_report_and_invalid_protocol(tmp_path):
    rng = np.random.default_rng(41701)
    data, _ = realization(rng, 20)
    waveform = tmp_path / "wave.sgy"
    write_segy(waveform, trs_shot(np.tile(data, (12, 1))))
    settings = tmp_path / "protocol.json"
    protocol = TRSProtocol(picking=pick_protocol(), provenance="CLI synthetic test")
    settings.write_text(protocol.model_dump_json(), encoding="utf-8")
    command = [sys.executable, "-X", "utf8", "-m", "geoqc", "trs", str(waveform), "--protocol", str(settings)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["eligible_for_acceptance"] is False and output["evidence_status"] == "INCOMPLETE"
    assert len(output["picks"]) == 12
    assert all(row["arrival"]["confidence"] == "UNCALIBRATED" for row in output["picks"])
    settings.write_text('{"picking":{},"horizontal_two_layers_verified":true,"provenance":"bad"}', encoding="utf-8")
    bad = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    assert bad.returncode == 2 and bad.stderr
