"""Graph state."""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class State(TypedDict, total=False):
    request: str
    messages: Annotated[list[AnyMessage], add_messages]
    answer: str
    route: str
