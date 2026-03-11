# Logging Pattern

Use `loguru`. No custom logger setup needed — import and call directly.

## Usage

```python
from loguru import logger

logger.info("Starting step X")
logger.info(f"Processing {n} records from {source}")
logger.error(f"Error reading {table}: {e}")
logger.warning(f"Skipping {row_id}: missing required field")
```

## Inside class methods

Always log at the start of a public method and on exceptions:

```python
def read_batch(self, source: str, dt_start: str, dt_stop: str):
    logger.info(f"Reading batch: {source} [{dt_start} → {dt_stop}]")
    try:
        result = ...
        return result
    except Exception as e:
        logger.error(f"Error reading {source}: {e}")
        raise
```

## Log levels

| Level | When to use |
|---|---|
| `logger.info` | Normal progress checkpoints |
| `logger.warning` | Recoverable issues, skipped records |
| `logger.error` | Caught exceptions before re-raising |
| `logger.debug` | Verbose detail only needed during dev |
