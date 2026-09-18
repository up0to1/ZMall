import unittest
from unittest.mock import patch

from shared.model_client.embed_client import EmbedClient


class EmbedClientProxyTests(unittest.TestCase):
    def test_configured_proxy_is_used_for_dashscope_embeddings(self):
        with patch("shared.model_client.embed_client.httpx.AsyncClient") as client_factory:
            EmbedClient(
                api_url="https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
                api_key="test-key",
                proxy_url="http://127.0.0.1:7897",
            )

        self.assertEqual(
            client_factory.call_args.kwargs.get("proxy"),
            "http://127.0.0.1:7897",
        )


if __name__ == "__main__":
    unittest.main()
