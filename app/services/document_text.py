from __future__ import annotations

import hashlib
import json
from urllib.parse import urljoin, urlparse

import httpx
import pymupdf as fitz

from .. import database as db


ALLOWED_DOCUMENT_HOSTS = frozenset(
    {
        "static.cninfo.com.cn",
        "www.cninfo.com.cn",
        "data.eastmoney.com",
        "pdf.dfcfw.com",
    }
)
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_PAGES = 120
MAX_EXTRACTED_CHARS = 200_000


class DocumentRejected(RuntimeError):
    pass


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOCUMENT_HOSTS:
        raise DocumentRejected("公告地址不在允许列表中")
    return url


def extract_pdf_bytes(content: bytes) -> dict:
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentRejected("公告文件超过 20 MB")
    if not content.startswith(b"%PDF"):
        raise DocumentRejected("响应内容不是 PDF")
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except (fitz.FileDataError, RuntimeError, ValueError) as exc:
        raise DocumentRejected("公告 PDF 无法解析") from exc
    try:
        try:
            text = "\n".join(
                document.load_page(index).get_text("text")
                for index in range(min(document.page_count, MAX_DOCUMENT_PAGES))
            ).strip()[:MAX_EXTRACTED_CHARS]
        except Exception as exc:
            raise DocumentRejected("公告 PDF 无法解析") from exc
    finally:
        document.close()
    return {
        "status": "extracted" if text else "unsupported",
        "text": text,
        "hash": hashlib.sha256(content).hexdigest(),
        "byte_size": len(content),
        "mime_type": "application/pdf",
    }


def _download(client: httpx.Client, url: str) -> bytes:
    current = validate_url(url)
    for _ in range(4):
        response = client.get(current, timeout=20.0, follow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise DocumentRejected("公告重定向缺少目标地址")
            current = validate_url(urljoin(current, location))
            continue
        response.raise_for_status()
        try:
            declared = int(response.headers.get("content-length") or 0)
        except (TypeError, ValueError) as exc:
            raise DocumentRejected("公告响应长度无效") from exc
        if declared > MAX_DOCUMENT_BYTES:
            raise DocumentRejected("公告文件超过 20 MB")
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        if content_type not in {"application/pdf", "application/octet-stream"}:
            raise DocumentRejected("公告响应类型不是 PDF")
        return response.content
    raise DocumentRejected("公告重定向次数过多")


def _primary_announcement(dynamic_id: int) -> dict:
    row = db.query_one(
        "SELECT e.evidence_id, e.raw FROM public_dynamic_evidence de "
        "JOIN evidence e ON e.evidence_id = de.evidence_id "
        "WHERE de.dynamic_id = ? AND de.relation = 'primary' "
        "AND e.source_type = 'announcement' LIMIT 1",
        (dynamic_id,),
    )
    if not row:
        raise DocumentRejected("公开动态没有可提取的主公告")
    return row


def _cache_failure(evidence_id: str, document_url: str, message: str) -> None:
    updated_at = db.utcnow()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO document_cache (evidence_id, document_url, extraction_status, "
            "extracted_text, extracted_at, error_message, updated_at) "
            "VALUES (?, ?, 'failed', '', NULL, ?, ?) "
            "ON CONFLICT(evidence_id) DO UPDATE SET "
            "document_url = excluded.document_url, document_hash = NULL, "
            "mime_type = NULL, byte_size = NULL, extraction_status = 'failed', "
            "extracted_text = '', extracted_at = NULL, "
            "error_message = excluded.error_message, updated_at = excluded.updated_at",
            (evidence_id, document_url, message, updated_at),
        )


def _cache_result(
    dynamic_id: int, evidence_id: str, document_url: str, result: dict
) -> dict:
    updated_at = db.utcnow()
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO document_cache (evidence_id, document_url, document_hash, "
            "mime_type, byte_size, extraction_status, extracted_text, extracted_at, "
            "error_message, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?) "
            "ON CONFLICT(evidence_id) DO UPDATE SET "
            "document_url = excluded.document_url, "
            "document_hash = excluded.document_hash, mime_type = excluded.mime_type, "
            "byte_size = excluded.byte_size, extraction_status = excluded.extraction_status, "
            "extracted_text = excluded.extracted_text, extracted_at = excluded.extracted_at, "
            "error_message = NULL, updated_at = excluded.updated_at",
            (
                evidence_id,
                document_url,
                result["hash"],
                result["mime_type"],
                result["byte_size"],
                result["status"],
                result["text"],
                updated_at,
                updated_at,
            ),
        )
        if result["status"] == "extracted":
            conn.execute(
                "UPDATE evidence SET excerpt = ?, content_status = 'full' "
                "WHERE evidence_id = ?",
                (result["text"], evidence_id),
            )
            conn.execute(
                "UPDATE public_dynamics SET content_status = 'full', updated_at = ? "
                "WHERE id = ?",
                (updated_at, dynamic_id),
            )
    cached = db.query_one(
        "SELECT * FROM document_cache WHERE evidence_id = ?", (evidence_id,)
    )
    assert cached is not None
    return cached


def extract_dynamic_document(
    dynamic_id: int, client: httpx.Client | None = None
) -> dict:
    evidence = _primary_announcement(dynamic_id)
    evidence_id = evidence["evidence_id"]
    cached = db.query_one(
        "SELECT * FROM document_cache WHERE evidence_id = ? "
        "AND extraction_status = 'extracted'",
        (evidence_id,),
    )
    if cached:
        return cached

    try:
        raw = json.loads(evidence["raw"] or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise DocumentRejected("公告元数据无效") from exc
    if not isinstance(raw, dict):
        raise DocumentRejected("公告元数据无效")
    document_url = raw.get("document_url")
    if not isinstance(document_url, str) or not document_url.strip():
        raise DocumentRejected("公告缺少可提取的 PDF 地址")
    document_url = document_url.strip()

    owned_client = client is None
    active_client = client or httpx.Client()
    try:
        content = _download(active_client, document_url)
        result = extract_pdf_bytes(content)
    except DocumentRejected as exc:
        _cache_failure(evidence_id, document_url, str(exc))
        raise
    except httpx.HTTPError:
        _cache_failure(evidence_id, document_url, "公告正文暂时无法获取")
        raise
    finally:
        if owned_client:
            active_client.close()

    return _cache_result(dynamic_id, evidence_id, document_url, result)
