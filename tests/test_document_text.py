import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz

from app import database as db
from app.services.document_text import (
    DocumentRejected,
    _download,
    extract_dynamic_document,
    extract_pdf_bytes,
    validate_url,
)


FIXTURES = Path(__file__).parent / "fixtures" / "public_dynamics"


class FakeResponse:
    def __init__(self, *, status_code=200, headers=None, content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requested_urls = []

    def get(self, url, **kwargs):
        self.requested_urls.append(url)
        return self.responses.pop(0)


class FakePage:
    def __init__(self, text):
        self.text = text

    def get_text(self, mode):
        return self.text


class FakeDocument:
    def __init__(self, texts):
        self.texts = texts
        self.page_count = len(texts)
        self.loaded_pages = []
        self.closed = False

    def load_page(self, index):
        self.loaded_pages.append(index)
        return FakePage(self.texts[index])

    def close(self):
        self.closed = True


class FailingDocument(FakeDocument):
    def load_page(self, index):
        raise RuntimeError("/Users/private/report.pdf SECRET_RESPONSE_BODY")


class DocumentTextSafetyTest(unittest.TestCase):
    def test_validate_url_rejects_unlisted_host(self):
        with self.assertRaises(DocumentRejected):
            validate_url("http://127.0.0.1/private.pdf")

    def test_validate_url_requires_https_on_allowed_host(self):
        with self.assertRaises(DocumentRejected):
            validate_url("http://static.cninfo.com.cn/report.pdf")

    def test_extract_pdf_bytes_reads_searchable_text(self):
        content = (FIXTURES / "searchable.pdf").read_bytes()

        result = extract_pdf_bytes(content)

        self.assertIn("TradingBuddy public announcement fixture", result["text"])
        self.assertEqual(result["status"], "extracted")

    def test_extract_pdf_bytes_rejects_non_pdf(self):
        with self.assertRaises(DocumentRejected):
            extract_pdf_bytes(b"<html>not pdf</html>")

    def test_download_rejects_declared_file_over_20_mb(self):
        client = FakeClient(
            [
                FakeResponse(
                    headers={
                        "content-length": str(20 * 1024 * 1024 + 1),
                        "content-type": "application/pdf",
                    }
                )
            ]
        )

        with self.assertRaises(DocumentRejected):
            _download(client, "https://static.cninfo.com.cn/report.pdf")

    def test_download_rejects_redirect_to_unlisted_host(self):
        client = FakeClient(
            [
                FakeResponse(
                    status_code=302,
                    headers={"location": "https://example.test/private.pdf"},
                )
            ]
        )

        with self.assertRaises(DocumentRejected):
            _download(client, "https://static.cninfo.com.cn/report.pdf")
        self.assertEqual(client.requested_urls, ["https://static.cninfo.com.cn/report.pdf"])

    def test_download_rejects_non_pdf_content_type(self):
        client = FakeClient(
            [
                FakeResponse(
                    headers={"content-type": "text/html"},
                    content=b"%PDF-not-really",
                )
            ]
        )

        with self.assertRaises(DocumentRejected):
            _download(client, "https://static.cninfo.com.cn/report.pdf")

    def test_pdf_without_searchable_text_is_unsupported(self):
        document = fitz.open()
        document.new_page()
        content = document.tobytes()
        document.close()

        result = extract_pdf_bytes(content)

        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["text"], "")

    def test_extract_pdf_bytes_reads_at_most_120_pages(self):
        document = FakeDocument([f"page-{index}" for index in range(121)])
        with patch("app.services.document_text.fitz.open", return_value=document):
            result = extract_pdf_bytes(b"%PDF fixture")

        self.assertEqual(document.loaded_pages, list(range(120)))
        self.assertNotIn("page-120", result["text"])
        self.assertTrue(document.closed)

    def test_extract_pdf_bytes_limits_text_to_200000_characters(self):
        document = FakeDocument(["x" * 200_001])
        with patch("app.services.document_text.fitz.open", return_value=document):
            result = extract_pdf_bytes(b"%PDF fixture")

        self.assertEqual(len(result["text"]), 200_000)

    def test_extract_pdf_bytes_sanitizes_page_read_failure(self):
        document = FailingDocument(["unreadable"])
        with patch("app.services.document_text.fitz.open", return_value=document):
            with self.assertRaisesRegex(DocumentRejected, "无法解析") as raised:
                extract_pdf_bytes(b"%PDF fixture")

        self.assertNotIn("/Users/private", str(raised.exception))
        self.assertNotIn("SECRET_RESPONSE_BODY", str(raised.exception))
        self.assertTrue(document.closed)


class DynamicDocumentExtractionTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = db.settings.database_path
        self.original_ready = db._schema_ready
        db.settings.database_path = str(Path(self.tempdir.name) / "test.db")
        db._schema_ready = False
        db.init_db()
        timestamp = "2026-09-21T00:00:00+00:00"
        self.asset_id = db.execute(
            "INSERT INTO assets (stock_code, stock_name, asset_type, "
            "notifications_enabled, created_at, updated_at) "
            "VALUES ('600000', '浦发银行', 'watchlist', 0, ?, ?)",
            (timestamp, timestamp),
        )
        self.dynamic_id = db.execute(
            "INSERT INTO public_dynamics (asset_id, canonical_key, kind, category, "
            "canonical_title, summary, published_at, importance_score, created_at, updated_at) "
            "VALUES (?, 'notice-1', 'announcement', '公告', '测试公告', '', ?, 50, ?, ?)",
            (self.asset_id, timestamp, timestamp, timestamp),
        )
        self.document_url = "https://static.cninfo.com.cn/report.pdf"
        self.evidence_id = "evidence-1"
        db.execute(
            "INSERT INTO evidence (evidence_id, stock_code, source_type, source_level, "
            "title, excerpt, published_at, source_url, fetched_at, content_status, raw) "
            "VALUES (?, '600000', 'announcement', 'primary', '测试公告', '', ?, "
            "'https://www.cninfo.com.cn/detail', ?, 'title_only', ?)",
            (
                self.evidence_id,
                timestamp,
                timestamp,
                json.dumps({"document_url": self.document_url}),
            ),
        )
        db.execute(
            "INSERT INTO public_dynamic_evidence (dynamic_id, evidence_id, relation, created_at) "
            "VALUES (?, ?, 'primary', ?)",
            (self.dynamic_id, self.evidence_id, timestamp),
        )

    def tearDown(self):
        db.settings.database_path = self.original_path
        db._schema_ready = self.original_ready
        self.tempdir.cleanup()

    def _pdf_response(self, content):
        return FakeResponse(
            headers={
                "content-length": str(len(content)),
                "content-type": "application/pdf; charset=binary",
            },
            content=content,
        )

    def test_success_caches_document_and_marks_evidence_and_dynamic_full(self):
        content = (FIXTURES / "searchable.pdf").read_bytes()

        result = extract_dynamic_document(
            self.dynamic_id, client=FakeClient([self._pdf_response(content)])
        )

        self.assertEqual(result["extraction_status"], "extracted")
        self.assertIn("TradingBuddy public announcement fixture", result["extracted_text"])
        cached = db.query_one(
            "SELECT * FROM document_cache WHERE evidence_id = ?", (self.evidence_id,)
        )
        self.assertEqual(cached, result)
        evidence = db.query_one(
            "SELECT excerpt, content_status FROM evidence WHERE evidence_id = ?",
            (self.evidence_id,),
        )
        dynamic = db.query_one(
            "SELECT content_status FROM public_dynamics WHERE id = ?", (self.dynamic_id,)
        )
        self.assertEqual(evidence["content_status"], "full")
        self.assertIn("TradingBuddy public announcement fixture", evidence["excerpt"])
        self.assertEqual(dynamic["content_status"], "full")

    def test_extracted_cache_hit_is_returned_without_downloading(self):
        timestamp = "2026-09-21T01:00:00+00:00"
        db.execute(
            "INSERT INTO document_cache (evidence_id, document_url, document_hash, mime_type, "
            "byte_size, extraction_status, extracted_text, extracted_at, error_message, updated_at) "
            "VALUES (?, ?, 'hash', 'application/pdf', 100, 'extracted', 'cached text', ?, NULL, ?)",
            (self.evidence_id, self.document_url, timestamp, timestamp),
        )
        client = FakeClient([])

        result = extract_dynamic_document(self.dynamic_id, client=client)

        self.assertEqual(result["extracted_text"], "cached text")
        self.assertEqual(client.requested_urls, [])
        self.assertEqual(result["updated_at"], timestamp)

    def test_pdf_without_text_is_cached_as_unsupported(self):
        document = fitz.open()
        document.new_page()
        content = document.tobytes()
        document.close()

        result = extract_dynamic_document(
            self.dynamic_id, client=FakeClient([self._pdf_response(content)])
        )

        self.assertEqual(result["extraction_status"], "unsupported")
        self.assertEqual(result["extracted_text"], "")
        self.assertEqual(
            db.query_one(
                "SELECT content_status FROM public_dynamics WHERE id = ?",
                (self.dynamic_id,),
            )["content_status"],
            "title_only",
        )

    def test_rejected_download_is_cached_without_response_body_or_local_path(self):
        secret = "/Users/private/report.pdf SECRET_RESPONSE_BODY"
        response = FakeResponse(
            headers={"content-type": "text/html"}, content=secret.encode()
        )

        with self.assertRaises(DocumentRejected):
            extract_dynamic_document(self.dynamic_id, client=FakeClient([response]))

        cached = db.query_one(
            "SELECT extraction_status, error_message FROM document_cache WHERE evidence_id = ?",
            (self.evidence_id,),
        )
        self.assertEqual(cached["extraction_status"], "failed")
        self.assertNotIn("/Users/private", cached["error_message"])
        self.assertNotIn("SECRET_RESPONSE_BODY", cached["error_message"])

    def test_missing_document_url_is_rejected(self):
        db.execute(
            "UPDATE evidence SET raw = '{}' WHERE evidence_id = ?", (self.evidence_id,)
        )

        with self.assertRaises(DocumentRejected):
            extract_dynamic_document(self.dynamic_id, client=FakeClient([]))

    def test_non_object_evidence_metadata_is_rejected(self):
        db.execute(
            "UPDATE evidence SET raw = '[]' WHERE evidence_id = ?", (self.evidence_id,)
        )

        with self.assertRaises(DocumentRejected):
            extract_dynamic_document(self.dynamic_id, client=FakeClient([]))


if __name__ == "__main__":
    unittest.main()
