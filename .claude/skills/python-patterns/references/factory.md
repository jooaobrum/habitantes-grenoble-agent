# Factory Pattern — Lazy Client Initialisation

Expensive clients (databases, HTTP clients, SDK instances) are created on first use, not at import time.

## Skeleton

```python
# tool.py
_client = None


def _get_client():
    global _client
    if _client is None:
        import <heavy_dependency>         # import here, not at module top
        _client = <heavy_dependency>.<Client>(
            <connection_args_from_settings>
        )
    return _client


def <action>(<args>) -> dict:
    client = _get_client()
    result = client.<call>(<args>)
    return {"<output_key>": result}
```

## Why

`import tool` must never crash in environments where the dependency isn't running (CI, unit tests, other services). Lazy init defers the connection until it's actually needed.

## Testing — patch `_get_client`, not the dependency

```python
def test_<action>(monkeypatch):
    mock_client = MagicMock()
    mock_client.<call>.return_value = <fixture_result>
    monkeypatch.setattr("app.tools.<tool>._get_client", lambda: mock_client)

    result = <tool>.<action>(<test_args>)
    assert result["<output_key>"] == <expected>
```

**Don't** initialise the client at module level:

```python
# Wrong — crashes on import if service is unavailable:
_client = ChromaDB.HttpClient(host=settings.db.host)
```
