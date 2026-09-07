# Case study 3: Account balances and cost basis assistant

**Business context.** Clients ask, in the app's chat, questions such as "What
is my total balance across accounts?", "What is the cost basis of my index fund
in the taxable account?", "How much did I contribute this year?" and "Why did my
balance drop yesterday?". Every number must come from the books and records
systems; the assistant explains, it never estimates.

**What the application does today.** A single agent with six deterministic
account tools, a FAQ knowledge base for explanations, and a Redis-backed
conversation memory, served behind a FastAPI websocket. It works, but latency
is 6-9 seconds and the team is asked to cut model spend and to keep all client
data on infrastructure cleared for restricted data.

**Constraints the code cannot see.** Answers within 5 seconds. Numbers must be
exactly right (accuracy 5), but every number is verifiable against the API
(strong verifiability). Account data is restricted. Volume is 200,000 requests a
day, so cost dominates. Conversations are multi-turn.

**Artistic liberty.** The firm has an on-premises open-weights model cleared for
restricted data, registered in the case-study catalog; the cloud models are not
cleared for this data class. A measured single-agent baseline on an internal eval
is 88%.
