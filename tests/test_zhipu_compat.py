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

ZHIPU_FLASH_CONFIG = VisitorAIConfig(
    api_key="visitor-key",
    model="glm-4-flash",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    resolved_ips=("8.8.8.8",),
)

OPENAI_CONFIG = VisitorAIConfig(
    api_key="visitor-key",
    model="gpt-test",
    base_url="https://api.openai.com/v1",
    resolved_ips=("8.8.8.8",),
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
        self.responses = SimpleNamespace(create=self.create_response)
        self.response_kwargs = None
        self.closed = False
        self.close_error = None

    def create_response(self, **kwargs):
        self.response_kwargs = kwargs
        return SimpleNamespace(output_text=json.dumps({"impact_state": "insufficient"}))

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


class ZhipuCompatibilityTest(unittest.TestCase):
    def test_research_schema_is_sent_to_openai_responses(self):
        original_client = ai._client
        try:
            fake = FakeClient()
            ai._client = lambda config: fake

            ai._call_model(
                OPENAI_CONFIG,
                "system instructions",
                {"asset": {"stock_code": "600519"}},
            )

            format_config = fake.response_kwargs["text"]["format"]
            self.assertTrue(format_config["strict"])
            self.assertEqual(format_config["schema"], ai.RESEARCH_SCHEMA)
            self.assertEqual(format_config["name"], "grounded_research")
        finally:
            ai._client = original_client

    def test_research_schema_is_included_for_chat_json_mode(self):
        original_client = ai._client
        try:
            fake = FakeClient()
            ai._client = lambda config: fake

            ai._call_model(
                CHAT_CONFIG,
                "system instructions",
                {"asset": {"stock_code": "600519"}},
            )

            system_message = fake.chat.completions.kwargs["messages"][0]["content"]
            self.assertIn('"core_conclusion"', system_message)
            self.assertIn('"additionalProperties": false', system_message)
        finally:
            ai._client = original_client

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

    def test_zhipu_standard_model_does_not_receive_reasoning_override(self):
        original_client = ai._client
        try:
            fake = FakeClient()
            ai._client = lambda config: fake

            ai._call_model(
                ZHIPU_FLASH_CONFIG,
                "system instructions",
                {"stock": {"code": "600519"}},
            )

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

    def test_model_name_error_is_reported_as_actionable_model_failure(self):
        original_client = ai._client
        fake = FakeClient()

        def raise_model_error(**kwargs):
            raise RuntimeError("Error code: 400 - model not found")

        fake.chat.completions.create = raise_model_error
        try:
            ai._client = lambda config: fake

            with self.assertRaises(ai.AIError) as context:
                ai._call_model(
                    ZHIPU_CONFIG,
                    "system instructions",
                    {"stock": {"code": "600519"}},
                )
        finally:
            ai._client = original_client

        self.assertEqual(context.exception.category, "model")
        self.assertIn("模型名称", str(context.exception))

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
