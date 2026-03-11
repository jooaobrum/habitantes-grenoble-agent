# Pipeline Pattern

Three classes in separate files: `loader.py`, `processor.py`, `writer.py`. Each has a single responsibility.

## loader.py

```python
from loguru import logger


class Loader:
    def __init__(self, <connection>):
        # store whatever client/session you need to read data
        self.<connection> = <connection>

    def read_full(self, source: str) -> <DataFrame>:
        logger.info(f"Reading full source: {source}")
        try:
            df = ...  # read all data from source
            return df
        except Exception as e:
            logger.error(f"Error reading {source}: {e}")
            raise

    def read_batch(self, source: str, dt_start: str, dt_stop: str) -> <DataFrame>:
        logger.info(f"Reading batch: {source} from {dt_start} to {dt_stop}")
        try:
            df = ...  # read filtered slice of data
            return df
        except Exception as e:
            logger.error(f"Error reading batch {source}: {e}")
            raise
```

## processor.py

```python
from loguru import logger


class Processor:
    def __init__(self, <config_fields>):
        # store everything the processor needs to transform data
        self.<field> = <field>
        self.df = None

    def _step_one(self):
        # private method for first transformation
        ...

    def _step_two(self):
        # private method for second transformation
        ...

    def run(self, df) -> <DataFrame>:
        self.df = df
        logger.info("Running processor")
        self._step_one()
        self._step_two()
        return self.df
```

## writer.py

```python
from loguru import logger


class Writer:
    def __init__(self, path: str):
        self.path = path

    def write(self, df, mode: str = "overwrite", metadata: dict = None) -> None:
        logger.info(f"Writing to: {self.path}")
        try:
            ...  # persist df to self.path
        except Exception as e:
            logger.error(f"Error writing to {self.path}: {e}")
            raise
```

## Wiring in a notebook or script

```python
config = ProjectConfig.from_yaml("configs/project.yml", env=env)

loader = Loader(<connection>)
processor = Processor(<config_fields>)
writer = Writer(path=<output_path>)

df = loader.read_batch(source, dt_start, dt_stop)
processed_df = processor.run(df)
writer.write(processed_df, mode="append", metadata={"run_date": today})
```
