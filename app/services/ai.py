"""AI 分析服务：OpenAI Responses API 结构化输出、证据引用校验与 SSE 状态流。"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Generator
from urllib.parse import urlparse

import httpx

from .. import database as db
from ..config import settings
from .evidence import get_evidence
from .research_context import select_research_context
from .research_prompt import compose_research_prompt
from .visitor_ai import VisitorAIConfig


_EVIDENCE_IDS_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string"},
}

RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer_mode": {
            "type": "string",
            "enum": ["daily", "event", "question"],
        },
        "core_conclusion": {"type": "string"},
        "key_tension": {"type": "string"},
        "impact_state": {
            "type": "string",
            "enum": ["unaffected", "watch", "may_affect", "insufficient"],
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "body": {"type": "string"},
                    "evidence_ids": _EVIDENCE_IDS_SCHEMA,
                },
                "required": ["heading", "body", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence_ids": _EVIDENCE_IDS_SCHEMA,
                },
                "required": ["claim", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "impact_paths": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "evidence_ids": _EVIDENCE_IDS_SCHEMA,
                    "uncertainty": {"type": "string"},
                },
                "required": ["path", "evidence_ids", "uncertainty"],
                "additionalProperties": False,
            },
        },
        "inferences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence_ids": _EVIDENCE_IDS_SCHEMA,
                    "uncertainty": {"type": "string"},
                },
                "required": ["claim", "evidence_ids", "uncertainty"],
                "additionalProperties": False,
            },
        },
        "unknowns": {"type": "array", "items": {"type": "string"}},
        "watch_signals": {"type": "array", "items": {"type": "string"}},
        "thesis_relationship": {"type": "string"},
        "follow_up_question": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "safety_boundary": {"type": "string"},
    },
    "required": [
        "answer_mode", "core_conclusion", "key_tension", "impact_state",
        "sections", "facts", "impact_paths", "inferences", "unknowns",
        "watch_signals", "thesis_relationship", "follow_up_question",
        "confidence", "safety_boundary",
    ],
    "additionalProperties": False,
}

IMPACT_LABELS = {
    "unaffected": "暂未影响",
    "watch": "值得留意",
    "may_affect": "可能影响原判断",
    "insufficient": "信息不足",
}

TRADING_PATTERN = re.compile(
    r"(应该?买|应该?卖|建议买|建议卖|可以买|可以卖|买入|卖出|加仓|减仓|清仓|建仓|"
    r"止损|止盈|目标价|抄底|逃顶|满仓|建议持有|继续持有|耐心持有|坚定持有|"
    r"适合持有|推荐持有|控制仓位|调整仓位|保持仓位|降低仓位|提高仓位|"
    r"维持仓位|仓位控制|逢低(?:配置|布局|买入|加仓)|逢高(?:卖出|减仓|减持)|"
    r"分批(?:买入|卖出|建仓|配置)|"
    r"择机(?:买入|卖出|配置)|建议配置|可以配置|低吸|高抛|建议观望|继续观望|"
    r"建议暂避|\b(?:buy|sell|hold)\b)",
    re.IGNORECASE,
)

_SNAPSHOT_NUMERIC_FIELDS = {
    "price", "prev_close", "open", "high", "low", "change_pct", "volume",
    "amount", "pe_dynamic", "pb", "market_cap", "price_time", "fetched_at",
}
_SNAPSHOT_LOOKUP_KEYS = {"__market_snapshot__", "market_snapshot"}
_REFERENCE_FIELDS = {
    "sections": ("heading", "body"),
    "facts": ("claim",),
    "impact_paths": ("path", "uncertainty"),
    "inferences": ("claim", "uncertainty"),
}
_NUMERIC_TOKEN_PATTERN = re.compile(r"(?<![\d.])[-+]?\d[\d,]*(?:\.\d+)?%?")
_CONFLICT_UNKNOWN = "来源信息存在冲突，相关事实尚待进一步核验。"
_NO_CONFLICT_PATTERN = re.compile(r"(?:未发现|不存在|没有|无)(?:明显)?冲突")
_TITLE_ONLY_SAFE_PHRASES = (
    "仅有标题信息", "标题信息", "标题显示", "标题披露", "标题提及",
    "正文未提供", "正文缺失", "无法核验", "尚待核验", "待核验",
    "原因无法核验", "影响无法核验", "结果无法核验", "细节无法核验",
    "证据不足", "已确认判断", "等待后续公告", "后续公告",
    "后续披露", "补充公告", "尚不清楚", "不清楚", "未披露", "未知",
    "仅有标题", "仅标题", "标题", "正文", "信息", "证据", "相关事实",
)
_TITLE_ONLY_IGNORABLE_CHARS = "的了已与和及、但仅为是否可并对于于将尚待需"


class AIError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category  # timeout / quota / schema / model / network / unknown


def evidence_fingerprint(evidence_ids: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(evidence_ids)).encode("utf-8")).hexdigest()[:20]


def _pin_request_to_validated_ip(config: VisitorAIConfig):
    parsed = urlparse(config.base_url)
    expected_host = parsed.hostname or ""
    authority = expected_host
    if parsed.port and parsed.port != 443:
        authority = f"{authority}:{parsed.port}"

    def pin(request: httpx.Request) -> None:
        if request.url.host != expected_host:
            raise AIError("network", "模型请求目标与已验证地址不一致")
        request.headers["Host"] = authority
        request.extensions["sni_hostname"] = expected_host
        request.url = request.url.copy_with(host=config.resolved_ips[0])

    return pin


def _client(config: VisitorAIConfig):
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise AIError("unknown", "未安装 openai Python 包") from exc
    http_client = httpx.Client(
        follow_redirects=False,
        trust_env=False,
        timeout=settings.ai_timeout_seconds,
        event_hooks={"request": [_pin_request_to_validated_ip(config)]},
    )
    return OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=settings.ai_timeout_seconds,
        max_retries=1,
        http_client=http_client,
    )


def _close_client(client: Any) -> None:
    try:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


def _uses_zhipu_chat_api(config: VisitorAIConfig) -> bool:
    value = config.base_url.lower()
    return "bigmodel.cn" in value or "zhipu" in value


def _uses_chat_api(config: VisitorAIConfig) -> bool:
    # 保持对旧版手工构造 VisitorAIConfig 的兼容；请求依赖会为新配置显式设置 api_mode。
    return config.api_mode == "chat" or _uses_zhipu_chat_api(config)


def _zhipu_extra_body(config: VisitorAIConfig) -> dict[str, Any] | None:
    """仅为明确支持的智谱推理模型设置思考参数。"""
    if config.model.lower().startswith("glm-5.3"):
        # glm-5.3 强制思考，不能传 thinking=disabled；降低推理预算，
        # 给结构化 JSON 正文留出足够的 completion tokens。
        return {"reasoning_effort": "low"}
    # 普通模型（例如 glm-4-flash）不强行注入 thinking 参数，避免不同
    # 模型版本因不支持该扩展字段而直接返回 400。
    return None


def _parse_json_response(raw: Any) -> dict:
    """解析模型 JSON，兼容代码围栏和 JSON 前后的说明文字。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(getattr(item, "text", "") or ""))
        raw = "".join(parts)
    if not isinstance(raw, str):
        raise AIError("schema", "模型输出不是合法 JSON")

    text = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise AIError("schema", "模型输出不是合法 JSON")


