"""User-scoped artifact IDs backed by bounded files and SQL metadata."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.db.models import AgentArtifact, AgentTaskEvent


_EXTENSIONS = {"text/markdown": ".md", "text/plain": ".txt", "application/json": ".json",
               "application/xml": ".drawio", "image/svg+xml": ".svg",
               "image/png": ".png", "image/jpeg": ".jpg",
               "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx"}


class ArtifactStore:
    def __init__(self, session_factory, data_dir: Path):
        self.session_factory = session_factory
        self.directory = data_dir.resolve() / "agent_artifacts"

    def save(self, content: bytes, *, user_id: str, task_id: str, kind: str,
             filename: str, mime_type: str, source_ids: list[str] | None = None,
             version: int = 1) -> str:
        if len(content) > 20_000_000:
            raise ValueError("Artifact exceeds 20 MB")
        artifact_id = str(uuid4())
        extension = _EXTENSIONS.get(mime_type, ".bin")
        folder = self.directory / user_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{artifact_id}{extension}"
        temporary = folder / f"{artifact_id}.tmp"
        temporary.write_bytes(content)
        temporary.replace(path)
        try:
            with self.session_factory() as db:
                db.add(AgentArtifact(id=artifact_id, user_id=user_id, task_id=task_id,
                                     kind=kind, filename=Path(filename).name[:180],
                                     mime_type=mime_type, storage_path=str(path),
                                     source_ids_json=source_ids or [], version=version))
                db.add(AgentTaskEvent(task_id=task_id, kind="artifact_saved",
                                      detail_json={"artifact_id": artifact_id, "kind": kind,
                                                   "version": version, "source_ids": source_ids or [],
                                                   "bytes": len(content)}))
                db.commit()
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return artifact_id

    def save_text(self, content: str, **kwargs) -> str:
        return self.save(content.encode("utf-8"), **kwargs)

    def read(self, artifact_id: str, *, user_id: str) -> tuple[AgentArtifact, bytes]:
        with self.session_factory() as db:
            row = db.get(AgentArtifact, artifact_id)
            if row is None or row.user_id != user_id:
                raise KeyError(artifact_id)
            db.expunge(row)
        path = Path(row.storage_path).resolve()
        if not path.is_relative_to(self.directory):
            raise ValueError("Artifact path escaped storage root")
        return row, path.read_bytes()

    def list_for_task(self, task_id: str, *, user_id: str) -> list[dict]:
        with self.session_factory() as db:
            rows = db.scalars(select(AgentArtifact).where(AgentArtifact.task_id == task_id,
                                                          AgentArtifact.user_id == user_id)
                              .order_by(AgentArtifact.created_at, AgentArtifact.id)).all()
            return [{"id": row.id, "kind": row.kind, "filename": row.filename,
                     "mimeType": row.mime_type, "sourceIds": row.source_ids_json,
                     "version": row.version, "createdAt": row.created_at.isoformat()} for row in rows]
