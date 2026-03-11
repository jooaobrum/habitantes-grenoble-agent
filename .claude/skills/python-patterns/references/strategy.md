# Strategy + Repository Patterns

## Strategy — swappable provider behind a stable function signature

Tools expose one narrow function. The implementation inside is swappable. Callers never know what's behind it.

```python
# tool.py
def <action>(<args>) -> dict:
    # swap provider by changing only this file's internals
    # callers never change
    client = _get_client()
    result = client.<provider_call>(<args>)
    return {"<output_key>": result}
```

**Don't** put `if settings.provider == "X":` inside callers (nodes, scripts, notebooks). That logic belongs inside the tool.

```python
# Wrong — provider logic leaking into caller:
if settings.llm.provider == "openai":
    result = openai_client.chat(...)
else:
    result = anthropic_client.messages(...)

# Correct — caller is stable:
result = llm_tool.generate(query, chunks)
```

---

## Repository — hide storage details behind a retrieval function

Callers call one function and receive a standard dict. They never see the underlying storage object (database cursor, ORM object, SDK response, etc.).

```python
# tool.py
def retrieve(<query_args>) -> dict:
    client = _get_client()
    raw = client.<storage_call>(<query_args>)
    # always return the same shape:
    return {
        "<items>": [
            {"<field_1>": item.<field_1>, "<field_2>": item.<field_2>}
            for item in raw.<results>
        ]
    }
```

**For tests:** replace `tool.retrieve` with a function returning a fixed list. The caller under test is unchanged.

```python
# In test:
monkeypatch.setattr("app.tools.<tool>.retrieve", lambda **_: {"<items>": [...]})
```
