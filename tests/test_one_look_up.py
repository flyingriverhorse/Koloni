"""0.1.10, Knowledge and Memory one page and one tool: an agent offered recall and lookup is offered
one look-up tool, recall, which looks in what it holds - the project's memory and earlier turns where
its role has recall (never KOLONİ's read-only Reviewer), the pages of its role's knowledge where it
has lookup. lookup stays its old name for one release, and looks in those pages alone, as it did."""

import asyncio
from types import SimpleNamespace

import pytest

from app import knows
from app.agent import AgentRunner
from app.tools import LOOKUP_SCHEMA, RECALL_SCHEMA, ToolError


def _names(schemas):
    return [schema["function"]["name"] for schema in schemas]


def test_recall_and_lookup_offered_together_are_one_recall_with_a_topic():
    other = {"type": "function", "function": {"name": "read_file"}}
    both = knows.one_look_up([other, RECALL_SCHEMA, LOOKUP_SCHEMA])
    assert _names(both) == ["read_file", "recall"] and both[1] is knows.RECALL_BOTH
    assert set(knows.RECALL_BOTH["function"]["parameters"]["properties"]) == {"query", "topic"}
    assert knows.RECALL_BOTH["function"]["parameters"]["required"] == ["query"]
    assert RECALL_SCHEMA["function"]["description"] in knows.RECALL_BOTH["function"]["description"]
    # One of them alone is left as it is.
    assert knows.one_look_up([RECALL_SCHEMA]) == [RECALL_SCHEMA]
    assert knows.one_look_up([LOOKUP_SCHEMA]) == [LOOKUP_SCHEMA]
    # The tool a map tells the agent to ask: the one it was offered.
    assert knows.look_tool({"recall"}, ["recall", "lookup"]) == "recall"
    assert knows.look_tool({"lookup"}, ["lookup"]) == "lookup"
    assert knows.look_tool({"recall"}, ["recall"]) is None


def _runner(read_only=(), refused=False):
    async def lookup(ctx, args):
        if refused:
            raise ToolError("the Coder role uses no knowledge here any more")
        return f"pages for {args['question']} ({args['topic']})"

    return SimpleNamespace(
        _read_only_agents=set(read_only),
        _recall=lambda ctx, args: f"memory for {args['query']}",
        _lookup=lookup,
    )


def _look(runner, tools, name, args, agent="a"):
    ctx = SimpleNamespace(tools=tools, agent_id=agent, role="Coder")
    return asyncio.run(AgentRunner._look_up(runner, ctx, name, args))


def test_each_agent_looks_only_in_the_halves_it_holds():
    both = ["recall", "lookup"]
    assert _look(_runner(), both, "recall", {"query": "q", "topic": "Pay"}) == (
        "memory for q\n\npages for q (Pay)"
    )
    assert _look(_runner(), ["recall"], "recall", {"query": "q"}) == "memory for q"
    # lookup, the old name: its pages alone, as before - its question too.
    assert _look(_runner(), both, "lookup", {"question": "q"}) == "pages for q (None)"
    # KOLONİ's read-only Reviewer: never the memory.
    assert _look(_runner({"a"}), both, "recall", {"query": "q"}) == "pages for q (None)"
    with pytest.raises(ToolError):
        _look(_runner({"a"}), ["recall"], "recall", {"query": "q"})
    # The pages refused (the role's knowledge gone meanwhile): what the memory found stands.
    assert _look(_runner(refused=True), both, "recall", {"query": "q"}) == (
        "memory for q\n\nYour knowledge's pages: the Coder role uses no knowledge here any more"
    )
    with pytest.raises(ToolError):
        _look(_runner(refused=True), both, "lookup", {"question": "q"})
