import unittest

from fastapi.testclient import TestClient

from app.main import create_app


class SecurityHeadersTest(unittest.TestCase):
    def test_static_and_api_responses_have_browser_security_headers(self):
        client = TestClient(create_app())
        for path in ("/", "/api/health"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            content_security_policy = response.headers["content-security-policy"]
            for directive in (
                "default-src 'self'",
                "script-src 'self'",
                "style-src 'self' 'unsafe-inline'",
                "img-src 'self' data:",
                "connect-src 'self'",
                "object-src 'none'",
                "base-uri 'self'",
                "frame-ancestors 'none'",
            ):
                with self.subTest(directive=directive):
                    self.assertIn(directive, content_security_policy)
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["referrer-policy"], "strict-origin-when-cross-origin")
            permissions_policy = response.headers["permissions-policy"]
            for permission in ("camera=()", "microphone=()", "geolocation=()", "payment=()"):
                with self.subTest(permission=permission):
                    self.assertIn(permission, permissions_policy)


if __name__ == "__main__":
    unittest.main()
