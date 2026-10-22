from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    dsn: str
    storage_root: Path
    schema: str = "geoqc_app"
    lease_seconds: int = 15
    heartbeat_seconds: float = 2
    calculation_timeout_seconds: float = 120
    memory_limit_mib: int = 1024
    max_attempts: int = 3
    upload_ttl_seconds: int = 86400

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.schema):
            raise ValueError("Nombre de esquema inválido")
        if self.lease_seconds < 3 or not 0 < self.heartbeat_seconds < self.lease_seconds / 2:
            raise ValueError("Heartbeat incompatible con lease")
        if self.calculation_timeout_seconds <= 0 or self.memory_limit_mib < 128 or self.max_attempts < 1:
            raise ValueError("Límites de ejecución inválidos")
        if type(self.upload_ttl_seconds) is not int or not 60 <= self.upload_ttl_seconds <= 604800:
            raise ValueError("Vigencia de carga requerida entre 60 segundos y siete días")

    @classmethod
    def load(cls, path: Path) -> Settings:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["storage_root"] = Path(data["storage_root"]).resolve()
        return cls(**data)
