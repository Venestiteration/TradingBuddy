import socket
import unittest

from fastapi import HTTPException

from app.services.visitor_ai import build_visitor_ai_config


def public_resolver(host, port, type=socket.SOCK_STREAM):
    return [(socket.AF_INET, type, 6, "", ("8.8.8.8", port))]


def private_resolver(host, port, type=socket.SOCK_STREAM):
    return [(socket.AF_INET, type, 6, "", ("10.0.0.8", port))]


def shared_resolver(host, port, type=socket.SOCK_STREAM):
    return [(socket.AF_INET, type, 6, "", ("100.64.0.1", port))]


class VisitorAIConfigTest(unittest.TestCase):
    def test_blank_url_uses_openai_default(self):
        config = build_visitor_ai_config("sk-user", "gpt-4.1-mini", "", resolver=public_resolver)
        self.assertEqual(config.base_url, "https://api.openai.com/v1")
        self.assertEqual(config.api_mode, "responses")

    def test_public_compatible_url_is_accepted(self):
        config = build_visitor_ai_config(
            "visitor-key", "glm-4-flash", "https://open.bigmodel.cn/api/paas/v4/",
            resolver=public_resolver,
        )
        self.assertEqual(config.model, "glm-4-flash")
        self.assertEqual(config.api_mode, "chat")

    def test_compatible_url_can_explicitly_select_chat_mode(self):
        config = build_visitor_ai_config(
            "visitor-key", "custom-model", "https://api.example.com/v1",
            api_mode="chat", resolver=public_resolver,
        )
        self.assertEqual(config.api_mode, "chat")

    def test_unknown_api_mode_is_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            build_visitor_ai_config(
                "visitor-key", "custom-model", "https://api.example.com/v1",
                api_mode="unknown", resolver=public_resolver,
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_missing_key_or_model_is_rejected(self):
        for key, model in (("", "gpt-4.1-mini"), ("sk-user", "")):
            with self.subTest(key=key, model=model), self.assertRaises(HTTPException) as caught:
                build_visitor_ai_config(key, model, "", resolver=public_resolver)
            self.assertEqual(caught.exception.status_code, 400)

    def test_missing_key_header_has_actionable_error(self):
        with self.assertRaises(HTTPException) as caught:
            build_visitor_ai_config(None, "gpt-4.1-mini", "", resolver=public_resolver)
        self.assertEqual(caught.exception.detail, "未收到 API Key，请重新保存")

    def test_non_https_and_private_destinations_are_rejected(self):
        cases = [
            ("http://api.example.com/v1", public_resolver),
            ("https://localhost/v1", public_resolver),
            ("https://service.local/v1", public_resolver),
            ("https://user:pass@api.example.com/v1", public_resolver),
            ("https://api.example.com/v1", private_resolver),
        ]
        for url, resolver in cases:
            with self.subTest(url=url), self.assertRaises(HTTPException):
                build_visitor_ai_config("sk-user", "model", url, resolver=resolver)

    def test_shared_address_destinations_are_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            build_visitor_ai_config(
                "sk-user", "model", "https://api.example.com/v1", resolver=shared_resolver
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_malformed_bracketed_ipv6_url_is_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            build_visitor_ai_config(
                "sk-user", "model", "https://[2001:db8::1/v1", resolver=public_resolver
            )
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail, "API 地址不是允许的公网地址")

    def test_length_limits_are_enforced(self):
        with self.assertRaises(HTTPException):
            build_visitor_ai_config("k" * 513, "model", "", resolver=public_resolver)
        with self.assertRaises(HTTPException):
            build_visitor_ai_config("key", "m" * 129, "", resolver=public_resolver)


if __name__ == "__main__":
    unittest.main()
