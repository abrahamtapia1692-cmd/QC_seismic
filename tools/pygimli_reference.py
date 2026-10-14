"""Proceso aislado: pyGIMLi Dijkstra, no importa algoritmos forward de GeoQC."""

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import sys
from pathlib import Path

import numpy as np
import pygimli as pg
from pygimli.physics import traveltime as tt


def simulate(request: dict) -> dict:
    x, z = np.array(request["x_edges_m"]), np.array(request["z_edges_m"])
    # pyGIMLi y = elevación; contrato GeoQC z = profundidad positiva.
    mesh = pg.meshtools.createGrid(x=x, y=-z[::-1])
    center_x = np.array([cell.center().x() for cell in mesh.cells()])
    depth = -np.array([cell.center().y() for cell in mesh.cells()])
    model = request["model"]
    if model["kind"] == "gradient":
        velocity = model["v0_ms"] + model["gradient_s_inv"] * depth
    elif model["kind"] == "homogeneous":
        velocity = np.full(mesh.cellCount(), model["velocity_ms"])
    elif model["kind"] == "two_layer":
        velocity = np.where(depth < model["thickness_m"], model["v1_ms"], model["v2_ms"])
    else:
        raise ValueError("Modelo de referencia desconocido")
    scheme = tt.DataContainerTT()
    scheme.createSensor([*request["source_xz_m"][:1], -request["source_xz_m"][1]])
    for receiver in request["receivers_xz_m"]:
        scheme.createSensor([receiver[0], -receiver[1]])
    count = len(request["receivers_xz_m"])
    scheme.resize(count)
    scheme["s"] = np.zeros(count)
    scheme["g"] = np.arange(1, count + 1)
    scheme["valid"] = np.ones(count)
    manager = tt.TravelTimeManager()
    times = manager.simulate(
        mesh=mesh,
        scheme=scheme,
        vel=velocity,
        secNodes=request["secondary_nodes"],
        noiseLevel=0,
        noiseAbs=0,
        returnArray=True,
    )
    response = {
        "times_s": np.asarray(times).tolist(),
        "version": pg.__version__,
        "pgcore_version": importlib.metadata.version("pgcore"),
        "numpy_version": np.__version__,
        "method": "Dijkstra shortest paths on mesh with secondary nodes",
        "secondary_nodes": request["secondary_nodes"],
        "mesh_cells": int(mesh.cellCount()),
        "velocity_extrema_ms": [float(min(velocity)), float(max(velocity))],
        "cell_center_x_range_m": [float(min(center_x)), float(max(center_x))],
        "z_convention": "depth positive -> pygimli y negative",
    }
    if request.get("include_ray_paths", False):
        # La API requiere crear el Jacobiano para conservar los caminos Dijkstra.
        response["rays_xz_m"] = [
            np.column_stack((points[:, 0], -points[:, 1])).tolist() for points in manager.getRayPaths(model=velocity)
        ]
    return response


if __name__ == "__main__":
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    with contextlib.redirect_stdout(sys.stderr):
        response = simulate(request)
    Path(sys.argv[2]).write_text(json.dumps(response, indent=2, allow_nan=False) + "\n", encoding="utf-8")
