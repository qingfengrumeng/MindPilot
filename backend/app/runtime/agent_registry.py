"""Discover trusted, directory-installed agent plugins from compact manifests."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from app.runtime.tool_registry import ToolRegistry


_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class AgentManifest(BaseModel):
    id: str
    version: str
    description: str = Field(min_length=1, max_length=500)
    intents: list[str] = Field(min_length=1)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = Field(default=None, ge=30, le=1800)
    entrypoint: str
    input_schema: str

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not _ID.fullmatch(value):
            raise ValueError("Invalid agent id")
        return value

    @field_validator("version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        if not _VERSION.fullmatch(value):
            raise ValueError("Version must be major.minor.patch")
        return value

    @field_validator("entrypoint", "input_schema")
    @classmethod
    def valid_entrypoint(cls, value: str) -> str:
        module, separator, function = value.partition(":")
        if not separator or not module.startswith("app.plugins.") or not function.isidentifier():
            raise ValueError("Entrypoint must be app.plugins.<name>.<module>:<function>")
        return value

    def summary(self) -> dict:
        return {"id": self.id, "version": self.version, "description": self.description,
                "intents": self.intents, "inputs": self.inputs, "outputs": self.outputs}


class AgentRegistry:
    def __init__(self, tools: ToolRegistry, directory: Path | None = None):
        self.tools = tools
        self.directory = directory or Path(__file__).resolve().parents[1] / "plugins"
        self._manifests: dict[str, AgentManifest] = {}

    def discover(self) -> None:
        discovered = {}
        if not self.directory.exists():
            self._manifests = discovered
            return
        for file in sorted(self.directory.glob("*/manifest.yaml")):
            raw = yaml.safe_load(file.read_text(encoding="utf-8"))
            manifest = AgentManifest.model_validate(raw)
            if manifest.id != file.parent.name or manifest.id in discovered:
                raise ValueError(f"Plugin id mismatch or duplicate: {file}")
            module_name, function_name = manifest.entrypoint.split(":", 1)
            schema_module, schema_name = manifest.input_schema.split(":", 1)
            if not module_name.startswith(f"app.plugins.{manifest.id}."):
                raise ValueError(f"Plugin entrypoint escapes its package: {file}")
            if schema_module != module_name:
                raise ValueError(f"Plugin input schema must share the entrypoint module: {file}")
            module_spec = importlib.util.find_spec(module_name)
            if module_spec is None or not module_spec.origin:
                raise ValueError(f"Plugin entrypoint module not found: {module_name}")
            source = Path(module_spec.origin).read_text(encoding="utf-8")
            definitions = ast.parse(source, filename=module_spec.origin).body
            if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and node.name == function_name for node in definitions):
                raise ValueError(f"Plugin entrypoint function not found: {manifest.entrypoint}")
            if not any(isinstance(node, ast.ClassDef) and node.name == schema_name for node in definitions):
                raise ValueError(f"Plugin input schema not found: {manifest.input_schema}")
            missing = [name for name in manifest.required_tools if not self.tools.has(name)]
            if missing:
                raise ValueError(f"Plugin {manifest.id} requires missing tools: {', '.join(missing)}")
            discovered[manifest.id] = manifest
        self._manifests = discovered

    def get(self, agent_id: str) -> AgentManifest:
        return self._manifests[agent_id]

    def summaries(self) -> list[dict]:
        return [manifest.summary() for manifest in self._manifests.values()]

    def candidates(self, intent: str) -> list[AgentManifest]:
        return [manifest for manifest in self._manifests.values() if intent in manifest.intents]

    def load(self, agent_id: str):
        manifest = self.get(agent_id)
        module_name, function = manifest.entrypoint.split(":", 1)
        module = importlib.import_module(module_name)
        handler = getattr(module, function, None)
        if not callable(handler):
            raise ValueError(f"Plugin entrypoint is not callable: {manifest.entrypoint}")
        schema_name = manifest.input_schema.split(":", 1)[1]
        schema = getattr(module, schema_name, None)
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise ValueError(f"Plugin input schema must be a Pydantic model: {manifest.input_schema}")
        return manifest, handler, schema

    def details(self, agent_id: str) -> dict:
        manifest, _, schema = self.load(agent_id)
        return {**manifest.model_dump(), "input_json_schema": schema.model_json_schema()}
