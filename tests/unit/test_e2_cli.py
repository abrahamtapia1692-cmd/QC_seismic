import json
import subprocess
import sys

import numpy as np
import pytest

from geoqc.io.writers import write_segy
from tests.synthetic.test_e2 import protocol, shot


@pytest.mark.vid("V-E2-10")
def test_qc_cli_and_invalid_protocol(tmp_path):
    waveform = tmp_path / "shot.sgy"
    write_segy(waveform, shot(np.tile(np.sin(np.arange(1000) * 0.1), (3, 1)), rails=(-2, 2)))
    settings = tmp_path / "protocol.json"
    settings.write_text(protocol(1, rail_scale_to_data=1).model_dump_json(), encoding="utf-8")
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "geoqc",
        "qc",
        str(waveform),
        "--config",
        "configs/vs30_sitio.yaml",
        "--protocol",
        str(settings),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["scope"] == "COMMON_QC_DIAGNOSTIC_ONLY"
    assert output["eligible_for_acceptance"] is False
    assert all(trace["clip"]["value"] == 0 for trace in output["traces"])
    settings.write_text('{"analysis":{"start_s":1,"end_s":0},"provenance":"bad"}', encoding="utf-8")
    failed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert failed.returncode == 2 and failed.stderr
