from __future__ import annotations

import json
from concurrent.futures import Future, wait
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread

import httpx

from .. import database as db
from .evidence import make_evidence
from .public_dynamics_aggregate import aggregate_raw_dynamics
from .public_dynamics_sources import (
    CninfoAnnouncementAdapter,
    EastmoneyNewsAdapter,
    EastmoneyNoticeAdapter,
    SourceAdapter,
)
from .public_dynamics_types import (
    MEDIA_PROVIDERS,
    OFFICIAL_PROVIDERS,
    PUBLIC_DYNAMICS_FORMULA_VERSION,
    ProviderResult,
    RawDynamic,
    SyncDecision,
)

# A total wall-clock budget also bounds AKShare calls that lack socket timeouts.
# Uncooperative calls are quarantined: only one daemon worker per provider may
# remain in flight. Late results have no database access and are never persisted.
SOURCE_TIMEOUT_SECONDS = 20.0
_provider_workers: dict[str, Future] = {}
_provider_workers_lock = Lock()


def decide_sync(state: dict | None, force: bool, now: datetime) -> SyncDecision:
    if force:
        return SyncDecision(True, "manual")
    if state and state.get("last_status") in {"partial", "failed"}:
        attempted = datetime.fromisoformat(state["last_attempt_at"])
        if now.astimezone(attempted.tzinfo) - attempted < timedelta(minutes=30):
            return SyncDecision(False, "failure_cooldown")
        return SyncDecision(True, "retry_after_failure")
    if not state or not state.get("last_complete_at"):
        return SyncDecision(True, "never_complete")
    completed = datetime.fromisoformat(state["last_complete_at"])
    if now.astimezone(completed.tzinfo) - completed <= timedelta(hours=24):
        return SyncDecision(False, "fresh")
    return SyncDecision(True, "stale")


def _provider_start(asset_id: int, provider: str, now: datetime) -> datetime:
    row = db.query_one(
        "SELECT last_success_at FROM source_sync_state WHERE asset_id = ? AND provider = ?",
        (asset_id, provider),
    )
    if row and row.get("last_success_at"):
        return datetime.fromisoformat(row["last_success_at"]) - timedelta(hours=24)
    return now - timedelta(days=90)


def _channel_status(results: list[ProviderResult]) -> str:
    successful = {
        result.provider
        for result in results
        if result.status in {"success", "empty"}
    }
    official_ok = bool(successful & OFFICIAL_PROVIDERS)
    media_ok = MEDIA_PROVIDERS.issubset(successful)
    if official_ok and media_ok:
        return "complete"
    if successful or any(result.items for result in results):
        return "partial"
    return "failed"


def serialize_provider_result(result: ProviderResult) -> dict:
    return {
        "provider": result.provider,
        "status": result.status,
        "attempted_at": result.attempted_at,
        "item_count": len(result.items),
        "error_code": result.error_code,
        "error_message": result.error_message,
    }


def _default_adapters(client: httpx.Client) -> tuple[SourceAdapter, ...]:
    import akshare as ak

    return (
        CninfoAnnouncementAdapter(client),
        EastmoneyNoticeAdapter(ak),
        EastmoneyNewsAdapter(ak),
    )


def _failed_provider_result(
    provider: str, attempted_at: str, exc: Exception
) -> ProviderResult:
    return ProviderResult(
        provider=provider,
        status="failed",
        items=(),
        attempted_at=attempted_at,
        error_code=exc.__class__.__name__,
        error_message=str(exc)[:300],
    )


def _fetch_results(
    asset: dict,
    adapters: tuple[SourceAdapter, ...],
    now: datetime,
    attempted_at: str,
) -> list[ProviderResult]:
    starts = {
        adapter.provider: _provider_start(asset["id"], adapter.provider, now)
        for adapter in adapters
    }

    def fetch(adapter: SourceAdapter) -> ProviderResult:
        try:
            return adapter.fetch(
                asset["stock_code"], starts[adapter.provider], now, attempted_at
            )
        except Exception as exc:
            return _failed_provider_result(adapter.provider, attempted_at, exc)

    pending = {}

    def run(adapter, future):
        result = fetch(adapter)
        with _provider_workers_lock:
            if _provider_workers.get(adapter.provider) is future:
                del _provider_workers[adapter.provider]
            future.set_result(result)

    for adapter in adapters:
        with _provider_workers_lock:
            if adapter.provider in _provider_workers:
                future = Future()
                future.set_result(
                    _failed_provider_result(
                        adapter.provider,
                        attempted_at,
                        TimeoutError("前次来源请求尚未结束，本次未重复启动"),
                    )
                )
            else:
                future = Future()
                _provider_workers[adapter.provider] = future
                Thread(target=run, args=(adapter, future), daemon=True).start()
            pending[adapter.provider] = future
    if pending:
        wait(pending.values(), timeout=SOURCE_TIMEOUT_SECONDS)
    return [
        future.result() if future.done() else _failed_provider_result(
            provider, attempted_at, TimeoutError("来源请求超过同步等待时限")
        )
        for provider, future in pending.items()
    ]


