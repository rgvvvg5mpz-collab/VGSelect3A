"""Repository scanner: infer as much of a WorkloadProfile as the code reveals.

Pure standard library. Walks the tree, reads source and dependency files,
and produces:
  * evidence   - file:line hits grouped by category (frameworks, tools,
                 retrieval, side effects, agent loops, evals, serving)
  * inferred   - profile fields with a confidence (0..1) and a reason
  * current    - the topology the code appears to implement today
The inferred fields are merged under any user-supplied values; nothing here
is authoritative. Every inference is shown in the report so it can be
corrected.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
             "dist", "build", "target", ".idea", ".vscode", ".next", ".turbo", "coverage", "site-packages", ".tox", ".cache", "vendor"}
SOURCE_EXT = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
              ".go": "go", ".java": "java", ".kt": "kotlin", ".rb": "ruby", ".cs": "csharp", ".php": "php", ".rs": "rust", ".scala": "scala"}
CONFIG_FILES = {"requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "package.json",
                "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile", "composer.json", "environment.yml"}
DOC_EXT = {".md", ".txt", ".yaml", ".yml", ".json", ".toml"}
MAX_FILE_BYTES = 1_000_000
MAX_FILES = 20_000


@dataclass
class Evidence:
    category: str
    label: str
    path: str
    line: int
    snippet: str


@dataclass
class Inference:
    field: str
    value: Any
    confidence: float
    reason: str


@dataclass
class ScanResult:
    root: str
    files_scanned: int
    languages: dict[str, int]
    frameworks: list[str]
    tools: list[str]
    knowledge_sources: list[str]
    side_effects: list[str]
    current_topology: str
    current_topology_reason: str
    evidence: list[Evidence]
    inferred: list[Inference]
    warnings: list[str] = field(default_factory=list)

    def inferred_profile(self) -> dict[str, Any]:
        return {i.field: i.value for i in self.inferred}

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["inferred_profile"] = self.inferred_profile()
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScanResult":
        return cls(
            root=d.get("root", ""), files_scanned=int(d.get("files_scanned", 0)), languages=dict(d.get("languages", {})),
            frameworks=list(d.get("frameworks", [])), tools=list(d.get("tools", [])), knowledge_sources=list(d.get("knowledge_sources", [])),
            side_effects=list(d.get("side_effects", [])), current_topology=d.get("current_topology", "none"),
            current_topology_reason=d.get("current_topology_reason", ""),
            evidence=[Evidence(**{k: e[k] for k in ("category", "label", "path", "line", "snippet")}) for e in d.get("evidence", [])],
            inferred=[Inference(**{k: i[k] for k in ("field", "value", "confidence", "reason")}) for i in d.get("inferred", [])],
            warnings=list(d.get("warnings", [])),
        )


# ------------------------------------------------------------------ pattern tables

FRAMEWORK_PATTERNS: dict[str, list[str]] = {
    "anthropic-sdk": [r"\bimport anthropic\b", r"from anthropic\b", r"@anthropic-ai/sdk", r"anthropic\.Anthropic\(", r"new Anthropic\("],
    "claude-agent-sdk": [r"claude[-_]agent[-_]sdk", r"@anthropic-ai/claude-agent-sdk"],
    "managed-agents": [r"client\.beta\.agents\.", r"beta\.sessions\.create", r"agent_toolset_20260401"],
    "openai-sdk": [r"\bimport openai\b", r"from openai\b", r"require\(['\"]openai['\"]\)", r"from ['\"]openai['\"]"],
    "openai-agents": [r"from agents import", r"@openai/agents", r"\bRunner\.run\(", r"handoffs=\["],
    "langchain": [r"\blangchain\b", r"@langchain/"],
    "langgraph": [r"\blanggraph\b", r"StateGraph\(", r"create_react_agent", r"create_supervisor"],
    "llamaindex": [r"llama_index", r"llamaindex"],
    "crewai": [r"\bcrewai\b", r"\bCrew\("],
    "autogen": [r"\bautogen\b", r"GroupChat\(", r"agent_framework"],
    "semantic-kernel": [r"semantic_kernel", r"Microsoft\.SemanticKernel"],
    "google-adk": [r"google\.adk", r"SequentialAgent\(", r"ParallelAgent\(", r"LlmAgent\("],
    "vercel-ai": [r"from ['\"]ai['\"]", r"@ai-sdk/"],
    "mcp": [r"\bmcp\b", r"FastMCP\(", r"@modelcontextprotocol/", r"mcp_servers"],
    "haystack": [r"\bhaystack\b"],
    "dspy": [r"\bdspy\b"],
}

TOOL_DEF_PATTERNS: list[tuple[str, str]] = [
    # (regex with a capture group for the tool name, label)
    (r"@(?:beta_)?tool(?:\([^)]*\))?\s*\n\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", "python decorator tool"),
    (r"@mcp\.tool(?:\([^)]*\))?\s*\n\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", "MCP tool"),
    (r"server\.tool\(\s*['\"]([\w.-]+)['\"]", "MCP tool (ts)"),
    (r"['\"]name['\"]\s*:\s*['\"]([\w.-]+)['\"]\s*,\s*\n?\s*['\"](?:description|input_schema|parameters)['\"]", "tool schema"),
    (r"name\s*:\s*['\"]([\w.-]+)['\"]\s*,\s*\n?\s*(?:description|inputSchema|input_schema|parameters)\s*:", "tool schema (ts)"),
    (r"(?:betaZodTool|betaTool|tool)\(\s*\{\s*name\s*:\s*['\"]([\w.-]+)['\"]", "zod tool"),
    (r"StructuredTool\.from_function\([^)]*name\s*=\s*['\"]([\w.-]+)['\"]", "langchain tool"),
    (r"Tool\(\s*name\s*=\s*['\"]([\w.-]+)['\"]", "langchain tool"),
    (r"FunctionTool\(\s*(?:func\s*=\s*)?([A-Za-z_]\w*)", "ADK function tool"),
    (r"\"type\"\s*:\s*\"function\"\s*,\s*\"function\"\s*:\s*\{\s*\"name\"\s*:\s*\"([\w.-]+)\"", "openai function"),
    (r"type\s*:\s*['\"]function['\"]\s*,\s*function\s*:\s*\{\s*name\s*:\s*['\"]([\w.-]+)['\"]", "openai function (ts)"),
    (r"\{\s*\"type\"\s*:\s*\"(web_search|web_fetch|code_execution|computer|bash|text_editor|memory)[\w_]*\"", "anthropic server/client tool"),
]

RETRIEVAL_PATTERNS: dict[str, list[str]] = {
    "pinecone": [r"\bpinecone\b"], "weaviate": [r"\bweaviate\b"], "chroma": [r"\bchromadb\b", r"\bChroma\b"],
    "qdrant": [r"\bqdrant\b"], "pgvector": [r"\bpgvector\b", r"\bvector\(\d+\)"], "faiss": [r"\bfaiss\b"],
    "milvus": [r"\bmilvus\b"], "elasticsearch": [r"\belasticsearch\b", r"\bopensearch\b"], "azure-search": [r"azure\.search", r"SearchClient\("],
    "vertex-search": [r"discoveryengine", r"vertexai.*rag"], "bedrock-kb": [r"retrieve_and_generate", r"bedrock-agent-runtime"],
    "embeddings": [r"embeddings?\.create\(", r"embed_documents", r"OpenAIEmbeddings|VoyageEmbeddings|HuggingFaceEmbeddings", r"text-embedding-"],
    "retriever": [r"as_retriever\(", r"\bRetriever\b", r"similarity_search", r"vector_store", r"VectorStore"],
    "web-search": [r"web_search", r"tavily", r"serpapi", r"bing.*search", r"googlesearch"],
    "sql": [r"\bSELECT\s+.+\s+FROM\b", r"sqlalchemy", r"psycopg", r"\bprisma\b", r"knex\(", r"\bsqlite3\b"],
    "graph-db": [r"\bneo4j\b", r"\bcypher\b"],
    "files-api": [r"client\.files\.upload", r"\"file_id\""],
}

SIDE_EFFECT_PATTERNS: dict[str, tuple[str, list[str]]] = {
    # name: (severity, patterns)   severity in read_only|reversible_writes|irreversible
    "email/sms": ("irreversible", [r"\bsmtplib\b", r"\bsendgrid\b", r"\btwilio\b", r"\bnodemailer\b", r"send_email|sendEmail|send_sms|sendSms", r"\bmailgun\b", r"\bses\.send"]),
    "payments": ("irreversible", [r"\bstripe\b", r"\bbraintree\b", r"\bpaypal\b", r"charge\(|refund\(|payout\(", r"issue_refund|process_payment"]),
    "external-post": ("irreversible", [r"requests\.(post|put|delete|patch)\(", r"httpx\.(post|put|delete|patch)\(", r"fetch\([^)]*method\s*:\s*['\"](POST|PUT|DELETE|PATCH)", r"axios\.(post|put|delete|patch)\("]),
    "chat-post": ("irreversible", [r"chat_postMessage", r"slack_sdk", r"discord\.py|discord\.js", r"telegram"]),
    "db-write": ("reversible_writes", [r"\bINSERT\s+INTO\b", r"\bUPDATE\s+\w+\s+SET\b", r"\bDELETE\s+FROM\b", r"\.save\(\)", r"session\.commit\(", r"\.insert_one\(|\.update_one\(|\.delete_one\(", r"prisma\.\w+\.(create|update|delete)\("]),
    "file-write": ("reversible_writes", [r"open\([^)]*['\"]w['\"]", r"\.write_text\(", r"fs\.writeFile", r"shutil\.rmtree|os\.remove\(|os\.unlink\(|fs\.rm\(|fs\.unlink"]),
    "shell": ("reversible_writes", [r"subprocess\.(run|Popen|call)", r"child_process", r"os\.system\(", r"\"type\"\s*:\s*\"bash"]),
    "deploy/infra": ("irreversible", [r"\bboto3\b", r"kubernetes|k8s", r"terraform", r"gcloud|aws\s+\w+\s+(create|delete)"]),
    "ticket/crm": ("irreversible", [r"\bjira\b", r"zendesk", r"salesforce|simple_salesforce", r"hubspot", r"create_ticket|open_ticket"]),
}

AGENT_LOOP_PATTERNS: dict[str, list[str]] = {
    "manual tool loop": [r"stop_reason\s*==\s*['\"]tool_use['\"]", r"while\s+.*tool_calls", r"finish_reason\s*==\s*['\"]tool_calls['\"]"],
    "tool runner": [r"tool_runner\(", r"toolRunner\(", r"\.RunToCompletion\(", r"until_done\("],
    "langgraph graph": [r"StateGraph\(", r"add_conditional_edges", r"create_react_agent"],
    "supervisor/orchestrator": [r"create_supervisor", r"supervisor", r"orchestrator", r"\bcoordinator\b", r"multiagent\s*=", r"\{\s*['\"]type['\"]\s*:\s*['\"]self['\"]"],
    "subagents": [r"subagent", r"sub_agents\s*=", r"spawn_(agent|worker)", r"Agent\(.*\)\s*$", r"send_to_agent", r"agents_as_tools|as_tool\("],
    "handoffs": [r"handoff", r"transfer_to_", r"Handoff\("],
    "router": [r"\brouter\b", r"classify_intent|classify_query|route_query|intent_classif"],
    "parallel fan-out": [r"asyncio\.gather\(", r"Promise\.all\(", r"ParallelAgent\(", r"ThreadPoolExecutor", r"\bSend\("],
    "evaluator loop": [r"evaluator|critic|reviewer|grader|judge", r"max_iterations|max_retries\s*=\s*\d"],
    "prompt chain": [r"SequentialAgent\(", r"\bchain\b.*\|", r"RunnableSequence", r"pipeline\("],
}

SERVING_PATTERNS: dict[str, list[str]] = {
    "http-api": [r"\bFastAPI\(", r"\bFlask\(", r"express\(\)", r"@app\.(get|post)\(", r"router\.(get|post)\(", r"@RestController", r"http\.HandleFunc"],
    "websocket/streaming": [r"websocket", r"\.stream\(", r"stream=True", r"text/event-stream", r"StreamingResponse"],
    "batch/cron": [r"\bcelery\b", r"\bcron\b", r"schedule\.", r"APScheduler", r"messages\.batches\.", r"@task"],
    "chat-ui": [r"streamlit", r"gradio", r"chainlit", r"useChat\("],
    "cli": [r"argparse", r"\bclick\b", r"\btyper\b", r"commander"],
}

QUALITY_PATTERNS: dict[str, list[str]] = {
    "tests": [r"^\s*def test_", r"\bpytest\b", r"describe\(['\"]", r"\bit\(['\"]", r"@Test\b"],
    "evals": [r"\beval(s|uation)?[_/]", r"promptfoo", r"\bragas\b", r"deepeval", r"braintrust", r"langsmith", r"llm[_-]judge|LLMJudge"],
    "structured-output": [r"output_config", r"response_format", r"json_schema", r"\.parse\(", r"withStructuredOutput|with_structured_output", r"strict\s*[:=]\s*[Tt]rue"],
    "prompt-caching": [r"cache_control", r"ephemeral"],
    "human-approval": [r"human[_ -]?in[_ -]?the[_ -]?loop|approval|approve\(|confirm\(|requires_confirmation|interrupt\("],
    "memory": [r"memory_20250818", r"ConversationBufferMemory", r"/memories", r"MemorySaver", r"checkpointer"],
    "compaction/context": [r"compact_20260112", r"context_management", r"clear_tool_uses", r"summarize_history|trim_messages"],
}


# ------------------------------------------------------------------ scanning

def iter_files(root: Path) -> Iterable[Path]:
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")] if Path(dirpath) != root else [d for d in dirnames if d not in SKIP_DIRS and (d == ".claude" or not d.startswith("."))]
        for fn in filenames:
            p = Path(dirpath) / fn
            ext = p.suffix.lower()
            if ext in SOURCE_EXT or ext in DOC_EXT or fn in CONFIG_FILES:
                count += 1
                if count > MAX_FILES:
                    return
                yield p


def _read(p: Path) -> str | None:
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return None
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _hits(text: str, patterns: list[str], flags: int = re.IGNORECASE | re.MULTILINE) -> list[tuple[int, str]]:
    out = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags):
            line_no = text.count("\n", 0, m.start()) + 1
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.end())
            snippet = text[start:end if end != -1 else len(text)].strip()[:160]
            out.append((line_no, snippet))
    return out


def scan_repository(root: str | os.PathLike, max_evidence_per_label: int = 5) -> ScanResult:
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(str(root_path))

    languages: Counter[str] = Counter()
    evidence: list[Evidence] = []
    per_label: Counter[str] = Counter()
    frameworks: set[str] = set()
    tools: dict[str, str] = {}
    sources: set[str] = set()
    side_effects: dict[str, str] = {}
    loop_hits: Counter[str] = Counter()
    serving: set[str] = set()
    quality: set[str] = set()
    warnings: list[str] = []
    files_scanned = 0
    long_prompts = 0
    openapi_ops = 0
    system_prompt_files: set[str] = set()
    total_tool_call_sites = 0
    dep_text = ""

    def add(cat: str, label: str, p: Path, line: int, snip: str) -> None:
        key = f"{cat}:{label}"
        per_label[key] += 1
        if per_label[key] <= max_evidence_per_label:
            evidence.append(Evidence(cat, label, str(p.relative_to(root_path)), line, snip))

    for p in iter_files(root_path):
        text = _read(p)
        if text is None:
            continue
        files_scanned += 1
        ext = p.suffix.lower()
        if ext in SOURCE_EXT:
            languages[SOURCE_EXT[ext]] += 1
        rel = p.relative_to(root_path)
        if p.name in CONFIG_FILES:
            dep_text += "\n" + text

        # OpenAPI specs count as candidate tools
        if ext in (".json", ".yaml", ".yml") and re.search(r"^\s*\"?openapi\"?\s*[:=]\s*\"?3", text, re.MULTILINE):
            ops = len(re.findall(r"^\s{4,8}\"?(get|post|put|delete|patch)\"?\s*:", text, re.MULTILINE | re.IGNORECASE))
            openapi_ops += ops
            add("tools", "openapi spec", p, 1, f"OpenAPI document with ~{ops} operations")
            continue

        if ext in (".md", ".txt"):
            continue  # prose is not evidence
        if ext not in SOURCE_EXT:
            # config files: framework mentions only (dependency declarations)
            if p.name in CONFIG_FILES or ext in (".toml", ".yaml", ".yml"):
                for fw, pats in FRAMEWORK_PATTERNS.items():
                    for line, snip in _hits(text, pats)[:1]:
                        frameworks.add(fw); add("frameworks", fw, p, line, snip)
            continue

        for fw, pats in FRAMEWORK_PATTERNS.items():
            h = _hits(text, pats)
            if h:
                frameworks.add(fw)
                for line, snip in h[:2]:
                    add("frameworks", fw, p, line, snip)
        for pat, label in TOOL_DEF_PATTERNS:
            for m in re.finditer(pat, text, re.MULTILINE):
                name = m.group(1)
                if name and name not in tools:
                    tools[name] = label
                    line = text.count("\n", 0, m.start()) + 1
                    add("tools", label, p, line, name)
        total_tool_call_sites += len(re.findall(r"tool_use|tool_calls|toolCalls|tool_result|function_call", text))
        for src, pats in RETRIEVAL_PATTERNS.items():
            h = _hits(text, pats)
            if h:
                sources.add(src)
                for line, snip in h[:2]:
                    add("retrieval", src, p, line, snip)
        for name, (sev, pats) in SIDE_EFFECT_PATTERNS.items():
            h = _hits(text, pats)
            if h:
                side_effects[name] = sev
                for line, snip in h[:2]:
                    add("side_effects", f"{name} ({sev})", p, line, snip)
        for name, pats in AGENT_LOOP_PATTERNS.items():
            h = _hits(text, pats)
            if h:
                loop_hits[name] += len(h)
                for line, snip in h[:2]:
                    add("agent_patterns", name, p, line, snip)
        for name, pats in SERVING_PATTERNS.items():
            h = _hits(text, pats)
            if h:
                serving.add(name)
                for line, snip in h[:1]:
                    add("serving", name, p, line, snip)
        for name, pats in QUALITY_PATTERNS.items():
            h = _hits(text, pats)
            if h:
                quality.add(name)
                for line, snip in h[:1]:
                    add("quality", name, p, line, snip)
        # long prompt literals ~ separate roles/agents
        for m in re.finditer(r"(?:system|SYSTEM|instructions|prompt)[\w]*\s*[:=]\s*[fr]?(?:\"\"\"|'''|`)", text):
            long_prompts += 1
            system_prompt_files.add(str(rel))

    # dependency file mentions (frameworks only)
    for fw, pats in FRAMEWORK_PATTERNS.items():
        if fw not in frameworks and any(re.search(p_, dep_text, re.IGNORECASE) for p_ in pats):
            frameworks.add(fw)

    if files_scanned == 0:
        warnings.append("No source, config or doc files found under the root.")
    if not frameworks:
        warnings.append("No LLM SDK or agent framework detected; the code may not call a model yet, or uses one not in the pattern table.")

    tool_names = sorted(tools)
    tool_count = len(tool_names) + openapi_ops
    current, reason = _current_topology(loop_hits, tool_count, frameworks)
    inferred = _infer(languages, frameworks, tool_count, tool_names, sources, side_effects, loop_hits, serving, quality, long_prompts, len(system_prompt_files), total_tool_call_sites)

    return ScanResult(
        root=str(root_path), files_scanned=files_scanned, languages=dict(languages.most_common()),
        frameworks=sorted(frameworks), tools=tool_names + ([f"~{openapi_ops} OpenAPI operations"] if openapi_ops else []),
        knowledge_sources=sorted(sources), side_effects=sorted(f"{k} ({v})" for k, v in side_effects.items()),
        current_topology=current, current_topology_reason=reason, evidence=evidence, inferred=inferred, warnings=warnings,
    )


def _current_topology(loop_hits: Counter, tool_count: int, frameworks: set[str]) -> tuple[str, str]:
    if not loop_hits and not frameworks:
        return "none", "No model calls or agent loops detected."
    if loop_hits.get("supervisor/orchestrator") or loop_hits.get("subagents"):
        return "orchestrator_workers", "Orchestrator/supervisor or subagent spawning patterns present."
    if loop_hits.get("handoffs"):
        return "handoff_network", "Handoff/transfer patterns present."
    if loop_hits.get("router") and (loop_hits.get("manual tool loop") or loop_hits.get("tool runner") or loop_hits.get("langgraph graph")):
        return "router", "Intent routing in front of agent handlers."
    if loop_hits.get("evaluator loop") and (loop_hits.get("manual tool loop") or loop_hits.get("tool runner")):
        return "evaluator_optimizer", "Generator with an evaluator/critic and iteration cap."
    if loop_hits.get("parallel fan-out") and not (loop_hits.get("manual tool loop") or loop_hits.get("tool runner")):
        return "parallel_sectioning", "Concurrent fan-out over model calls without a tool loop."
    if loop_hits.get("prompt chain"):
        return "prompt_chain", "Sequential chain of model steps."
    if loop_hits.get("manual tool loop") or loop_hits.get("tool runner") or loop_hits.get("langgraph graph") or tool_count > 0:
        return "single_agent", "A tool-use loop (or tool definitions) with no delegation."
    return "single_call", "Model calls without tools or loops."


def _infer(languages, frameworks, tool_count, tool_names, sources, side_effects, loop_hits, serving, quality, long_prompts, prompt_files, call_sites) -> list[Inference]:
    inf: list[Inference] = []
    add = lambda f, v, c, r: inf.append(Inference(f, v, round(c, 2), r))  # noqa: E731

    add("tool_count", int(tool_count), 0.8 if tool_count else 0.5, f"{tool_count} tool definitions found (decorators, schemas, MCP tools, OpenAPI operations)." if tool_count else "No tool definitions found.")
    if tool_count:
        est_calls = max(1, min(40, int(round(tool_count * 0.6 + call_sites * 0.2))))
        add("tool_calls_per_task", est_calls, 0.3, f"Rough: {tool_count} tools and {call_sites} tool-handling call sites; verify against traces.")
        dep = "independent" if loop_hits.get("parallel fan-out") else "sequential"
        add("tool_dependency", dep, 0.4, "Concurrent fan-out present." if dep == "independent" else "No concurrency primitives around tool calls.")
    else:
        add("tool_calls_per_task", 0, 0.6, "No tools found.")

    if side_effects:
        worst = "irreversible" if "irreversible" in side_effects.values() else "reversible_writes"
        add("tool_side_effects", worst, 0.7, "Side-effecting integrations: " + ", ".join(f"{k} ({v})" for k, v in side_effects.items()))
    else:
        add("tool_side_effects", "read_only", 0.6, "No write/side-effect integrations detected.")

    real_sources = [s for s in sources if s not in ("embeddings", "retriever")]
    n_sources = len(real_sources) if real_sources else (1 if sources else 0)
    add("knowledge_sources", n_sources, 0.6 if sources else 0.5, ("Retrieval integrations: " + ", ".join(sorted(sources))) if sources else "No retrieval integrations found.")
    if not sources:
        depth = "none"
    elif "web-search" in sources or n_sources >= 3:
        depth = "exhaustive" if n_sources >= 3 and loop_hits.get("subagents") else "multi_hop"
    elif loop_hits.get("manual tool loop") or loop_hits.get("tool runner") or loop_hits.get("langgraph graph"):
        depth = "multi_hop"
    else:
        depth = "single_lookup"
    add("retrieval_depth", depth, 0.5, f"Derived from sources ({n_sources}) and whether a loop can issue follow-up queries.")
    ctx = 2_000 + 6_000 * n_sources + 1_500 * min(tool_count, 20)
    if loop_hits.get("subagents"):
        ctx *= 4
    add("context_tokens_per_task", int(ctx), 0.3, "Rough function of sources and tools; replace with measured input tokens per request.")

    breadth = max(1, min(8, prompt_files if prompt_files else 1))
    if loop_hits.get("router") or loop_hits.get("handoffs"):
        breadth = max(breadth, 3)
    add("scope_breadth", breadth, 0.4, f"{prompt_files} file(s) define system prompts/instructions; routing/handoffs raise this.")

    if loop_hits.get("subagents") or loop_hits.get("supervisor/orchestrator"):
        add("parallel_subtasks", 4, 0.4, "Delegation patterns imply several independent sub-tasks.")
        add("steps_predictable", False, 0.6, "Dynamic delegation implies run-time planning.")
        add("task_complexity", "complex", 0.5, "Multi-agent code implies a complex task.")
    elif loop_hits.get("parallel fan-out"):
        add("parallel_subtasks", 3, 0.4, "Concurrent fan-out present.")
        add("steps_predictable", True, 0.5, "Fan-out is code-defined.")
        add("task_complexity", "moderate", 0.4, "Code-defined workflow.")
    elif loop_hits.get("manual tool loop") or loop_hits.get("tool runner") or loop_hits.get("langgraph graph"):
        add("parallel_subtasks", 1, 0.4, "Single tool loop.")
        add("steps_predictable", False, 0.6, "The model chooses steps at run time.")
        add("task_complexity", "complex" if tool_count >= 8 else "moderate", 0.4, f"Tool loop with {tool_count} tools.")
    elif loop_hits.get("prompt chain"):
        add("parallel_subtasks", 1, 0.4, "Sequential chain.")
        add("steps_predictable", True, 0.7, "Chain defined in code.")
        add("task_complexity", "moderate", 0.4, "Fixed multi-step chain.")
    else:
        add("parallel_subtasks", 1, 0.3, "No orchestration detected.")
        add("steps_predictable", True, 0.5, "No run-time planning detected.")
        add("task_complexity", "simple" if not tool_count else "moderate", 0.3, "Defaulted from tool presence.")

    if "http-api" in serving or "chat-ui" in serving:
        add("latency_budget_s", 10.0 if "websocket/streaming" in serving else 8.0, 0.4, "Request/response serving implies an interactive budget.")
        add("interaction", "multi_turn" if "chat-ui" in serving or "memory" in quality else "single_turn", 0.4, "Serving surface and memory usage.")
    elif "batch/cron" in serving:
        add("latency_budget_s", 3600.0, 0.5, "Batch/cron execution: minutes to hours are acceptable.")
        add("interaction", "single_turn", 0.5, "Batch jobs are single-shot.")
    elif "cli" in serving:
        add("latency_budget_s", 300.0, 0.3, "CLI tool: minutes-scale is tolerable.")
        add("interaction", "long_running" if loop_hits.get("manual tool loop") or loop_hits.get("tool runner") else "single_turn", 0.3, "CLI with a tool loop.")

    if "evals" in quality:
        add("verifiability", "strong", 0.6, "Eval harness present.")
    elif "tests" in quality or "structured-output" in quality:
        add("verifiability", "partial", 0.5, "Tests or schema validation present.")
    else:
        add("verifiability", "none", 0.3, "No tests, evals or schemas found.")
    if "human-approval" in quality:
        add("human_in_loop", True, 0.6, "Approval/confirmation logic present.")
    if any(v == "irreversible" for v in side_effects.values()):
        add("error_recoverability", "hard", 0.5, "Irreversible integrations present.")
        add("accuracy_priority", 4, 0.4, "Irreversible actions raise the cost of errors.")
    tools_overlap = _overlapping(tool_names)
    if tools_overlap:
        add("tool_overlap", True, 0.5, "Similarly named tools: " + ", ".join(tools_overlap[:6]))
    return inf


def _overlapping(names: list[str]) -> list[str]:
    """Tools whose names share a stem (search_docs / search_kb / search_web ...)."""
    stems: dict[str, list[str]] = defaultdict(list)
    for n in names:
        parts = re.split(r"[_\-.]|(?<=[a-z])(?=[A-Z])", n)
        if parts:
            stems[parts[0].lower()].append(n)
    return [n for grp in stems.values() if len(grp) >= 3 for n in grp]


# ------------------------------------------------------------------ merge

def merge_profile(scan: ScanResult, overrides: dict[str, Any] | None = None, min_confidence: float = 0.0) -> dict[str, Any]:
    """Scan inferences first, then user overrides win. Extras (tools, sources) are attached for naming."""
    data: dict[str, Any] = {i.field: i.value for i in scan.inferred if i.confidence >= min_confidence}
    data["tools"] = [t for t in scan.tools if not t.startswith("~")][:20]
    data["sources"] = scan.knowledge_sources
    data.setdefault("name", Path(scan.root).name)
    data.setdefault("description", f"Inferred from repository scan of {Path(scan.root).name} ({scan.files_scanned} files; frameworks: {', '.join(scan.frameworks) or 'none'}).")
    if overrides:
        data.update({k: v for k, v in overrides.items() if v is not None})
    return data


def scan_markdown(scan: ScanResult) -> str:
    out = [f"## Repository scan: `{scan.root}`\n"]
    out.append(f"- Files scanned: {scan.files_scanned}; languages: " + (", ".join(f"{k} ({v})" for k, v in scan.languages.items()) or "none"))
    out.append(f"- Frameworks/SDKs: {', '.join(scan.frameworks) or 'none detected'}")
    out.append(f"- Tools found: {len([t for t in scan.tools if not t.startswith('~')])}" + (f" ({', '.join(scan.tools[:12])}{' ...' if len(scan.tools) > 12 else ''})" if scan.tools else ""))
    out.append(f"- Knowledge sources: {', '.join(scan.knowledge_sources) or 'none detected'}")
    out.append(f"- Side effects: {', '.join(scan.side_effects) or 'none detected'}")
    out.append(f"- Current topology (as implemented): **{scan.current_topology}** - {scan.current_topology_reason}")
    for w in scan.warnings:
        out.append(f"- Warning: {w}")
    out.append("\n| Inferred field | Value | Confidence | Reason |\n|---|---|---|---|")
    for i in scan.inferred:
        out.append(f"| {i.field} | {i.value} | {i.confidence:.0%} | {i.reason} |")
    out.append("\nEvidence (first hits per category):\n")
    by_cat: dict[str, list[Evidence]] = defaultdict(list)
    for e in scan.evidence:
        by_cat[e.category].append(e)
    for cat, items in by_cat.items():
        out.append(f"- **{cat}**: " + "; ".join(f"{e.label} @ `{e.path}:{e.line}`" for e in items[:8]))
    out.append("")
    return "\n".join(out)
