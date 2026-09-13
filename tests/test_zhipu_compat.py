import json
import unittest
from types import SimpleNamespace

from app.services import ai


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


class ZhipuCompatibilityTest(unittest.TestCase):
    def test_zhipu_json_code_fence_is_parsed(self):
        original_client = ai._client
        original_base_url = ai.settings.openai_base_url
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
            ai._client = lambda: fake
            ai.settings.openai_base_url = "https://open.bigmodel.cn/api/paas/v4/"

            result = ai._call_model("system instructions", {"stock": {"code": "600519"}})

            self.assertEqual(result["impact_state"], "insufficient")
        finally:
            ai._client = original_client
            ai.settings.openai_base_url = original_base_url

    def test_zhipu_base_url_uses_chat_completions(self):
        original_client = ai._client
        original_base_url = ai.settings.openai_base_url
        original_model = ai.settings.openai_model
        try:
            fake = FakeClient()
            ai._client = lambda: fake
            ai.settings.openai_base_url = "https://open.bigmodel.cn/api/paas/v4/"
            ai.settings.openai_model = "glm-5.3"

            result = ai._call_model("system instructions", {"stock": {"code": "600519"}})

            self.assertEqual(result["impact_state"], "insufficient")
            self.assertEqual(fake.chat.completions.kwargs["response_format"], {"type": "json_object"})
            self.assertEqual(
                fake.chat.completions.kwargs["extra_body"],
                {"reasoning_effort": "low"},
            )
            self.assertEqual(fake.chat.completions.kwargs["messages"][0]["role"], "system")
        finally:
            ai._client = original_client
            ai.settings.openai_base_url = original_base_url
            ai.settings.openai_model = original_model


if __name__ == "__main__":
    unittest.main()
