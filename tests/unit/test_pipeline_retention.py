import os
import time
from pathlib import Path

from ingestion.pipeline import cleanup_expired_artifacts


def _age_file(path: Path, days_old: int) -> None:
    ts = time.time() - days_old * 86400
    os.utime(path, (ts, ts))


def test_cleanup_deletes_only_expired_raw_and_intermediate_files(tmp_path: Path):
    data_dir = tmp_path / "data"
    artifacts_dir = tmp_path / "artifacts"
    chat_dir = artifacts_dir / "chat"
    data_dir.mkdir()
    chat_dir.mkdir(parents=True)

    old_raw = data_dir / "old.txt"
    old_raw.write_text("old", encoding="utf-8")
    _age_file(old_raw, days_old=100)

    fresh_raw = data_dir / "fresh.txt"
    fresh_raw.write_text("fresh", encoding="utf-8")

    old_artifact = chat_dir / "classified.csv"
    old_artifact.write_text("old", encoding="utf-8")
    _age_file(old_artifact, days_old=100)

    fresh_artifact = chat_dir / "qa_pairs.json"
    fresh_artifact.write_text("[]", encoding="utf-8")

    cleanup_expired_artifacts(data_dir, artifacts_dir, retention_days=90)

    assert not old_raw.exists()
    assert fresh_raw.exists()
    assert not old_artifact.exists()
    assert fresh_artifact.exists()


def test_cleanup_disabled_when_retention_not_positive(tmp_path: Path):
    data_dir = tmp_path / "data"
    artifacts_dir = tmp_path / "artifacts"
    data_dir.mkdir()
    artifacts_dir.mkdir()

    old_raw = data_dir / "old.txt"
    old_raw.write_text("old", encoding="utf-8")
    _age_file(old_raw, days_old=1000)

    cleanup_expired_artifacts(data_dir, artifacts_dir, retention_days=0)

    assert old_raw.exists()


def test_cleanup_skips_concat_directory(tmp_path: Path):
    data_dir = tmp_path / "data"
    artifacts_dir = tmp_path / "artifacts"
    concat_dir = artifacts_dir / "concat"
    data_dir.mkdir()
    concat_dir.mkdir(parents=True)

    concat_file = concat_dir / "qa_pairs.json"
    concat_file.write_text("[]", encoding="utf-8")
    _age_file(concat_file, days_old=100)

    cleanup_expired_artifacts(data_dir, artifacts_dir, retention_days=90)

    assert concat_file.exists()
