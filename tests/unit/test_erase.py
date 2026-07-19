import json
from pathlib import Path

import pandas as pd
import pytest

from ingestion.erase import (
    build_matcher,
    delete_from_qdrant,
    erase_user_data,
    purge_csv,
    purge_json_records,
    purge_jsonl_records,
    purge_logs_by_chat_id,
    qdrant_point_ids_for_matches,
    redact_raw_export,
)


def test_build_matcher_normalizes_case_and_punctuation():
    matches = build_matcher(["Fulano De Tal", "+33 6 12 34 56 78"])

    assert matches("fulano de tal")
    assert matches("FULANO DE TAL")
    assert matches("+33612345678")
    assert not matches("Beltrano")


def test_build_matcher_requires_at_least_one_identifier():
    with pytest.raises(ValueError):
        build_matcher(["", "   "])


def test_redact_raw_export_blanks_message_and_continuation_lines(tmp_path: Path):
    chat = tmp_path / "chat.txt"
    chat.write_text(
        "[01/02/23, 10:00:00] Fulano: pergunta sobre CAF\n"
        "linha de continuação da pergunta\n"
        "[01/02/23, 10:05:00] Beltrano: aqui vai a resposta\n",
        encoding="utf-8",
    )
    matches = build_matcher(["Fulano"])

    # Dry run must not touch the file.
    n = redact_raw_export(chat, matches, dry_run=True)
    assert n == 1
    assert "pergunta sobre CAF" in chat.read_text(encoding="utf-8")

    n = redact_raw_export(chat, matches, dry_run=False)
    assert n == 1
    content = chat.read_text(encoding="utf-8")
    assert (
        "[01/02/23, 10:00:00] Fulano: [mensagem removida a pedido do usuário]"
        in content
    )
    assert "pergunta sobre CAF" not in content
    assert "linha de continuação" not in content
    # Other people's messages are untouched.
    assert "[01/02/23, 10:05:00] Beltrano: aqui vai a resposta" in content


def test_purge_csv_removes_matching_rows_only(tmp_path: Path):
    csv_path = tmp_path / "classified.csv"
    pd.DataFrame(
        [
            {"user": "Fulano", "message": "oi", "msg_type": "question"},
            {"user": "Beltrano", "message": "oi", "msg_type": "answer"},
        ]
    ).to_csv(csv_path, index=False)
    matches = build_matcher(["Fulano"])

    n = purge_csv(csv_path, matches, dry_run=False)

    assert n == 1
    remaining = pd.read_csv(csv_path)
    assert list(remaining["user"]) == ["Beltrano"]


def test_purge_csv_checks_answer_users_column(tmp_path: Path):
    csv_path = tmp_path / "qa_pairs.csv"
    pd.DataFrame(
        [
            {
                "question_user": "Ciclano",
                "answer_users": "['Fulano', 'Beltrano']",
                "question": "algum aluguel disponivel?",
            },
            {
                "question_user": "Beltrano",
                "answer_users": "['Ciclano']",
                "question": "onde acho um médico?",
            },
        ]
    ).to_csv(csv_path, index=False)
    matches = build_matcher(["Fulano"])

    n = purge_csv(csv_path, matches, dry_run=False)

    assert n == 1
    remaining = pd.read_csv(csv_path)
    assert list(remaining["question_user"]) == ["Beltrano"]


def test_purge_json_records_matches_question_and_answer_users(tmp_path: Path):
    json_path = tmp_path / "qa_pairs.json"
    records = [
        {"question_user": "Fulano", "answer_users": ["Beltrano"], "question": "q1"},
        {"question_user": "Ciclano", "answer_users": ["Fulano"], "question": "q2"},
        {"question_user": "Beltrano", "answer_users": ["Ciclano"], "question": "q3"},
    ]
    json_path.write_text(json.dumps(records), encoding="utf-8")
    matches = build_matcher(["Fulano"])

    n = purge_json_records(json_path, matches, dry_run=False)

    assert n == 2
    remaining = json.loads(json_path.read_text(encoding="utf-8"))
    assert [r["question"] for r in remaining] == ["q3"]