def _save_evidence(conn, item: RawDynamic) -> dict:
    evidence = make_evidence(
        stock_code=item.stock_code,
        source_type=item.kind,
        source_level=item.source_level,
        title=item.title,
        excerpt=item.excerpt,
        published_at=item.published_at,
        source_url=item.source_url,
        content_status=item.content_status,
        raw={
            "provider": item.provider,
            "provider_item_id": item.provider_item_id,
            "publisher": item.publisher,
            "document_url": item.document_url,
            "raw_metadata": item.raw_metadata,
        },
    )
    existing = conn.execute(
        "SELECT * FROM evidence WHERE evidence_id = ?", (evidence["evidence_id"],)
    ).fetchone()
    if existing:
        ranks = {"title_only": 0, "excerpt": 1, "full": 2}
        if ranks[existing["content_status"]] >= ranks[evidence["content_status"]]:
            evidence["content_status"] = existing["content_status"]
            evidence["excerpt"] = existing["excerpt"]
        old_raw = json.loads(existing["raw"] or "{}")
        evidence["raw"] = {
            **old_raw,
            **{
                key: value
                for key, value in evidence["raw"].items()
                if value is not None
            },
        }
    conn.execute(
        "INSERT INTO evidence (evidence_id, stock_code, source_type, source_level, "
        "title, excerpt, published_at, source_url, fetched_at, content_status, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(evidence_id) DO UPDATE SET fetched_at = excluded.fetched_at, "
        "excerpt = excluded.excerpt, content_status = excluded.content_status, raw = excluded.raw",
        (
            evidence["evidence_id"],
            evidence["stock_code"],
            evidence["source_type"],
            evidence["source_level"],
            evidence["title"],
            evidence["excerpt"],
            evidence["published_at"],
            evidence["source_url"],
            evidence["fetched_at"],
            evidence["content_status"],
            json.dumps(evidence["raw"], ensure_ascii=False),
        ),
    )
    return evidence


def _upsert_source_state(conn, asset_id: int, result: ProviderResult, updated_at: str):
    success_at = (
        result.attempted_at if result.status in {"success", "empty"} else None
    )
    conn.execute(
        "INSERT INTO source_sync_state (asset_id, provider, last_attempt_at, "
        "last_success_at, last_status, last_error_code, last_error_message, "
        "item_count, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(asset_id, provider) DO UPDATE SET "
        "last_attempt_at = excluded.last_attempt_at, "
        "last_success_at = COALESCE(excluded.last_success_at, "
        "source_sync_state.last_success_at), "
        "last_status = excluded.last_status, "
        "last_error_code = excluded.last_error_code, "
        "last_error_message = excluded.last_error_message, "
        "item_count = excluded.item_count, updated_at = excluded.updated_at",
        (
            asset_id,
            result.provider,
            result.attempted_at,
            success_at,
            result.status,
            result.error_code,
            result.error_message,
            len(result.items),
            updated_at,
        ),
    )


