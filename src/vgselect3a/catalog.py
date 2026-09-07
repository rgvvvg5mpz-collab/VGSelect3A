"""Model catalog: the ecosystem of models a subagent may run on.

A catalog is a list of ModelSpec entries loaded from JSON (the bundled default,
a file given on the command line / VGSELECT_CATALOG, or models posted with an
API request). Entries describe governance (provider, platforms, regions,
approval, data classes), capability (reasoning tier, tool use, structured
output, context, modalities, effort control), performance (TTFT, tokens/s,
rate limits), cost, and measured evidence per task family. See
docs/MODEL_CATALOG.html for the schema and how to maintain it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from importlib import resources
from pathlib import Path
from typing import Any, Iterable

PROVIDERS_KNOWN = ("anthropic", "openai", "google", "meta", "mistral", "amazon", "microsoft", "cohere", "deepseek", "xai", "self_hosted", "other")
PLATFORMS_KNOWN = ("anthropic_api", "bedrock", "vertex", "foundry", "openai_api", "azure_openai", "google_api", "self_hosted", "other")
DATA_CLASSES = ("public", "internal", "confidential", "restricted")
MODALITIES = ("text", "image", "pdf", "audio", "video")
TASK_FAMILIES = ("general", "classification", "extraction", "research", "writing", "coding", "evaluation", "conversation", "planning")


@dataclass
class ModelSpec:
    id: str
    display_name: str
    provider: str
    family: str
    platforms: list[str]
    regions: list[str] = field(default_factory=lambda: ["global"])
    approved: bool = True
    data_classes: list[str] = field(default_factory=lambda: ["public", "internal"])
    retention: str = "standard"                # standard | zero
    deprecation_date: str | None = None        # ISO date
    # capability
    reasoning_tier: int = 3                    # 1 trivial .. 5 frontier
    tool_use: int = 2                          # 0 none, 1 basic, 2 reliable, 3 reliable + parallel
    structured_output: bool = True
    strict_schema: bool = False
    context_window: int = 128_000
    max_output: int = 8_192
    modalities: list[str] = field(default_factory=lambda: ["text"])
    thinking: bool = False
    effort_control: bool = False
    # performance
    ttft_s: float = 1.0
    tokens_per_s: float = 80.0
    rpm: int | None = None
    tpm: int | None = None
    max_concurrency: int | None = None
    batch: bool = False
    # cost (USD per million tokens)
    input_price: float = 1.0
    output_price: float = 5.0
    cache_read_price: float | None = None
    batch_discount: float = 0.0
    # evidence: task family -> measured accuracy 0..1 on your own evals
    evidence: dict[str, float] = field(default_factory=dict)
    # provenance
    langchain_provider: str | None = None      # value for langchain.chat_models.init_chat_model(model_provider=...)
    illustrative: bool = False                 # numbers are placeholders to be replaced from your registry
    verified_on: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        problems = []
        if not (1 <= int(self.reasoning_tier) <= 5):
            problems.append(f"{self.id}: reasoning_tier must be 1..5")
        if not (0 <= int(self.tool_use) <= 3):
            problems.append(f"{self.id}: tool_use must be 0..3")
        for d in self.data_classes:
            if d not in DATA_CLASSES:
                problems.append(f"{self.id}: unknown data class {d!r}")
        for m in self.modalities:
            if m not in MODALITIES:
                problems.append(f"{self.id}: unknown modality {m!r}")
        for k, v in self.evidence.items():
            if k not in TASK_FAMILIES or not (0.0 <= float(v) <= 1.0):
                problems.append(f"{self.id}: evidence {k}={v} must be a known task family with a value in 0..1")
        if not self.platforms:
            problems.append(f"{self.id}: at least one platform required")
        if problems:
            raise ValueError("; ".join(problems))
        if self.langchain_provider is None:
            self.langchain_provider = {"anthropic": "anthropic", "openai": "openai", "google": "google_genai", "amazon": "bedrock_converse",
                                       "mistral": "mistralai", "cohere": "cohere", "deepseek": "deepseek", "xai": "xai"}.get(self.provider)

    @property
    def tier_name(self) -> str:
        """Colour/tier bucket used by the plan and diagrams."""
        return {5: "opus", 4: "sonnet"}.get(int(self.reasoning_tier), "haiku")

    def call_latency_s(self, output_tokens: float) -> float:
        return self.ttft_s + output_tokens / max(1.0, self.tokens_per_s)

    def call_cost_usd(self, input_tokens: float, output_tokens: float) -> float:
        return (input_tokens * self.input_price + output_tokens * self.output_price) / 1e6

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ModelSpec":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Catalog:
    models: list[ModelSpec]
    name: str = "catalog"
    source: str = ""

    # ---------------------------------------------------------------- loading
    @classmethod
    def default(cls) -> "Catalog":
        path = resources.files("vgselect3a") / "catalogs" / "default.json"
        return cls.from_json(path.read_text(encoding="utf-8"), source="bundled default")

    @classmethod
    def load(cls, path: str | Path) -> "Catalog":
        p = Path(path)
        return cls.from_json(p.read_text(encoding="utf-8"), source=str(p))

    @classmethod
    def from_json(cls, text: str, source: str = "") -> "Catalog":
        data = json.loads(text)
        return cls.from_dict(data, source)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | list[dict[str, Any]], source: str = "") -> "Catalog":
        if isinstance(data, list):
            models, name = data, "catalog"
        else:
            models, name = data.get("models", []), data.get("name", "catalog")
        specs = [ModelSpec.from_dict(m) for m in models]
        ids = [m.id for m in specs]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate model ids in catalog: {sorted(dupes)}")
        return cls(specs, name=name, source=source)

    def merged(self, extra: Iterable[ModelSpec]) -> "Catalog":
        """Entries in `extra` override bundled entries with the same id."""
        by_id = {m.id: m for m in self.models}
        for m in extra:
            by_id[m.id] = m
        return Catalog(list(by_id.values()), name=self.name, source=self.source + " + overrides")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "source": self.source, "models": [m.to_dict() for m in self.models]}

    # ---------------------------------------------------------------- lookup
    def get(self, model_id: str) -> ModelSpec | None:
        return next((m for m in self.models if m.id == model_id), None)

    def providers(self) -> list[str]:
        return sorted({m.provider for m in self.models})

    def platforms(self) -> list[str]:
        return sorted({p for m in self.models for p in m.platforms})

    def regions(self) -> list[str]:
        return sorted({r for m in self.models for r in m.regions})
