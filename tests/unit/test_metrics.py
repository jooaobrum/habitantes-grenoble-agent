import pytest
from unittest.mock import MagicMock
from habitantes.eval.metrics import recall_at_k, context_precision


class TestRecallAtK:
    def test_perfect_recall(self):
        retrieved = ["1", "2", "3", "4", "5"]
        relevant = ["1", "2"]
        assert recall_at_k(retrieved, relevant, k=5) == 1.0

    def test_partial_recall(self):
        retrieved = ["1", "3", "5", "7", "9"]
        relevant = ["1", "2"]
        # Only "1" is retrieved out of ["1", "2"]
        assert recall_at_k(retrieved, relevant, k=5) == 0.5

    def test_zero_recall(self):
        retrieved = ["3", "4", "5"]
        relevant = ["1", "2"]
        assert recall_at_k(retrieved, relevant, k=5) == 0.0

    def test_k_smaller_than_retrieved(self):
        retrieved = ["1", "2", "3", "4", "5"]
        relevant = ["3"]
        # "3" is at index 2 (rank 3), k=2 should give 0.0
        assert recall_at_k(retrieved, relevant, k=2) == 0.0
        # k=3 should give 1.0
        assert recall_at_k(retrieved, relevant, k=3) == 1.0

    def test_empty_relevant(self):
        assert recall_at_k(["1"], [], k=5) == 0.0

    def test_empty_retrieved(self):
        assert recall_at_k([], ["1"], k=5) == 0.0


class TestContextPrecision:
    def test_perfect_precision_at_top(self):
        retrieved = ["1", "2", "3"]
        relevant = ["1", "2"]
        # P@1 = 1/1 = 1.0 (rel)
        # P@2 = 2/2 = 1.0 (rel)
        # P@3 = 2/3 = 0.66 (not rel)
        # AP = (1.0 + 1.0) / 2 = 1.0
        assert context_precision(retrieved, relevant) == 1.0

    def test_relevant_at_lower_ranks(self):
        retrieved = ["3", "1", "2"]
        relevant = ["1", "2"]
        # rank 1: "3" (not rel)
        # rank 2: "1" (rel) -> P@2 = 1/2 = 0.5
        # rank 3: "2" (rel) -> P@3 = 2/3 = 0.666...
        # AP = (0.5 + 0.666...) / 2 = 0.58333...
        assert context_precision(retrieved, relevant) == pytest.approx(
            0.58333, rel=1e-4
        )

    def test_single_relevant_at_rank_3(self):
        retrieved = ["a", "b", "c", "d"]
        relevant = ["c"]
        # rank 1: a (no)
        # rank 2: b (no)
        # rank 3: c (YES) -> P@3 = 1/3
        # AP = (1/3) / 1 = 0.333...
        assert context_precision(retrieved, relevant) == pytest.approx(
            0.33333, rel=1e-4
        )

    def test_no_relevant_retrieved(self):
        retrieved = ["a", "b", "c"]
        relevant = ["x", "y"]
        assert context_precision(retrieved, relevant) == 0.0

    def test_empty_inputs(self):
        assert context_precision([], ["1"]) == 0.0
        assert context_precision(["1"], []) == 0.0


class TestE2EMetrics:
    def test_answer_relevance_parsing(self, monkeypatch):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "The relevance score is 0.85"
        mock_client.chat.completions.create.return_value = mock_response

        from habitantes.eval import metrics

        monkeypatch.setattr(metrics, "_get_client", lambda: mock_client)

        score = metrics.answer_relevance(
            "What is API?", "API is Application Programming Interface."
        )
        assert score == 0.85

    def test_faithfulness_parsing(self, monkeypatch):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Score: 1.0"
        mock_client.chat.completions.create.return_value = mock_response

        from habitantes.eval import metrics

        monkeypatch.setattr(metrics, "_get_client", lambda: mock_client)

        score = metrics.faithfulness("Answer", ["Context 1", "Context 2"])
        assert score == 1.0

    def test_semantic_similarity(self, monkeypatch):
        mock_model = MagicMock()
        # Mock encode to return dummy embeddings
        mock_model.encode.return_value = [0.1, 0.2]

        from habitantes.eval import metrics

        monkeypatch.setattr(metrics, "_get_embed_model", lambda: mock_model)

        # Mock util.cos_sim to return a tensor-like with .item()
        mock_score = MagicMock()
        mock_score.item.return_value = 0.95
        monkeypatch.setattr(metrics.util, "cos_sim", lambda a, b: mock_score)

        score = metrics.semantic_similarity("Hello", "Hi")
        assert score == 0.95

    def test_semantic_similarity_empty(self):
        from habitantes.eval import metrics

        assert metrics.semantic_similarity("", "Hi") == 0.0
        assert metrics.semantic_similarity("Hello", "") == 0.0
