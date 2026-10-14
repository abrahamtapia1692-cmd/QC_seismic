import json
import subprocess
import sys

import pytest

from geoqc.io.writers import write_segy
from tests.unit.test_e1 import fixture_shot


@pytest.mark.vid("V-E1-2")
def test_inspect_cli_valid_and_missing_metadata_are_structured(tmp_path):
    path = tmp_path / "cli.sgy"
    write_segy(path, fixture_shot())
    result = subprocess.run(
        [sys.executable, "-m", "geoqc", "inspect", str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["n_channels"] == 3
    assert summary["dt_s"] == [0.001] * 3
    assert summary["eligible_for_acceptance"] is False
    path.with_suffix(path.suffix + ".json").unlink()
    failed = subprocess.run(
        [sys.executable, "-m", "geoqc", "inspect", str(path)], capture_output=True, text=True, check=False
    )
    assert failed.returncode == 2
    assert json.loads(failed.stdout)["error_code"] == "METADATA_MISSING"
