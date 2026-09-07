"""Smoke tests that need no API key: the graph compiles and exposes the expected nodes."""

from app.graph import build_graph


def test_graph_compiles():
    g = build_graph()
    nodes = set(g.get_graph().nodes)
    assert "__start__" in nodes and "__end__" in nodes
    assert len(nodes) >= 3
