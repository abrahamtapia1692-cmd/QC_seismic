"""Exploración del protocolo registrado; no emite estados de gates."""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoqc.trs.picking import pick_trace  # noqa: E402
from tests.synthetic.e4_support import pick_protocol, realization, trs_shot  # noqa: E402

for db in (15, 20, 30):
    rng = np.random.default_rng(4410 + db)
    errors, states = [], {}
    for _ in range(500):
        data, truth = realization(rng, db)
        pick = pick_trace(trs_shot(data), 0, pick_protocol(db))
        states[pick.confidence] = states.get(pick.confidence, 0) + 1
        if pick.onset_s is not None:
            errors.append(pick.onset_s - truth)
    print(
        db,
        states,
        "bias/median/P95",
        np.mean(errors),
        np.median(abs(np.array(errors))),
        np.percentile(abs(np.array(errors)), 95),
    )