def _upsert_cluster(conn, asset_id: int, cluster, evidence_by_item, updated_at: str):
    conn.execute(
        "INSERT INTO public_dynamics (asset_id, canonical_key, kind, category, "
        "canonical_title, summary, published_at, importance_score, "
        "importance_factors_json, formula_version, content_status, "
        "conflict_status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(asset_id, canonical_key) DO UPDATE SET "
        "kind = excluded.kind, category = excluded.category, "
        "canonical_title = excluded.canonical_title, "
        "summary = CASE WHEN length(excluded.summary) > length(public_dynamics.summary) "
        "THEN excluded.summary ELSE public_dynamics.summary END, "
        "published_at = CASE WHEN datetime(excluded.published_at) > datetime(public_dynamics.published_at) "
        "THEN excluded.published_at ELSE public_dynamics.published_at END, "
        "importance_score = excluded.importance_score, "
        "importance_factors_json = excluded.importance_factors_json, "
        "formula_version = excluded.formula_version, "
        "content_status = CASE WHEN public_dynamics.content_status = 'full' THEN 'full' "
        "WHEN public_dynamics.content_status = 'excerpt' AND excluded.content_status = 'title_only' "
        "THEN 'excerpt' ELSE excluded.content_status END, "
        "conflict_status = excluded.conflict_status, updated_at = excluded.updated_at",
        (
            asset_id,
            cluster.canonical_key,
            cluster.kind,
            cluster.category,
            cluster.title,
            cluster.summary,
            cluster.published_at,
            cluster.importance_score,
            json.dumps(cluster.importance_factors, ensure_ascii=False),
            PUBLIC_DYNAMICS_FORMULA_VERSION,
            cluster.content_status,
            cluster.conflict_status,
            updated_at,
            updated_at,
        ),
    )
    dynamic_id = conn.execute(
        "SELECT id FROM public_dynamics WHERE asset_id = ? AND canonical_key = ?",
        (asset_id, cluster.canonical_key),
    ).fetchone()["id"]
    for member in cluster.members:
        evidence_id = evidence_by_item[id(member)]["evidence_id"]
        conn.execute(
            "INSERT INTO public_dynamic_evidence "
            "(dynamic_id, evidence_id, relation, created_at) VALUES (?, ?, 'corroborating', ?) "
            "ON CONFLICT(dynamic_id, evidence_id) DO NOTHING",
            (dynamic_id, evidence_id, updated_at),
        )

    linked = conn.execute(
        "SELECT e.*, de.relation FROM public_dynamic_evidence de "
        "JOIN evidence e ON e.evidence_id = de.evidence_id WHERE de.dynamic_id = ?",
        (dynamic_id,),
    ).fetchall()

    def primary_rank(evidence):
        from .document_text import DocumentRejected, validate_url

        raw = json.loads(evidence["raw"] or "{}")
        try:
            valid_document = bool(validate_url(raw.get("document_url") or ""))
        except DocumentRejected:
            valid_document = False
        return (
            valid_document,
            raw.get("provider") == "cninfo",
            evidence["content_status"] == "full",
            evidence["source_level"] == "primary",
            evidence["relation"] == "primary",
            evidence["evidence_id"],
        )

    primary = max(linked, key=primary_rank)
    conn.execute(
        "UPDATE public_dynamic_evidence SET relation = CASE WHEN evidence_id = ? "
        "THEN 'primary' ELSE 'corroborating' END WHERE dynamic_id = ?",
        (primary["evidence_id"], dynamic_id),
    )
    ranks = {"title_only": 0, "excerpt": 1, "full": 2}
    best_status = max(
        [cluster.content_status, *[item["content_status"] for item in linked]],
        key=ranks.get,
    )
    # Linked evidence may already contain extracted text, including from a
    # provider absent in this run. Refresh the canonical completeness from it.
    conn.execute(
        "UPDATE public_dynamics SET content_status = CASE WHEN content_status = 'full' "
        "THEN 'full' WHEN ? = 'full' THEN 'full' WHEN content_status = 'excerpt' "
        "THEN 'excerpt' ELSE ? END WHERE id = ?",
        (best_status, best_status, dynamic_id),
    )