def test_purge_jsonl_records(tmp_path: Path):
    jsonl_path = tmp_path / "synthesis_results.jsonl"
    records = [
        {"question_user": "Fulano", "answer_users": [], "question": "q1"},
        {"question_user": "Beltrano", "answer_users": [], "question": "q2"},
    ]
    jsonl_path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    matches = build_matcher(["Fulano"])

    n = purge_jsonl_records(jsonl_path, matches, dry_run=False)

    assert n == 1
    remaining = [
        json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [r["question"] for r in remaining] == ["q2"]


def test_dry_run_never_writes_to_disk(tmp_path: Path):
    jsonl_path = tmp_path / "synthesis_results.jsonl"
    original = json.dumps({"question_user": "Fulano", "question": "q1"}) + "\n"
    jsonl_path.write_text(original, encoding="utf-8")
    matches = build_matcher(["Fulano"])

    n = purge_jsonl_records(jsonl_path, matches, dry_run=True)

    assert n == 1
    assert jsonl_path.read_text(encoding="utf-8") == original


def test_purge_logs_by_chat_id(tmp_path: Path):
    log_path = tmp_path / "interactions.jsonl"
    records = [
        {"chat_id": "hash_a", "user_query": "oi"},
        {"chat_id": "hash_b", "user_query": "oi"},
    ]
    log_path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )

    n = purge_logs_by_chat_id(log_path, ["hash_a"], dry_run=False)

    assert n == 1
    remaining = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [r["chat_id"] for r in remaining] == ["hash_b"]


def test_qdrant_point_ids_for_matches_uses_stable_point_id(tmp_path: Path):
    jsonl_path = tmp_path / "synthesis_results.jsonl"
    records = [
        {
            "source_file": "chat.txt",
            "thread_id": 1,
            "question_time": "2023-01-01 10:00:00",
            "question": "q1",
            "question_user": "Fulano",
            "answer_users": [],
        },
        {
            "source_file": "chat.txt",
            "thread_id": 2,
            "question_time": "2023-01-02 10:00:00",
            "question": "q2",
            "question_user": "Beltrano",
            "answer_users": [],
        },
    ]
    jsonl_path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    matches = build_matcher(["Fulano"])

    from ingestion.load.qdrant import stable_point_id

    ids = qdrant_point_ids_for_matches(jsonl_path, matches)

    assert ids == [stable_point_id(records[0])]


def test_delete_from_qdrant_dry_run_counts_without_client_call(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("QdrantClient should not be constructed in dry-run mode")

    monkeypatch.setattr("qdrant_client.QdrantClient", fail_if_called)

    n = delete_from_qdrant("some_collection", ["id1", "id2"], dry_run=True)

    assert n == 2


def test_erase_user_data_sweeps_raw_and_intermediate_artifacts(tmp_path: Path):
    data_dir = tmp_path / "data"
    artifacts_dir = tmp_path / "artifacts" / "chat"
    data_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)

    (data_dir / "chat.txt").write_text(
        "[01/02/23, 10:00:00] Fulano: numero de telefone e detalhes pessoais\n",
        encoding="utf-8",
    )

    pd.DataFrame([{"user": "Fulano", "message": "oi", "msg_type": "question"}]).to_csv(
        artifacts_dir / "classified.csv", index=False
    )

    (artifacts_dir / "qa_pairs.json").write_text(
        json.dumps([{"question_user": "Fulano", "answer_users": [], "question": "q1"}]),
        encoding="utf-8",
    )

    synth_records = [
        {
            "source_file": "chat.txt",
            "thread_id": 1,
            "question_time": "2023-01-01 10:00:00",
            "question": "q1",
            "question_user": "Fulano",
            "answer_users": [],
        }
    ]
    (artifacts_dir / "synthesis_results.jsonl").write_text(
        "\n".join(json.dumps(r) for r in synth_records) + "\n", encoding="utf-8"
    )

    report = erase_user_data(
        identifiers=["Fulano"],
        data_dir=data_dir,
        artifacts_dir=artifacts_dir,
        collection_name="test_collection",
        dry_run=True,
    )

    assert report["raw_lines_redacted"] == 1
    assert report["csv_rows_removed"] == 1
    assert (
        report["json_records_removed"] == 2
    )  # qa_pairs.json + synthesis_results.jsonl
    assert report["qdrant_points_removed"] == 1

    # Dry-run must leave every file untouched.
    assert "numero de telefone" in (data_dir / "chat.txt").read_text(encoding="utf-8")