def call_structured_model(
    config: VisitorAIConfig,
    instructions: str,
    context: dict,
    schema: dict[str, Any],
    schema_name: str,
    max_tokens: int = 2400,
) -> dict:
    """按指定 JSON Schema 调用模型，兼容 OpenAI Responses 与智谱 Chat API。"""
    client = _client(config)
    try:
        if _uses_chat_api(config):
            # 智谱兼容 OpenAI 的 Chat Completions，但不提供项目原先调用的
            # /responses 路径。使用 JSON mode，再由 validate_research_result 做字段
            # 和证据引用的二次校验。
            chat_kwargs = {
                "model": config.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{instructions}\n\n请严格返回 JSON，不要输出 Markdown。"
                            f"JSON 结构如下：{json.dumps(schema, ensure_ascii=False)}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(context, ensure_ascii=False, default=str),
                    },
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "max_tokens": max_tokens,
            }
            if _uses_zhipu_chat_api(config):
                extra_body = _zhipu_extra_body(config)
                if extra_body:
                    chat_kwargs["extra_body"] = extra_body
            response = client.chat.completions.create(**chat_kwargs)
            raw = response.choices[0].message.content
        else:
            response = client.responses.create(
                model=config.model,
                instructions=instructions,
                input=json.dumps(context, ensure_ascii=False, default=str),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    },
                },
                temperature=0.2,
                max_output_tokens=max_tokens,
            )
            raw = getattr(response, "output_text", None)
            if not raw:
                # 兼容不同 SDK 版本的输出结构
                chunks = []
                for item in getattr(response, "output", []) or []:
                    for part in getattr(item, "content", []) or []:
                        if getattr(part, "type", "") in ("output_text", "text"):
                            chunks.append(getattr(part, "text", ""))
                raw = "".join(chunks)
    except Exception as exc:
        text = str(exc)
        lowered = text.lower()
        if "timeout" in lowered or isinstance(exc, TimeoutError):
            raise AIError("timeout", "模型调用超时") from exc
        if "quota" in lowered or "insufficient" in lowered or "429" in text:
            raise AIError("quota", "模型额度或频率受限") from exc
        if "api key" in lowered or "401" in text or "403" in text:
            raise AIError("auth", "API Key 无效或没有模型权限") from exc
        if (
            ("model" in lowered and any(marker in lowered for marker in ("not found", "does not exist", "invalid")))
            or "模型不存在" in text
            or "模型不支持" in text
            or "1210" in text
        ):
            raise AIError("model", "模型名称不被该服务支持，请检查模型名称") from exc
        raise AIError("network", f"模型调用失败: {text[:200]}") from exc
    finally:
        _close_client(client)

    return _parse_json_response(raw)


