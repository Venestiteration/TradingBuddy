from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

PROVIDER_CNINFO = "cninfo"
PROVIDER_EASTMONEY_NOTICES = "eastmoney_notices"
PROVIDER_EASTMONEY_NEWS = "eastmoney_news"
OFFICIAL_PROVIDERS = frozenset({PROVIDER_CNINFO, PROVIDER_EASTMONEY_NOTICES})
MEDIA_PROVIDERS = frozenset({PROVIDER_EASTMONEY_NEWS})
PUBLIC_DYNAMICS_FORMULA_VERSION = "public-dynamics-v1"

ProviderStatus = Literal["success", "empty", "failed"]
DynamicKind = Literal["announcement", "news"]


@dataclass(frozen=True)
class RawDynamic:
    provider: str
    provider_item_id: str
    stock_code: str
    kind: DynamicKind
    category: str
    title: str
    excerpt: str
    published_at: str
    publisher: str
    source_url: str
    document_url: str | None = None
    source_level: Literal["primary", "secondary"] = "secondary"
    content_status: Literal["title_only", "excerpt", "full"] = "title_only"
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    status: ProviderStatus
    items: tuple[RawDynamic, ...]
    attempted_at: str
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DynamicCluster:
    canonical_key: str
    kind: DynamicKind
    category: str
    title: str
    summary: str
    published_at: str
    importance_score: float
    importance_factors: dict[str, float]
    content_status: str
    conflict_status: Literal["none", "possible"]
    members: tuple[RawDynamic, ...]


@dataclass(frozen=True)
class SyncDecision:
    should_sync: bool
    reason: str
