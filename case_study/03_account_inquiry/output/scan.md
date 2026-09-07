## Repository scan: `/Users/saxena/Desktop/ClaudeCode_GIT/AgentTopologyBuilder/case_study/03_account_inquiry`

- Files scanned: 7; languages: python (3)
- Frameworks/SDKs: anthropic-sdk
- Tools found: 7 (explain_balance_change, faq_lookup, get_balances, get_contributions_ytd, get_cost_basis, get_positions, get_transactions)
- Knowledge sources: pgvector, sql
- Side effects: none detected
- Current topology (as implemented): **single_agent** - A tool-use loop (or tool definitions) with no delegation.

| Inferred field | Value | Confidence | Reason |
|---|---|---|---|
| tool_count | 7 | 80% | 7 tool definitions found (decorators, schemas, MCP tools, OpenAPI operations). |
| tool_calls_per_task | 4 | 30% | Rough: 7 tools and 0 tool-handling call sites; verify against traces. |
| tool_dependency | sequential | 40% | No concurrency primitives around tool calls. |
| tool_side_effects | read_only | 60% | No write/side-effect integrations detected. |
| knowledge_sources | 2 | 60% | Retrieval integrations: pgvector, sql |
| retrieval_depth | multi_hop | 50% | Derived from sources (2) and whether a loop can issue follow-up queries. |
| context_tokens_per_task | 24500 | 30% | Rough function of sources and tools; replace with measured input tokens per request. |
| scope_breadth | 1 | 40% | 1 file(s) define system prompts/instructions; routing/handoffs raise this. |
| parallel_subtasks | 1 | 40% | Single tool loop. |
| steps_predictable | False | 60% | The model chooses steps at run time. |
| task_complexity | moderate | 40% | Tool loop with 7 tools. |
| latency_budget_s | 10.0 | 40% | Request/response serving implies an interactive budget. |
| interaction | single_turn | 40% | Serving surface and memory usage. |
| verifiability | partial | 50% | Tests or schema validation present. |
| tool_overlap | True | 50% | Similarly named tools: get_balances, get_contributions_ytd, get_cost_basis, get_positions, get_transactions |

Evidence (first hits per category):

- **frameworks**: anthropic-sdk @ `app/assistant.py:2`; anthropic-sdk @ `app/assistant.py:10`; anthropic-sdk @ `app/tools.py:3`
- **agent_patterns**: tool runner @ `app/assistant.py:24`; tool runner @ `app/assistant.py:28`
- **serving**: http-api @ `app/assistant.py:9`; websocket/streaming @ `app/assistant.py:1`
- **tools**: python decorator tool @ `app/tools.py:7`; python decorator tool @ `app/tools.py:13`; python decorator tool @ `app/tools.py:19`; python decorator tool @ `app/tools.py:25`; python decorator tool @ `app/tools.py:31`
- **retrieval**: pgvector @ `app/tools.py:4`; pgvector @ `app/tools.py:45`; sql @ `app/tools.py:4`
- **quality**: tests @ `tests/test_numbers_match.py:1`
