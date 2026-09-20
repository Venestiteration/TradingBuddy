import json
import unittest
from types import SimpleNamespace

import httpx

from app.services import ai
from app.services.visitor_ai import VisitorAIConfig, visitor_ai_config


ZHIPU_CONFIG = VisitorAIConfig(
    api_key="visitor-key",
    model="glm-5.3",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    resolved_ips=("8.8.8.8",),
)

CHAT_CONFIG = VisitorAIConfig(
    api_key="visitor-key",
    model="deepseek-chat",
    base_url="https://api.deepseek.com/v1",
    resolved_ips=("8.8.8.8",),
    api_mode="chat",
)


class FakeChatCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"impact_state": "insufficient"})
                    )
                )
            ]
        )


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeChatCompletions())
        self.closed = False
        self.close_error = None

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


class ZhipuCompatibilityTest(unittest.TestCase):
    def test_zhipu_json_code_fence_is_parsed(self):
        original_client = ai._client
        try:
            fake = FakeClient()
            fake.chat.completions.create = lambda **kwargs: SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='```json\n{"impact_state": "insufficient"}\n```'
                        )
                    )
                ]
            )
            ai._client = lambda config: fake

            result = ai._call_model(
                ZHIPU_CONFIG,
                "system instructions",
                {"stock": {"code": "600519"}},
            )

            self.assertEqual(result["impact_state"], "insufficient")
        finally:
            ai._client = original_client

    def test_zhipu_base_url_uses_chat_completions(self):
        original_client = ai._client
        try:
            fake = FakeClient()
            ai._client = lambda config: fake

            result = ai._call_model(
                ZHIPU_CONFIG,
                "system instructions",
                {"stock": {"code": "600519"}},
            )

            self.assertEqual(result["impact_state"], "insufficient")
            self.assertEqual(fake.chat.completions.kwargs["response_format"], {"type": "json_object"})
            self.assertEqual(
                fake.chat.completions.kwargs["extra_body"],
                {"reasoning_effort": "low"},
            )
            self.assertEqual(fake.chat.completions.kwargs["messages"][0]["role"], "system")
        finally:
            ai._client = original_client

    def test_generic_chat_provider_uses_chat_completions(self):
        original_client = ai._client
        try:
            fake = FakeClient()
            ai._client = lambda config: fake

            result = ai._call_model(
                CHAT_CONFIG,
                "system instructions",
                {"stock": {"code": "600519"}},
            )

            self.assertEqual(result["impact_state"], "insufficient")
            self.assertEqual(fake.chat.completions.kwargs["response_format"], {"type": "json_object"})
            self.assertNotIn("extra_body", fake.chat.completions.kwargs)
        finally:
            ai._client = original_client

    def test_structured_model_accepts_custom_schema(self):
        original_client = ai._client
        try:
            fake = FakeClient()
            fake.chat.completions.create = lambda **kwargs: SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps({"summary": "已整理"})
                        )
                    )
                ]
            )
            ai._client = lambda config: fake

            result = ai.call_structured_model(
                ZHIPU_CONFIG,
                "整理判断",
                {"messages": []},
                {
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                    "required": ["summary"],
                    "additionalProperties": False,
                },
                "thesis_draft",
            )

            self.assertEqual(result, {"summary": "已整理"})
        finally:
            ai._client = original_client

    def test_model_client_is_closed_after_success(self):
        original_client = ai._client
        fake = FakeClient()
        try:
            ai._client = lambda config: fake

            ai._call_model(
                ZHIPU_CONFIG,
                "system instructions",
                {"stock": {"code": "600519"}},
            )
        finally:
            ai._client = original_client

        self.assertTrue(fake.closed)

    def test_model_client_close_does_not_mask_model_error(self):
        original_client = ai._client
        fake = FakeClient()

        def raise_model_error(**kwargs):
            raise RuntimeError("model boom")

        fake.chat.completions.create = raise_model_error
        fake.close_error = RuntimeError("close boom")
        try:
            ai._client = lambda config: fake

            with self.assertRaisesRegex(ai.AIError, "模型调用失败: model boom"):
                ai._call_model(
                    ZHIPU_CONFIG,
                    "system instructions",
                    {"stock": {"code": "600519"}},
                )
        finally:
            ai._client = original_client

        self.assertTrue(fake.closed)

    def test_request_is_pinned_to_validated_ip_with_original_authority(self):
        request = httpx.Request(
            "POST",
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        )

        ai._pin_request_to_validated_ip(ZHIPU_CONFIG)(request)

        self.assertEqual(request.url.host, "8.8.8.8")
        self.assertEqual(request.headers["Host"], "open.bigmodel.cn")
        self.assertEqual(request.extensions["sni_hostname"], "open.bigmodel.cn")

    def test_request_to_different_host_is_rejected(self):
        request = httpx.Request("POST", "https://attacker.example/v1/chat/completions")

        with self.assertRaises(ai.AIError):
            ai._pin_request_to_validated_ip(ZHIPU_CONFIG)(request)


if __name__ == "__main__":
    unittest.main()