def sync_public_dynamics(
    asset: dict,
    force: bool = False,
    now: datetime | None = None,
    adapters: tuple[SourceAdapter, ...] | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    state = db.query_one(
        "SELECT * FROM public_dynamics_sync_state WHERE asset_id = ?",
        (asset["id"],),
    )
    decision = decide_sync(state, force, now)
    if not decision.should_sync:
        return {
            "status": state["last_status"],
            "decision": decision.reason,
            "synced": False,
            "providers": source_status(asset["id"])["providers"],
            "last_complete_at": state.get("last_complete_at"),
        }

    attempted_at = now.astimezone(timezone.utc).isoformat()
    owned_client = None
    if adapters is None:
        owned_client = httpx.Client()
        adapters = _default_adapters(owned_client)
    try:
        results = _fetch_results(asset, adapters, now, attempted_at)
    finally:
        if owned_client is not None:
            owned_client.close()

    status = _channel_status(results)
    successful_items = [
        item
        for result in results
        for item in result.items
    ]
    updated_at = attempted_at
    with db.get_conn() as conn:
        for result in results:
            _upsert_source_state(conn, asset["id"], result, updated_at)

        evidence_by_item = {
            id(item): _save_evidence(conn, item) for item in successful_items
        }
        for cluster in aggregate_raw_dynamics(successful_items):
            _upsert_cluster(
                conn, asset["id"], cluster, evidence_by_item, updated_at
            )

        complete_at = attempted_at if status == "complete" else None
        conn.execute(
            "INSERT INTO public_dynamics_sync_state (asset_id, last_attempt_at, "
            "last_complete_at, last_status, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(asset_id) DO UPDATE SET "
            "last_attempt_at = excluded.last_attempt_at, "
            "last_complete_at = CASE WHEN excluded.last_status = 'complete' "
            "THEN excluded.last_complete_at "
            "ELSE public_dynamics_sync_state.last_complete_at END, "
            "last_status = excluded.last_status, updated_at = excluded.updated_at",
            (asset["id"], attempted_at, complete_at, status, updated_at),
        )
        persisted = conn.execute(
            "SELECT last_complete_at FROM public_dynamics_sync_state WHERE asset_id = ?",
            (asset["id"],),
        ).fetchone()
        last_complete_at = persisted["last_complete_at"]

    return {
        "status": status,
        "decision": decision.reason,
        "synced": True,
        "providers": [serialize_provider_result(result) for result in results],
        "last_complete_at": last_complete_at,
    }


def _utc_bound(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_dynamic(row: dict) -> dict:
    raw_factors = row.pop("importance_factors_json", "{}")
    try:
        row["importance_factors"] = json.loads(raw_factors or "{}")
    except json.JSONDecodeError:
        row["importance_factors"] = {}
    return row


def list_public_dynamics(
    asset_id: int,
    start: datetime,
    end: datetime,
    kind: str = "all",
    limit: int | None = None,
) -> list[dict]:
    kind_map = {"official": "announcement", "media": "news"}
    if kind not in {"all", *kind_map}:
        raise ValueError(f"unsupported public dynamics kind: {kind}")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")

    clauses = [
        "d.asset_id = ?",
        "datetime(d.published_at) >= datetime(?)",
        "datetime(d.published_at) <= datetime(?)",
    ]
    params: list = [asset_id, _utc_bound(start), _utc_bound(end)]
    if kind != "all":
        clauses.append("d.kind = ?")
        params.append(kind_map[kind])
    sql = (
        "SELECT d.*, COUNT(e.evidence_id) AS evidence_count "
        "FROM public_dynamics d "
        "LEFT JOIN public_dynamic_evidence de ON de.dynamic_id = d.id "
        "LEFT JOIN evidence e ON e.evidence_id = de.evidence_id "
        f"WHERE {' AND '.join(clauses)} GROUP BY d.id "
        "ORDER BY datetime(d.published_at) DESC"
    )
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [_parse_dynamic(row) for row in db.query(sql, tuple(params))]


def dynamic_evidence(dynamic_id: int, asset_id: int | None = None) -> list[dict]:
    clauses = ["de.dynamic_id = ?"]
    params: list = [dynamic_id]
    if asset_id is not None:
        clauses.append("d.asset_id = ?")
        params.append(asset_id)
    rows = db.query(
        "SELECT e.evidence_id, e.stock_code, e.source_type, e.source_level, "
        "e.title, e.excerpt, e.published_at, e.source_url, e.fetched_at, "
        "e.content_status, e.raw, de.relation "
        "FROM public_dynamic_evidence de "
        "JOIN public_dynamics d ON d.id = de.dynamic_id "
        "JOIN evidence e ON e.evidence_id = de.evidence_id "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY CASE de.relation WHEN 'primary' THEN 0 ELSE 1 END, "
        "e.published_at DESC",
        tuple(params),
    )
    for row in rows:
        try:
            row["raw"] = json.loads(row.get("raw") or "{}")
        except json.JSONDecodeError:
            row["raw"] = {}
    return rows


def get_public_dynamic(dynamic_id: int) -> dict | None:
    row = db.query_one(
        "SELECT d.*, COUNT(e.evidence_id) AS evidence_count "
        "FROM public_dynamics d "
        "LEFT JOIN public_dynamic_evidence de ON de.dynamic_id = d.id "
        "LEFT JOIN evidence e ON e.evidence_id = de.evidence_id "
        "WHERE d.id = ? GROUP BY d.id",
        (dynamic_id,),
    )
    if not row:
        return None
    item = _parse_dynamic(row)
    item["evidence"] = dynamic_evidence(dynamic_id, asset_id=item["asset_id"])
    return item


def source_status(asset_id: int) -> dict:
    state = db.query_one(
        "SELECT last_attempt_at, last_complete_at, last_status "
        "FROM public_dynamics_sync_state WHERE asset_id = ?",
        (asset_id,),
    )
    providers = db.query(
        "SELECT provider, last_attempt_at, last_success_at, last_status, "
        "last_error_code, last_error_message, item_count, updated_at "
        "FROM source_sync_state WHERE asset_id = ? ORDER BY provider",
        (asset_id,),
    )
    return {
        "status": state["last_status"] if state else "never_synced",
        "last_attempt_at": state["last_attempt_at"] if state else None,
        "last_complete_at": state["last_complete_at"] if state else None,
        "providers": providers,
    }
