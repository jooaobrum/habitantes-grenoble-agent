---
name: python-patterns
description: Pattern reference guide for personal Python coding style. Use when asked "show me the X pattern", "how should I structure X", "what's the config pattern", "how do I set up logging", "how do I track experiments", "what's your pipeline pattern", "how do I swap providers", "how should tools return errors", "how do I lazy-load a client", "what's the DTO pattern", or "how should I structure nodes". Covers: Pydantic config from YAML, Loader/Processor/Writer pipeline, loguru logging, MLflow tracking, Strategy, Repository, Result type, Factory, DTO, and pure function nodes. Do NOT use for general Python questions unrelated to these patterns.
license: CC-BY-4.0
metadata:
  author: jooaobrum
  version: 1.2.0
  last_reviewed: "2026-02"
---

# Python Patterns

Personal Python coding style reference. Return only the skeleton relevant to the requested pattern — no full file dumps.

## Instructions

### Step 1: Identify the requested pattern

Map the user's question to one reference file:

| User asks about | Load file |
|---|---|
| config, settings, YAML, environment, Pydantic, DTO, request/response models | `references/config.md` |
| loader, processor, writer, pipeline, ETL, step | `references/pipeline.md` |
| logging, log, loguru | `references/logging.md` |
| mlflow, experiment, tracking, run, metric, prompt registry | `references/mlflow.md` |
| strategy, provider, swap implementation, swappable backend | `references/strategy.md` |
| result type, error dict, tool return, success/failure shape | `references/result-type.md` |
| factory, lazy init, lazy client, patch in tests | `references/factory.md` |
| node, pure function, stateless, graph step, testable unit | `references/nodes.md` |

### Step 2: Load the relevant reference file

Read only the file that matches. Do not load all references at once.

### Step 3: Return the relevant skeleton

Return just the skeleton for the specific class or concept asked. If the user asks "show me the config pattern", return the `config.py` + `project.yml` skeletons. If they ask only about one piece (e.g. "how does `from_yaml` work?"), return only that method.

Keep the response minimal: skeleton + inline comments where the user needs to fill in their own fields. No prose explanation unless the user asks why.

## Examples

### Example 1: Config pattern

User says: "show me the config pattern"
Action: Load `references/config.md`, return the `config.py` + `project.yml` skeletons.

### Example 2: Specific pipeline class

User says: "how should I structure the processor?"
Action: Load `references/pipeline.md`, return only the `Processor` skeleton.

### Example 3: MLflow run

User says: "how do I log a run with mlflow?"
Action: Load `references/mlflow.md`, return only the `start_run` block.

### Example 4: Swappable provider

User says: "how do I make the LLM provider swappable?"
Action: Load `references/strategy.md`, return the Strategy skeleton.

### Example 5: Tool error handling

User says: "how should my tool return errors?"
Action: Load `references/result-type.md`, return the result type skeleton.
