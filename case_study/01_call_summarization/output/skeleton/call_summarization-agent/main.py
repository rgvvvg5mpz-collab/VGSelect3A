"""Run one request through the graph."""

import sys

from dotenv import load_dotenv

from app.config import RECURSION_LIMIT
from app.graph import build_graph

load_dotenv()

if __name__ == "__main__":
    request = " ".join(sys.argv[1:]) or "TODO: put a representative request here"
    graph = build_graph()
    result = graph.invoke({"request": request, "messages": []}, config={"recursion_limit": RECURSION_LIMIT})
    print(result.get("answer") or result)
