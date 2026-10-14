from pathlib import Path

from geoqc.core.models import IngestFailure


class IngestError(ValueError):
    def __init__(self, code: str, reason: str, action: str = "CHECK_FORMAT_AND_METADATA") -> None:
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason
        self.action = action

    def failure(self, path: Path, data_hash: str | None) -> IngestFailure:
        return IngestFailure(
            path=str(path), data_hash=data_hash, error_code=self.code, reason=self.reason, action_ids=(self.action,)
        )
