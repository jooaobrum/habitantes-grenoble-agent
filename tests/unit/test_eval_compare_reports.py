"""compare_reports: success = recommendation improves AND regression does not drop."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "eval"))

import compare_reports as cr  # noqa: E402
from run_eval import cites_community_counts  # noqa: E402

DATASET = [
    {"id": "r1", "suite": "recommendation"},
    {"id": "r2", "suite": "recommendation"},
    {"id": "g1", "suite": "v1_regression"},
    {"id": "g2", "suite": "v1_regression"},
    {"id": "other", "suite": None},
]


def report(**passed: bool) -> dict:
    return {"cases": [{"id": k, "case_passed": v} for k, v in passed.items()]}


def test_success_when_recommendation_improves_and_regression_holds():
    base = report(r1=False, r2=False, g1=True, g2=False, other=True)
    feat = report(r1=True, r2=False, g1=True, g2=False, other=False)
    res = cr.compare(base, feat, DATASET)
    assert res["success"] is True
    assert res["recommendation"]["baseline_pass_rate"] == 0.0
    assert res["recommendation"]["feature_pass_rate"] == 0.5
    assert res["recommendation"]["fixed"] == ["r1"]
    assert res["regression"]["n_cases"] == 2  # untagged "other" is ignored


def test_failure_when_regression_drops():
    base = report(r1=False, r2=False, g1=True, g2=True)
    feat = report(r1=True, r2=True, g1=True, g2=False)
    res = cr.compare(base, feat, DATASET)
    assert res["success"] is False
    assert res["regression"]["broken"] == ["g2"]
    assert "regression pass rate dropped" in res["failure_reasons"]


def test_failure_when_recommendation_does_not_improve():
    base = report(r1=True, r2=False, g1=True, g2=True)
    feat = report(r1=True, r2=False, g1=True, g2=True)
    res = cr.compare(base, feat, DATASET)
    assert res["success"] is False
    assert res["recommendation_improved"] is False
    assert res["regression_not_dropped"] is True


def test_equal_regression_rate_is_not_a_drop():
    base = report(r1=False, r2=False, g1=True, g2=False)
    feat = report(r1=True, r2=False, g1=False, g2=True)  # one fixed, one broken
    assert cr.compare(base, feat, DATASET)["success"] is True


def test_only_common_cases_count():
    base = report(r1=False, g1=True)  # r2, g2 missing from baseline
    feat = report(r1=True, r2=True, g1=True, g2=False)
    res = cr.compare(base, feat, DATASET)
    assert res["recommendation"]["n_cases"] == 1
    assert res["regression"]["n_cases"] == 1
    assert res["success"] is True


def test_no_common_cases_is_failure():
    res = cr.compare(report(other=True), report(other=True), DATASET)
    assert res["success"] is False
    assert res["recommendation"]["baseline_pass_rate"] is None


def test_cli_writes_result_and_sets_exit_code(tmp_path, capsys):
    paths = {}
    for name, data in {
        "base": report(r1=False, r2=False, g1=True, g2=True),
        "feat": report(r1=True, r2=False, g1=True, g2=True),
        "data": DATASET,
    }.items():
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(data))
    out = tmp_path / "out.json"
    code = cr.main(
        [
            str(paths["base"]),
            str(paths["feat"]),
            "--dataset",
            str(paths["data"]),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert json.loads(out.read_text())["success"] is True
    assert "SUCCESS" in capsys.readouterr().out


def test_dataset_tags_are_consistent():
    root = Path(__file__).parents[2] / "tests" / "eval" / "golden_dataset_v2.json"
    cases = json.loads(root.read_text(encoding="utf-8"))
    assert len({c["id"] for c in cases}) == len(cases)
    rec = [c for c in cases if c.get("suite") == "recommendation"]
    reg = [c for c in cases if c.get("suite") == "v1_regression"]
    assert 18 <= len(rec) <= 25 and len(reg) >= 10
    assert all(
        c["expected_source"] == "suggestions" and c["test_type"] == "capability"
        for c in rec
    )
    assert all(c["expected_suggestions"]["verification"] for c in rec)
    assert all(
        c["expected_source"] == "kb" and c["test_type"] == "regression" for c in reg
    )


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("Épicerie X (9👍/0👎) - 20/05/2026", True),
        ("Resposta sem contagens", False),
        ("", False),
    ],
)
def test_cites_community_counts(answer, expected):
    assert cites_community_counts(answer) is expected
