import os
import unittest
from unittest.mock import patch

import httpcore
import httpx

from shared.qdrant_client.client import QdrantClientWrapper


class QdrantProxyRoutingTests(unittest.TestCase):
    def setUp(self):
        self._previous_instance = QdrantClientWrapper._instance
        QdrantClientWrapper._instance = None
        self._environment = patch.dict(os.environ, clear=False)
        self._environment.start()

        self.wrapper = QdrantClientWrapper(
            host="192.168.59.128",
            port=6333,
            proxy_url="http://127.0.0.1:7897",
        )
        self.qdrant_client = self.wrapper.get_client()
        self.http_client = httpx.Client()

    def tearDown(self):
        self.http_client.close()
        self.qdrant_client.close()
        QdrantClientWrapper._instance = self._previous_instance
        self._environment.stop()

    def test_local_qdrant_ip_uses_direct_connection(self):
        transport = self.http_client._transport_for_url(
            httpx.URL("http://192.168.59.128:6333")
        )

        self.assertNotIsInstance(transport._pool, httpcore.HTTPProxy)

    def test_external_requests_keep_using_proxy(self):
        transport = self.http_client._transport_for_url(
            httpx.URL("https://example.com")
        )

        self.assertIsInstance(transport._pool, httpcore.HTTPProxy)


if __name__ == "__main__":
    unittest.main()
