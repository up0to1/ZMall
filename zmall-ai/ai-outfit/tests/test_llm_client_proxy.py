import unittest
from unittest.mock import patch

from app.api import deps
from shared.model_client.llm_client import LlmClient


_PROXY_URL = "http://127.0.0.1:7897"


class _FakeResponse:
    status_code = 200

    @staticmethod
    def json():
        return {
            "choices": [{
                "message": {
                    "content": '{"query_text":"休闲日常穿搭","style_tags":["休闲"]}',
                    "tool_calls": [],
                }
            }]
        }


class _FakeAsyncClient:
    def __init__(self, **kwargs):
        self.options = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def post(self, *args, **kwargs):
        return _FakeResponse()

    async def aclose(self):
        return None


class LlmClientProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_react_intent_uses_configured_proxy_for_dashscope(self):
        with patch(
            "shared.model_client.llm_client.httpx.AsyncClient",
            side_effect=lambda **kwargs: _FakeAsyncClient(**kwargs),
        ) as client_factory:
            client = LlmClient(
                api_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key="test-key",
                proxy_url=_PROXY_URL,
            )
            try:
                result = await client.react_intent(
                    user_input={
                        "style_tags": ["休闲"],
                        "scene_desc": "日常穿搭",
                        "color": ["黑色", "白色"],
                        "has_photo": False,
                    },
                    max_rounds=1,
                )
            finally:
                await client.close()

        self.assertEqual(result["query_text"], "休闲日常穿搭")
        self.assertTrue(client_factory.call_args_list)
        self.assertTrue(
            all(call.kwargs.get("proxy") == _PROXY_URL for call in client_factory.call_args_list)
        )

    async def test_dependency_injects_configured_proxy(self):
        previous_client = deps._llm_client
        deps._llm_client = None
        try:
            with patch.object(deps.settings, "proxy_url", _PROXY_URL), \
                 patch("app.api.deps.LlmClient") as client_factory:
                expected_client = client_factory.return_value
                result = await deps.get_llm_client()
        finally:
            deps._llm_client = previous_client

        self.assertIs(result, expected_client)
        self.assertEqual(client_factory.call_args.kwargs.get("proxy_url"), _PROXY_URL)


if __name__ == "__main__":
    unittest.main()
