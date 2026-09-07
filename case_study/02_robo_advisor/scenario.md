# Case study 2: Robo-advisor

**Business context.** A digital advice service for retail clients. In a chat,
the client asks questions such as "Should I move my emergency fund into the
bond ladder?" or "How much can I put into my retirement account this year?"
The service must answer within the firm's advice methodology, cite policy, use
the client's actual portfolio, and never give advice a human adviser would not
be allowed to give.

**What the application does today.** One large prompt with the methodology,
several policy documents and a dozen tools: portfolio analytics, risk scoring,
tax-lot lookups, contribution-limit rules, product catalog search, market data,
plus three knowledge bases (methodology, policy, product). A compliance review
model call runs on every answer. Latency is 20-40 seconds and the prompt is
hard to maintain; the team suspects it should be split.

**Constraints the code cannot see.** Answers should arrive within about 15
seconds. Errors are very costly (unsuitable advice). Conversations are
multi-turn. Client data is confidential. A human adviser reviews flagged
answers. Volume is ~8,000 conversations a day.

**Artistic liberty.** Four advice domains (planning, tax, risk, products), a
suitability rules engine as a deterministic API, and a written eval rubric
scored by compliance; single-prompt baseline scores 61% on it.
