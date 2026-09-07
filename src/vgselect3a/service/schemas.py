"""Pydantic request/response models. The profile model is generated from
FIELD_SPECS so the OpenAPI document always matches the engine."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from ..profile import FIELD_SPECS


def _profile_model() -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for spec in FIELD_SPECS:
        if spec.kind == "enum":
            typ = Literal[tuple(spec.choices)]  # type: ignore[valid-type]
        elif spec.kind == "int":
            typ = int
        elif spec.kind == "float":
            typ = float
        elif spec.kind == "bool":
            typ = bool
        else:
            typ = str
        kwargs: dict[str, Any] = {"description": spec.description}
        if spec.minimum is not None:
            kwargs["ge"] = spec.minimum
        if spec.maximum is not None:
            kwargs["le"] = spec.maximum
        fields[spec.name] = (typ | None, Field(default=None, **kwargs))
    for extra, desc in (
        ("domains", "Names of the distinct domains/skill areas (used to name specialists)."),
        ("sources", "Names of the knowledge sources (used to name research workers)."),
        ("tools", "Tool names (shown in the plan)."),
        ("subtasks", "Names of independent sub-tasks (used to name workers)."),
        ("sections", "Names of independent sections for code-defined fan-out."),
    ):
        fields[extra] = (list[str] | None, Field(default=None, description=desc))
    return create_model("WorkloadProfileIn", __config__=ConfigDict(extra="allow"), **fields)


WorkloadProfileIn = _profile_model()


class RecommendRequest(BaseModel):
    profile: WorkloadProfileIn = Field(..., description="Workload profile. Omitted fields take engine defaults.")  # type: ignore[valid-type]
    include_markdown: bool = Field(True, description="Include the full Markdown report in the response.")


class DeliverableRequest(RecommendRequest):
    scan: dict[str, Any] | None = Field(None, description="The `scan` object returned by a previous /api/v1/scan call, to include scan findings in the document.")
    framework: Literal["langgraph"] = Field("langgraph", description="Skeleton framework (skeleton endpoint only).")


class ScanRequest(BaseModel):
    path: str | None = Field(None, description="Server-side directory to scan. Must be under one of VGSELECT_SCAN_ROOTS.")
    git_url: str | None = Field(None, description="Git URL to clone (shallow) and scan. Requires VGSELECT_ALLOW_GIT_CLONE=1.")
    overrides: WorkloadProfileIn | None = Field(None, description="Profile fields that override scan inferences.")  # type: ignore[valid-type]
    recommend: bool = Field(True, description="Also run the recommender on the merged profile.")
    include_markdown: bool = True


class DescribeRequest(BaseModel):
    text: str = Field(..., min_length=10, description="Prose description of the application.")
    model: str = Field("claude-opus-5", description="Claude model used to infer the profile.")
    overrides: WorkloadProfileIn | None = None  # type: ignore[valid-type]
    include_markdown: bool = True


class EstimateOut(BaseModel):
    latency_s: float
    cost_usd: float
    llm_calls: int
    total_tokens: float
    token_multiplier: float
    assumptions: list[str]


class SignalOut(BaseModel):
    rule_id: str
    topology_id: str
    delta: float
    rationale: str
    citation: str


class CandidateOut(BaseModel):
    topology: str
    name: str
    family: str
    score: float
    fit: float
    quality_proxy: float
    latency_adj: float
    cost_adj: float
    latency_verdict: str
    viable: bool
    infeasible_reason: str
    estimate: EstimateOut
    signals: list[SignalOut]


class ComponentOut(BaseModel):
    id: str
    name: str
    role: str
    tier: str
    effort: str
    tools: str
    parallel_group: str | None
    notes: list[str]
    model_id: str


class EdgeOut(BaseModel):
    src: str
    dst: str
    label: str


class AugmentationOut(BaseModel):
    id: str
    title: str
    why: str
    citation: str


class PlanOut(BaseModel):
    topology: str
    components: list[ComponentOut]
    edges: list[EdgeOut]
    augmentations: list[AugmentationOut]
    briefing_rules: list[str]


class RecommendationOut(BaseModel):
    product: str
    version: str
    profile: dict[str, Any]
    headline: str
    primary: str
    candidates: list[CandidateOut]
    frontier: list[str]
    fastest_viable: str | None
    most_accurate: str | None
    plan: PlanOut
    mermaid: str
    svg: str = Field("", description="Standalone SVG rendering of the plan (no external dependencies).")
    scan: dict[str, Any] | None = None
    report_markdown: str | None = None


class ScanOut(BaseModel):
    scan: dict[str, Any]
    profile: dict[str, Any] = Field(..., description="Merged profile (scan inferences + overrides) that was recommended on.")
    recommendation: RecommendationOut | None = None


class HealthOut(BaseModel):
    status: str
    product: str
    version: str
    scan_roots: list[str]
    git_clone_enabled: bool
    describe_enabled: bool
    pdf_enabled: bool = True
