"""Summaries are cheap to list; detailed instructions load only on selection."""

from __future__ import annotations

from pathlib import Path


class SkillRegistry:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or Path(__file__).resolve().parents[1] / "skills"
        self._skills: dict[str, tuple[str, Path]] = {}

    def discover(self) -> None:
        discovered = {}
        for path in sorted(self.directory.glob("*/SKILL.md")):
            if not path.parent.name.replace("_", "").isalnum():
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            summary = next((line.strip() for line in lines if line.strip() and not line.startswith("#")), "")
            discovered[path.parent.name] = (summary[:240], path)
        self._skills = discovered

    def summaries(self) -> list[dict]:
        return [{"id": name, "description": summary} for name, (summary, _) in self._skills.items()]

    def load(self, skill_id: str) -> str:
        return self._skills[skill_id][1].read_text(encoding="utf-8")
