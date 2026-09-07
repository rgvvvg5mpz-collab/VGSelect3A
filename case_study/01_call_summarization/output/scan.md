## Repository scan: `/Users/saxena/Desktop/ClaudeCode_GIT/AgentTopologyBuilder/case_study/01_call_summarization`

- Files scanned: 8; languages: python (3)
- Frameworks/SDKs: anthropic-sdk
- Tools found: 0
- Knowledge sources: none detected
- Side effects: external-post (irreversible), ticket/crm (irreversible)
- Current topology (as implemented): **single_call** - Model calls without tools or loops.

| Inferred field | Value | Confidence | Reason |
|---|---|---|---|
| tool_count | 0 | 50% | No tool definitions found. |
| tool_calls_per_task | 0 | 60% | No tools found. |
| tool_side_effects | irreversible | 70% | Side-effecting integrations: external-post (irreversible), ticket/crm (irreversible) |
| knowledge_sources | 0 | 50% | No retrieval integrations found. |
| retrieval_depth | none | 50% | Derived from sources (0) and whether a loop can issue follow-up queries. |
| context_tokens_per_task | 2000 | 30% | Rough function of sources and tools; replace with measured input tokens per request. |
| scope_breadth | 1 | 40% | 1 file(s) define system prompts/instructions; routing/handoffs raise this. |
| parallel_subtasks | 1 | 30% | No orchestration detected. |
| steps_predictable | True | 50% | No run-time planning detected. |
| task_complexity | simple | 30% | Defaulted from tool presence. |
| latency_budget_s | 3600.0 | 50% | Batch/cron execution: minutes to hours are acceptable. |
| interaction | single_turn | 50% | Batch jobs are single-shot. |
| verifiability | partial | 50% | Tests or schema validation present. |
| error_recoverability | hard | 50% | Irreversible integrations present. |
| accuracy_priority | 4 | 40% | Irreversible actions raise the cost of errors. |

Evidence (first hits per category):

- **side_effects**: external-post (irreversible) @ `app/crm.py:10`; ticket/crm (irreversible) @ `app/crm.py:1`; ticket/crm (irreversible) @ `app/crm.py:3`
- **frameworks**: anthropic-sdk @ `app/pipeline.py:4`; anthropic-sdk @ `app/pipeline.py:11`
- **serving**: batch/cron @ `app/pipeline.py:5`
- **quality**: structured-output @ `app/pipeline.py:31`
