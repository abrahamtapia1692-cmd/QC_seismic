"""Capturar versiones de dependencias E0 del entorno Windows/Python 3.12."""

from importlib.metadata import requires, version
from pathlib import Path

from packaging.requirements import Requirement

NAMES = (
    "numpy",
    "scipy",
    "pydantic",
    "pydantic_core",
    "annotated-types",
    "typing_extensions",
    "typing-inspection",
    "PyYAML",
    "pytest",
    "hypothesis",
    "ruff",
    "mypy",
    "mypy_extensions",
    "types-PyYAML",
    "sortedcontainers",
    "iniconfig",
    "packaging",
    "pluggy",
    "colorama",
    "pathspec",
    "librt",
    "ast_serialize",
    "setuptools",
    "Pygments",
    "disba",
    "obspy",
    "pytest-cov",
    "coverage",
)

if __name__ == "__main__":
    lines = ["# Entorno observado: Windows, CPython 3.12.3; versiones, sin hashes de wheels."]
    found = {name.lower().replace("_", "-") for name in NAMES}
    pending = list(found)
    while pending:
        package = pending.pop()
        for expression in requires(package) or ():
            requirement = Requirement(expression)
            if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
                continue
            name = requirement.name.lower().replace("_", "-")
            if name not in found:
                found.add(name)
                pending.append(name)
    lines.extend(f"{name}=={version(name)}" for name in sorted(found))
    path = Path(__file__).resolve().parents[1] / "requirements-win-py312.lock"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(path.read_text(encoding="utf-8"))
