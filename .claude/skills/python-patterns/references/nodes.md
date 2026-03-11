# Pure Function Nodes Pattern

Every processing node (graph step, pipeline stage) is a stateless function: takes input state, returns a partial update dict. No side effects, no global reads, no mutations.

## Skeleton

```python
from typing import TypedDict


class <PipelineState>(TypedDict):
    # all fields the pipeline can carry
    <input_field>: str
    <intermediate_field>: str | None
    <output_field>: str | None


def <node_name>(state: <PipelineState>) -> dict:
    # read from state, compute, return only what changed
    value = _compute(state["<input_field>"])
    return {"<output_field>": value}
```

## Rules

- **Read** from `state` freely.
- **Return** only the keys that changed — not the full state.
- **No external I/O** inside the node. All storage/LLM calls go through tools.
- `logger.info()` is allowed. Network calls, file writes, DB reads are not.

## Connecting nodes to tools

```python
# Wrong — I/O inside node:
def retrieve_node(state):
    db = chromadb.HttpClient(...)          # not allowed
    results = db.query(state["query"])
    return {"chunks": results}

# Correct — delegate to tool:
from app.tools import vector_store

def retrieve_node(state: <PipelineState>) -> dict:
    result = vector_store.retrieve(state["query"])
    if "error" in result:
        return {"chunks": [], "fallback_triggered": True}
    return {"chunks": result["chunks"]}
```

## Unit testing — zero mocking required for pure logic

```python
def test_<node_name>():
    state = {
        "<input_field>": "<test_value>",
        "<intermediate_field>": None,
        "<output_field>": None,
    }
    result = <node_name>(state)
    assert result["<output_field>"] == "<expected>"
```

When the node calls a tool, patch only the tool function — the node itself is unchanged.
