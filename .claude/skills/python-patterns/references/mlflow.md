# MLflow Pattern

Two uses: experiment tracking (metrics/params/tags) and prompt versioning (registry).

## Experiment tracking

```python
import mlflow

mlflow.set_tracking_uri("...")        # e.g. "databricks" or local path
mlflow.set_experiment("<experiment_name>")

with mlflow.start_run(run_name="<run_name>") as run:
    mlflow.log_param("<key>", <value>)         # hyperparams, config values
    mlflow.log_metric("<metric>", <value>)     # scores, losses, counts
    mlflow.set_tag("<tag>", "<value>")         # status labels, free-form metadata
```

## Prompt versioning (registry)

### Register a prompt after it passes evaluation

```python
import mlflow

mlflow.set_registry_uri("...")   # e.g. "databricks-uc" or local

prompt = mlflow.genai.register_prompt(
    name="<catalog>.<schema>.<prompt_name>",
    template=<prompt_string>,
    commit_message="<why this version was registered>",
)

client = mlflow.tracking.MlflowClient()
client.set_prompt_alias("<catalog>.<schema>.<prompt_name>", "champion", str(prompt.version))
```

### Load champion prompt at runtime (with fallback)

```python
def load_champion_prompt_or_fallback(prompt_name: str, fallback_template: str) -> str:
    try:
        mlflow.set_registry_uri("...")
        pv = mlflow.genai.load_prompt(
            name_or_uri=f"prompts:/{prompt_name}@champion",
            allow_missing=True,
        )
        if pv is not None:
            return pv.template
    except Exception:
        pass
    return fallback_template
```

## Evaluation with scorer

```python
from mlflow.entities import Feedback
from mlflow.genai.scorers import scorer

@scorer
def <my_scorer>(*, outputs, expectations, **_):
    # compare outputs to expectations field by field
    score = ...
    return [Feedback(name="<metric_name>", value=score)]

with mlflow.start_run(run_name=run_name) as run:
    results = mlflow.genai.evaluate(data=eval_df, scorers=[<my_scorer>])
    macro = results.metrics.get("<metric>/mean")
    mlflow.log_metric("<metric>", macro)
```
