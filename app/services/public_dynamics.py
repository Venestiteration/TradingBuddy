from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

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


def decide_sync(state: dict | None, force: bool, now: datetime) -> SyncDecision:
    if force:
        return SyncDecision(True, "manual")
    if not state or not state.get("last_complete_at"):
        if state and state.get("last_status") in {"partial", "failed"}:
            attempted = datetime.fromisoformat(state["last_attempt_at"])
            if now.astimezone(attempted.tzinfo) - attempted < timedelta(minutes=30):
                return SyncDecision(False, "failure_cooldown")
        return SyncDecision(True, "never_complete")
    completed = datetime.fromisoformat(state["last_complete_at"])
    if now.astimezone(completed.tzinfo) - completed <= timedelta(hours=24):
        return SyncDecision(False, "fresh")
    if state.get("last_status") in {"partial", "failed"}:
        attempted = datetime.fromisoformat(state["last_attempt_at"])
        if now.astimezone(attempted.tzinfo) - attempted < timedelta(minutes=30):
            return SyncDecision(False, "failure_cooldown")
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
    if successful:
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

    with ThreadPoolExecutor(max_workers=3) as executor:
        return list(executor.map(fetch, adapters))


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
    conn.execute(
        "INSERT INTO evidence (evidence_id, stock_code, source_type, source_level, "
        "title, excerpt, published_at, source_url, fetched_at, content_status, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(evidence_id) DO UPDATE SET fetched_at = excluded.fetched_at",
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
        "canonical_title = excluded.canonical_title, summary = excluded.summary, "
        "published_at = excluded.published_at, "
        "importance_score = excluded.importance_score, "
        "importance_factors_json = excluded.importance_factors_json, "
        "formula_version = excluded.formula_version, "
        "content_status = excluded.content_status, "
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
    existing_primary = conn.execute(
        "SELECT evidence_id FROM public_dynamic_evidence "
        "WHERE dynamic_id = ? AND relation = 'primary' LIMIT 1",
        (dynamic_id,),
    ).fetchone()
    primary_evidence_id = existing_primary["evidence_id"] if existing_primary else None
    if primary_evidence_id is None:
        primary_member = next(
            (member for member in cluster.members if member.source_level == "primary"),
            None,
        )
        if primary_member is not None:
            primary_evidence_id = evidence_by_item[id(primary_member)]["evidence_id"]

    for member in cluster.members:
        evidence_id = evidence_by_item[id(member)]["evidence_id"]
        relation = "primary" if evidence_id == primary_evidence_id else "corroborating"
        conn.execute(
            "INSERT INTO public_dynamic_evidence "
            "(dynamic_id, evidence_id, relation, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(dynamic_id, evidence_id) DO UPDATE SET "
            "relation = excluded.relation",
            (dynamic_id, evidence_id, relation, updated_at),
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
        if result.status in {"success", "empty"}
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