def _call_model(config: VisitorAIConfig, instructions: str, context: dict) -> dict:
    """调用投研分析模型并解析严格研究结构。"""
    return call_structured_model(
        config,
        instructions,
        context,
        RESEARCH_SCHEMA,
        "grounded_research",
    )


def _expect_exact_object(
    value: Any, required: set[str], label: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AIError("schema", f"{label}必须是 JSON 对象")
    missing = sorted(required - set(value))
    if missing:
        raise AIError("schema", f"{label}缺少字段 {missing[0]}")
    extra = sorted(set(value) - required)
    if extra:
        raise AIError("schema", f"{label}包含额外字段 {extra[0]}")
    return value


def _expect_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise AIError("schema", f"{label}必须是字符串")
    return value


def _expect_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise AIError("schema", f"{label}必须是数组")
    for index, item in enumerate(value):
        _expect_string(item, f"{label}[{index}]")
    return value


def _canonical_number(token: str) -> str:
    normalized = unicodedata.normalize("NFKC", token).replace(",", "").rstrip("%")
    if normalized.startswith("+"):
        normalized = normalized[1:]
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return normalized
    if number == number.to_integral():
        return str(number.quantize(Decimal("1")))
    return format(number.normalize(), "f")


def _numeric_tokens(value: Any) -> set[str]:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return {_canonical_number(token) for token in _NUMERIC_TOKEN_PATTERN.findall(normalized)}


def _title_only_lexical_tokens(value: Any, *, remove_safe_phrases: bool) -> set[str]:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    if remove_safe_phrases:
        for phrase in sorted(_TITLE_ONLY_SAFE_PHRASES, key=len, reverse=True):
            normalized = normalized.replace(phrase, "")
        normalized = normalized.translate(
            str.maketrans("", "", _TITLE_ONLY_IGNORABLE_CHARS)
        )
    normalized = _NUMERIC_TOKEN_PATTERN.sub("", normalized)
    chinese = set(re.findall(r"[\u4e00-\u9fff]", normalized))
    latin = set(re.findall(r"[a-z][a-z0-9_.-]*", normalized))
    return chinese | latin


def _assert_title_only_supported(text: str, titles: list[str], label: str) -> None:
    source_text = " ".join(titles)
    unsupported_numbers = sorted(
        _numeric_tokens(text) - _numeric_tokens(source_text)
    )
    unsupported_terms = sorted(
        _title_only_lexical_tokens(text, remove_safe_phrases=True)
        - _title_only_lexical_tokens(source_text, remove_safe_phrases=False)
    )
    if unsupported_numbers or unsupported_terms:
        detail = unsupported_numbers[0] if unsupported_numbers else unsupported_terms[0]
        raise AIError("schema", f"{label}超出仅标题证据可支持的内容 {detail}")


def _snapshot_numeric_tokens(evidence_lookup: dict[str, dict]) -> set[str]:
    snapshot: dict[str, Any] = {}
    for key in _SNAPSHOT_LOOKUP_KEYS:
        candidate = evidence_lookup.get(key)
        if isinstance(candidate, dict):
            snapshot.update(candidate)
    tokens: set[str] = set()
    for field in _SNAPSHOT_NUMERIC_FIELDS:
        if field in snapshot:
            tokens.update(_numeric_tokens(snapshot[field]))
    return tokens


def _result_strings(value: Any) -> Generator[str, None, None]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _result_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _result_strings(child)


def validate_research_result(
    result: dict,
    evidence_lookup: dict[str, dict],
    conflict_status: str,
) -> tuple[dict, list[str]]:
    """严格校验模型研究输出；不修改或吞掉证据违规。"""
    top_fields = set(RESEARCH_SCHEMA["required"])
    _expect_exact_object(result, top_fields, "模型输出")
    cleaned = deepcopy(result)

    for field in (
        "core_conclusion", "key_tension", "thesis_relationship",
        "follow_up_question", "safety_boundary",
    ):
        _expect_string(cleaned[field], field)
    _expect_string(cleaned["answer_mode"], "answer_mode")
    _expect_string(cleaned["impact_state"], "impact_state")
    _expect_string(cleaned["confidence"], "confidence")
    if cleaned["answer_mode"] not in {"daily", "event", "question"}:
        raise AIError("schema", "answer_mode 非法")
    if cleaned["impact_state"] not in IMPACT_LABELS:
        raise AIError("schema", "impact_state 非法")
    if cleaned["confidence"] not in {"low", "medium", "high"}:
        raise AIError("schema", "confidence 非法")

    _expect_string_list(cleaned["unknowns"], "unknowns")
    _expect_string_list(cleaned["watch_signals"], "watch_signals")

    valid_evidence_ids = {
        evidence_id
        for evidence_id, evidence in evidence_lookup.items()
        if (
            isinstance(evidence_id, str)
            and evidence_id not in _SNAPSHOT_LOOKUP_KEYS
            and isinstance(evidence, dict)
        )
    }
    item_fields = {
        "sections": {"heading", "body", "evidence_ids"},
        "facts": {"claim", "evidence_ids"},
        "impact_paths": {"path", "evidence_ids", "uncertainty"},
        "inferences": {"claim", "evidence_ids", "uncertainty"},
    }
    for collection, required in item_fields.items():
        items = cleaned[collection]
        if not isinstance(items, list):
            raise AIError("schema", f"{collection}必须是数组")
        for index, item in enumerate(items):
            label = f"{collection}[{index}]"
            _expect_exact_object(item, required, label)
            for field in required - {"evidence_ids"}:
                _expect_string(item[field], f"{label}.{field}")
            evidence_ids = _expect_string_list(
                item["evidence_ids"], f"{label}.evidence_ids"
            )
            if collection == "facts" and not evidence_ids:
                raise AIError("schema", f"{label}必须引用至少一条证据")
            invalid_ids = [
                evidence_id
                for evidence_id in evidence_ids
                if evidence_id not in valid_evidence_ids
            ]
            if invalid_ids:
                raise AIError("schema", f"{label}引用了无效证据 {invalid_ids[0]}")

    public_evidence = {
        evidence_id: evidence_lookup[evidence_id]
        for evidence_id in valid_evidence_ids
    }
    all_evidence_is_title_only = bool(public_evidence) and all(
        evidence.get("content_status") == "title_only"
        for evidence in public_evidence.values()
    )
    all_titles = [str(evidence.get("title") or "") for evidence in public_evidence.values()]
    if all_evidence_is_title_only:
        global_title_fields = (
            "core_conclusion", "key_tension", "thesis_relationship",
        )
        for field in global_title_fields:
            _assert_title_only_supported(cleaned[field], all_titles, field)
        for field in ("watch_signals", "unknowns"):
            for index, text in enumerate(cleaned[field]):
                _assert_title_only_supported(text, all_titles, f"{field}[{index}]")

    for collection, text_fields in _REFERENCE_FIELDS.items():
        for index, item in enumerate(cleaned[collection]):
            cited = [public_evidence[evidence_id] for evidence_id in item["evidence_ids"]]
            title_only_scope = (
                cited
                if cited and all(evidence.get("content_status") == "title_only" for evidence in cited)
                else list(public_evidence.values()) if not cited and all_evidence_is_title_only
                else []
            )
            if not title_only_scope:
                continue
            titles = [str(evidence.get("title") or "") for evidence in title_only_scope]
            text = " ".join(item[field] for field in text_fields)
            _assert_title_only_supported(text, titles, f"{collection}[{index}]")

    snapshot_numbers = _snapshot_numeric_tokens(evidence_lookup)
    for collection in ("facts", "sections"):
        for index, item in enumerate(cleaned[collection]):
            text = " ".join(item[field] for field in _REFERENCE_FIELDS[collection])
            claimed_numbers = _numeric_tokens(text)
            if not claimed_numbers:
                continue
            supported_numbers = set(snapshot_numbers)
            cited_numbers: set[str] = set()
            has_title_only_reference = False
            for evidence_id in item["evidence_ids"]:
                evidence = evidence_lookup[evidence_id]
                evidence_numbers = _numeric_tokens(evidence.get("title"))
                evidence_numbers.update(_numeric_tokens(evidence.get("excerpt")))
                supported_numbers.update(evidence_numbers)
                cited_numbers.update(evidence_numbers)
                if evidence.get("content_status") == "title_only":
                    has_title_only_reference = True
            if has_title_only_reference:
                title_only_unsupported = sorted(claimed_numbers - cited_numbers)
                if title_only_unsupported:
                    raise AIError(
                        "schema",
                        f"{collection}[{index}]为仅标题证据添加了数字 "
                        f"{title_only_unsupported[0]}",
                    )
            unsupported = sorted(claimed_numbers - supported_numbers)
            if unsupported:
                raise AIError(
                    "schema",
                    f"{collection}[{index}]包含证据或行情快照未支持的数字 {unsupported[0]}",
                )

    if any(TRADING_PATTERN.search(text) for text in _result_strings(cleaned)):
        raise AIError("schema", "模型输出包含交易指令")

    notes: list[str] = []
    if conflict_status == "possible":
        cleaned["confidence"] = "low"
        cleaned["impact_state"] = "insufficient"
        cleaned["unknowns"] = [
            item for item in cleaned["unknowns"]
            if item != _CONFLICT_UNKNOWN and not _NO_CONFLICT_PATTERN.search(item)
        ]
        cleaned["unknowns"].append(_CONFLICT_UNKNOWN)
        notes.append("来源存在冲突，已将置信度降为 low 并标记信息不足")
    return cleaned, notes


def _sse(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _adapt_legacy_stream_context(
    asset: dict | None,
    question: str | None,
    event: dict | None,
    evidence_items: list[dict] | None,
    thesis: dict | None,
    recent_messages: list[dict] | None,
    snapshot: dict | None,
) -> tuple[dict, str]:
    """将 Task 5 之前的路由参数收敛为 Task 3 的有界上下文。"""
    if not isinstance(asset, dict):
        raise AIError("schema", "缺少研究标的上下文")
    selected_evidence = list(evidence_items or [])
    selected_event = deepcopy(event) if isinstance(event, dict) else None
    if selected_event is not None:
        selected_event["evidence"] = selected_evidence
    context = select_research_context(
        asset=asset,
        question=str(question or ""),
        snapshot=snapshot,
        selected_event=selected_event,
        daily_brief={},
        evidence_items=selected_evidence,
        thesis=thesis,
        recent_messages=list(recent_messages or []),
    )
    if selected_event and selected_event.get("event_id"):
        context.setdefault("selected_event", {})["event_id"] = selected_event["event_id"]
    legacy_conflict_status = str((selected_event or {}).get("conflict_status") or "none")
    return context, legacy_conflict_status


def run_grounded_stream(
    config: VisitorAIConfig,
    mode: str,
    context: dict | None = None,
    conflict_status: str | None = None,
    *,
    asset: dict | None = None,
    question: str | None = None,
    event: dict | None = None,
    evidence_items: list[dict] | None = None,
    thesis: dict | None = None,
    recent_messages: list[dict] | None = None,
    snapshot: dict | None = None,
) -> Generator[str, None, None]:
    """执行一次真实模型调用，按 SSE 状态推进，结束时产出 completed / failed 事件。"""
    prompt_mode = "event" if mode == "research" else mode
    instructions = compose_research_prompt(prompt_mode)
    if context is None:
        context, legacy_conflict_status = _adapt_legacy_stream_context(
            asset, question, event, evidence_items, thesis, recent_messages, snapshot
        )
        if conflict_status is None:
            conflict_status = legacy_conflict_status
    if conflict_status is None:
        conflict_status = "none"
    model_context = deepcopy(context)
    evidence_items = [
        item for item in model_context.get("evidence", [])
        if isinstance(item, dict) and str(item.get("evidence_id") or "").strip()
    ]
    lookup = {str(item["evidence_id"]): item for item in evidence_items}
    validation_lookup = dict(lookup)
    snapshot = model_context.get("market_snapshot")
    if isinstance(snapshot, dict):
        validation_lookup["__market_snapshot__"] = snapshot
    fingerprint = evidence_fingerprint(list(lookup))
    selected_event = model_context.get("selected_event")
    selected_event = selected_event if isinstance(selected_event, dict) else {}
    thesis = model_context.get("confirmed_thesis")
    thesis_version = thesis.get("version") if isinstance(thesis, dict) else None
    question = str(model_context.get("question") or "")

    yield _sse("status", {"state": "context_ready", "evidence_count": len(lookup)})

    yield _sse("status", {"state": "model_running", "model": config.model})
    result: dict | None = None
    last_error: AIError | None = None
    for attempt in range(2):  # 校验失败允许重试一次
        try:
            candidate = _call_model(config, instructions, model_context)
        except AIError as exc:
            last_error = exc
            if exc.category != "schema" or attempt == 1:
                break  # 网络/额度类错误重试无意义
            model_context["validation_feedback"] = (
                f"上一次输出无法解析（{exc}）。"
                "请严格返回符合 Schema 的 JSON，不要输出 Markdown 或说明文字。"
            )
            continue
        try:
            yield _sse("status", {"state": "validating"})
            result, _notes = validate_research_result(
                candidate, validation_lookup, conflict_status
            )
            break
        except AIError as exc:
            last_error = exc
            result = None
            if attempt == 1:
                break
            model_context["validation_feedback"] = (
                f"上一次输出未通过研究校验（{exc}）。"
                "请仅使用已提供证据并严格按 Schema 修复后重新输出。"
            )

    if result is None:
        category = last_error.category if last_error else "schema"
        message = str(last_error) if last_error else "本次分析未通过证据校验"
        yield _sse("failed", {"category": category, "message": message})
        return

    compatibility_result = {
        **result,
        "conclusion": result["core_conclusion"],
        "next_checks": list(result["watch_signals"]),
    }
    referenced_ids = sorted({
        evidence_id
        for collection in ("sections", "facts", "impact_paths", "inferences")
        for item in result[collection]
        for evidence_id in item["evidence_ids"]
    })
    yield _sse("completed", {
        "mode": mode,
        "question": question,
        "event_id": selected_event.get("event_id") or selected_event.get("cluster_id"),
        "cluster_id": selected_event.get("cluster_id"),
        "evidence_fingerprint": fingerprint,
        "thesis_version": thesis_version,
        "model": config.model,
        "created_at": db.utcnow(),
        "result": compatibility_result,
        "impact_label": IMPACT_LABELS.get(result["impact_state"], "信息不足"),
        "evidence": [
            evidence
            for evidence in (get_evidence(evidence_id) for evidence_id in referenced_ids)
            if evidence
        ],
    })
