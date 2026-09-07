## Repository scan: `/Users/saxena/Desktop/ClaudeCode_GIT/AgentTopologyBuilder/case_study/02_robo_advisor`

- Files scanned: 7; languages: python (2)
- Frameworks/SDKs: anthropic-sdk, langgraph
- Tools found: 10 (contribution_limits, create_proposal, get_portfolio, market_data, risk_score, search_methodology, search_policy, search_products, suitability_check, tax_lots)
- Knowledge sources: elasticsearch
- Side effects: external-post (irreversible)
- Current topology (as implemented): **evaluator_optimizer** - Generator with an evaluator/critic and iteration cap.

| Inferred field | Value | Confidence | Reason |
|---|---|---|---|
| tool_count | 10 | 80% | 10 tool definitions found (decorators, schemas, MCP tools, OpenAPI operations). |
| tool_calls_per_task | 6 | 30% | Rough: 10 tools and 0 tool-handling call sites; verify against traces. |
| tool_dependency | sequential | 40% | No concurrency primitives around tool calls. |
| tool_side_effects | irreversible | 70% | Side-effecting integrations: external-post (irreversible) |
| knowledge_sources | 1 | 60% | Retrieval integrations: elasticsearch |
| retrieval_depth | multi_hop | 50% | Derived from sources (1) and whether a loop can issue follow-up queries. |
| context_tokens_per_task | 23000 | 30% | Rough function of sources and tools; replace with measured input tokens per request. |
| scope_breadth | 1 | 40% | 0 file(s) define system prompts/instructions; routing/handoffs raise this. |
| parallel_subtasks | 1 | 40% | Single tool loop. |
| steps_predictable | False | 60% | The model chooses steps at run time. |
| task_complexity | complex | 40% | Tool loop with 10 tools. |
| latency_budget_s | 8.0 | 40% | Request/response serving implies an interactive budget. |
| interaction | multi_turn | 40% | Serving surface and memory usage. |
| verifiability | none | 30% | No tests, evals or schemas found. |
| human_in_loop | True | 60% | Approval/confirmation logic present. |
| error_recoverability | hard | 50% | Irreversible integrations present. |
| accuracy_priority | 4 | 40% | Irreversible actions raise the cost of errors. |
| tool_overlap | True | 50% | Similarly named tools: search_methodology, search_policy, search_products |

Evidence (first hits per category):

- **frameworks**: anthropic-sdk @ `app/advisor.py:2`; anthropic-sdk @ `app/advisor.py:10`; langgraph @ `app/advisor.py:4`; anthropic-sdk @ `app/tools.py:3`
- **agent_patterns**: tool runner @ `app/advisor.py:23`; tool runner @ `app/advisor.py:27`; evaluator loop @ `app/advisor.py:1`; evaluator loop @ `app/advisor.py:14`
- **serving**: http-api @ `app/advisor.py:9`
- **quality**: human-approval @ `app/advisor.py:34`; memory @ `app/advisor.py:4`
- **tools**: python decorator tool @ `app/tools.py:9`; python decorator tool @ `app/tools.py:15`; python decorator tool @ `app/tools.py:21`; python decorator tool @ `app/tools.py:27`; python decorator tool @ `app/tools.py:33`
- **retrieval**: elasticsearch @ `app/tools.py:4`; elasticsearch @ `app/tools.py:6`
- **side_effects**: external-post (irreversible) @ `app/tools.py:36`; external-post (irreversible) @ `app/tools.py:66`
