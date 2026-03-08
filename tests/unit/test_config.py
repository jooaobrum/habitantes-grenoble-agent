import unittest
from unittest.mock import mock_open, patch

from habitantes.config import load_settings


class TestConfig(unittest.TestCase):
    def setUp(self):
        # Clear lru_cache for each test
        load_settings.cache_clear()

        # Base YAML content to be mocked
        self.base_yaml = {
            "llm": {
                "model_name": "gpt-4o-mini",
                "embedding_model_name": "intfloat/multilingual-e5-small",
            },
            "vector_store": {"qdrant_url": "http://qdrant:6333"},
            "api": {"rate_limit_per_hour": 100, "eval_gate_enabled": True},
            "telegram": {"api_url": "http://api:8000"},
            "search": {
                "dense_prefetch_k": 80,
                "sparse_prefetch_k": 120,
                "fused_k": 50,
                "top_k": 5,
                "w_dense": 0.7,
                "w_sparse": 0.3,
                "rrf_k": 60,
            },
            "ranking": {
                "anchor_bonus": 0.05,
                "rerank_top_k": 40,
                "date_decay_lambda": 0.0005,
                "min_token_length": 4,
            },
            "agent": {
                "max_react_iterations": 5,
                "max_history": 5,
                "temperature": 0.0,
            },
            "environments": {
                "dev": {
                    "vector_store": {"collection_name": "dev_base"},
                    "api": {"log_level": "DEBUG"},
                },
                "qa": {
                    "vector_store": {"collection_name": "qa_base"},
                    "api": {"log_level": "INFO"},
                },
                "prod": {
                    "vector_store": {"collection_name": "prod_base"},
                    "api": {"log_level": "WARNING"},
                },
            },
        }

    @patch("builtins.open", new_callable=mock_open)
    @patch(
        "os.environ",
        {
            "OPENAI_API_KEY": "sk-test",
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "APP_ENV": "dev",
        },
    )
    def test_load_settings_dev(self, mock_file):
        with patch("yaml.safe_load", return_value=self.base_yaml):
            settings = load_settings()

            # New sections
            self.assertEqual(settings.search.top_k, 5)
            self.assertEqual(settings.ranking.anchor_bonus, 0.05)
            self.assertEqual(settings.agent.max_history, 5)

            self.assertEqual(settings.vector_store.collection_name, "dev_base")
            self.assertEqual(settings.api.log_level, "DEBUG")
            self.assertEqual(settings.app_env, "dev")

    @patch("builtins.open", new_callable=mock_open)
    @patch(
        "os.environ",
        {"OPENAI_API_KEY": "sk-test", "TELEGRAM_BOT_TOKEN": "123:abc", "APP_ENV": "qa"},
    )
    def test_load_settings_qa(self, mock_file):
        with patch("yaml.safe_load", return_value=self.base_yaml):
            settings = load_settings()

            # Should have the 'qa' collection name
            self.assertEqual(settings.vector_store.collection_name, "qa_base")
            self.assertEqual(settings.api.log_level, "INFO")
            self.assertEqual(settings.app_env, "qa")

    @patch("builtins.open", new_callable=mock_open)
    @patch(
        "os.environ",
        {
            "OPENAI_API_KEY": "sk-test",
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "APP_ENV": "prod",
        },
    )
    def test_load_settings_prod(self, mock_file):
        with patch("yaml.safe_load", return_value=self.base_yaml):
            settings = load_settings()

            # Should have the 'prod' collection name
            self.assertEqual(settings.vector_store.collection_name, "prod_base")
            self.assertEqual(settings.api.log_level, "WARNING")
            self.assertEqual(settings.app_env, "prod")

    @patch("builtins.open", new_callable=mock_open)
    @patch(
        "os.environ",
        {
            "OPENAI_API_KEY": "sk-test",
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "COLLECTION_NAME": "manual_override",
        },
    )
    def test_load_settings_manual_override(self, mock_file):
        with patch("yaml.safe_load", return_value=self.base_yaml):
            settings = load_settings()

            # System env variable should override YAML environment specifics
            self.assertEqual(settings.vector_store.collection_name, "manual_override")
