from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from geoqc_app.errors import AppError


@dataclass(frozen=True)
class Blob:
    key: str
    sha256: str
    size: int


class BlobWriter:
    def __init__(self, store: ArtifactStore, limit: int) -> None:
        self.store, self.limit = store, limit
        self.key = uuid.uuid4().hex
        self.temporary = store.root / "temporary" / self.key
        self.file: BinaryIO = self.temporary.open("xb")
        self.hash, self.size = hashlib.sha256(), 0

    def write(self, chunk: bytes) -> None:
        if self.size + len(chunk) > self.limit:
            raise AppError(413, "UPLOAD_TOO_LARGE", "Archivo excede el límite permitido")
        self.file.write(chunk)
        self.hash.update(chunk)
        self.size += len(chunk)

    def finish(self) -> Blob:
        self.file.flush()
        os.fsync(self.file.fileno())
        self.file.close()
        os.link(self.temporary, self.store.path(self.key))
        self.temporary.unlink()
        return Blob(self.key, self.hash.hexdigest(), self.size)

    def abort(self) -> None:
        self.file.close()
        self.temporary.unlink(missing_ok=True)


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        for folder in (self.root, self.root / "temporary", self.root / "blobs", self.root / "attempts"):
            folder.mkdir(parents=True, exist_ok=True)

    def bind(self, namespace: str) -> None:
        """A storage root belongs to one database/schema, including during maintenance."""
        marker = self.root / "namespace.json"
        temporary = self.root / ("namespace-" + uuid.uuid4().hex + ".writing")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump({"namespace": namespace}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, marker)
            except FileExistsError:
                pass
            if json.loads(marker.read_bytes()) != {"namespace": namespace}:
                raise ValueError("El almacenamiento pertenece a otra base o esquema")
        finally:
            temporary.unlink(missing_ok=True)

    def path(self, key: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", key):
            raise AppError(404, "ARTIFACT_NOT_FOUND", "Artefacto no encontrado")
        return self.root / "blobs" / key

    def cursor_key(self) -> bytes:
        """Persist outside downloadable blobs; atomic creation permits parallel API startup."""
        path = self.root / ".cursor-key"
        temporary = self.root / (".cursor-key-" + uuid.uuid4().hex + ".writing")
        try:
            with temporary.open("xb") as stream:
                os.chmod(temporary, 0o600)
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            key = path.read_bytes()
            if len(key) != 32:
                raise ValueError("Clave de cursores local dañada; se requiere reparación")
            return key
        finally:
            temporary.unlink(missing_ok=True)

    def begin(self, limit: int) -> BlobWriter:
        if shutil.disk_usage(self.root).free < limit + 128 * 1024**2:
            raise AppError(503, "STORAGE_CAPACITY", "Espacio local insuficiente")
        return BlobWriter(self, limit)

    def put(self, content: bytes, *, limit: int = 64 * 1024**2) -> Blob:
        writer = self.begin(limit)
        try:
            writer.write(content)
            return writer.finish()
        except BaseException:
            writer.abort()
            raise

    def verify(self, blob: Blob) -> Path:
        path = self.path(blob.key)
        digest, size = hashlib.sha256(), 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024**2), b""):
                digest.update(chunk)
                size += len(chunk)
        if size != blob.size or digest.hexdigest() != blob.sha256:
            raise AppError(409, "ARTIFACT_INTEGRITY", "Integridad del artefacto no comprobada")
        return path
