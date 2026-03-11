# Config Pattern

Two files: `config.py` (Pydantic models) + `project.yml` (values).

## config.py

```python
from typing import Dict

import yaml
from pydantic import BaseModel


class <SourceConfig>(BaseModel):
    # fields specific to your data source
    host: str
    table_name: str


class <ProcessorConfig>(BaseModel):
    # fields specific to your processing step
    model_name: str
    prompt_name: str


class <WriterConfig>(BaseModel):
    # fields specific to your output
    output_path: str


class <EnvironmentConfig>(BaseModel):
    # fields that change per environment (dev/qa/prod)
    catalog_name: str
    schema_name: str


class ProjectConfig(BaseModel):
    source: <SourceConfig>
    processor: <ProcessorConfig>
    writer: <WriterConfig>
    environments: Dict[str, <EnvironmentConfig>]

    @classmethod
    def from_yaml(cls, config_path: str, env: str):
        with open(config_path, "r") as f:
            config_dict = yaml.safe_load(f)

        env_config = config_dict.get("environments", {}).get(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found in configuration.")

        main_config = {k: v for k, v in config_dict.items() if k != "environments"}
        merged_config = {**main_config, "environments": {env: env_config}}

        return cls(**merged_config)
```

## project.yml

```yaml
source:
  host: "..."
  table_name: "..."

processor:
  model_name: "..."
  prompt_name: "..."

writer:
  output_path: "..."

environments:
  dev:
    catalog_name: "..."
    schema_name: "..."
  qa:
    catalog_name: "..."
    schema_name: "..."
  prod:
    catalog_name: "..."
    schema_name: "..."
```

## Usage

```python
config = ProjectConfig.from_yaml(config_path="configs/project.yml", env="dev")
```

---

## DTO — Pydantic models at layer boundaries

Every value crossing a layer boundary uses a Pydantic model. Raw dicts are never passed between layers unvalidated.

```python
from pydantic import BaseModel, Field


class <Request>(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    # add fields with validation constraints


class <EvidenceItem>(BaseModel):
    document: str
    excerpt: str
    score: float = Field(..., ge=0.0, le=1.0)


class <Response>(BaseModel):
    answer: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: list[<EvidenceItem>] = []
    trace_id: str
```

**Rule:** internal graph/pipeline state (TypedDict or dataclass) stays internal. Only `<Request>` and `<Response>` are exposed at boundaries (API, CLI, notebook entry points).
