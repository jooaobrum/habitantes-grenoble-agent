# Result Type Pattern

Tools return a structured dict — never raise exceptions across layer boundaries. Callers check which shape they received.

## Tool side — never raises

```python
def <tool_function>(<args>) -> dict:
    try:
        result = ...
        return {"<output_key>": result}           # success shape
    except <KnownError> as e:
        return {
            "error": {
                "error_code": "<ERROR_CODE>",
                "message": str(e),
                "retryable": True,                # or False
            }
        }
    except Exception as e:
        return {
            "error": {
                "error_code": "UNEXPECTED_ERROR",
                "message": str(e),
                "retryable": False,
            }
        }
```

## Caller side — handles both shapes

```python
result = <tool_function>(<args>)

if "error" in result:
    # handle gracefully — log, fallback, or propagate upward
    logger.warning(f"Tool failed: {result['error']['error_code']}")
    return {"<fallback_key>": <fallback_value>}

# happy path
return {"<output_key>": result["<output_key>"]}
```

## Canonical error schema (contracts.py)

```python
from pydantic import BaseModel


class ToolError(BaseModel):
    error_code: str
    message: str
    retryable: bool = False
```

**Rule:** exceptions are allowed inside a tool's own scope. They must not cross the boundary into callers. The caller always receives a dict.
