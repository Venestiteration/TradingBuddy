import unittest

from fastapi.testclient import TestClient

from app.main import create_app


class SecurityHeadersTest(unittest.TestCase):
    def test_static_and_api_responses_have_browser_security_headers(self):
        client = TestClient(create_app())
        for path in ("/", "/api/health"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("script-src 'self'", response.headers["content-security-policy"])
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["referrer-policy"], "strict-origin-when-cross-origin")
            self.assertIn("camera=()", response.headers["permissions-policy"])


if __name__ == "__main__":
    unittest.main()
