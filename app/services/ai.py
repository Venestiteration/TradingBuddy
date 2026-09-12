"""AI 分析服务：OpenAI Responses API 结构化输出、证据引用校验与 SSE 状态流。"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Generator

from .. import database as db
from ..config import settings
from .evidence import get_evidence

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "conclusion": {"type": "string"},
        "impact_state": {
            "type": "string",
            "enum": ["unaffected", "watch", "may_affect", "insufficient"],
        },
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["claim", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "inferences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "uncertainty": {"type": "string"},
                },
                "required": ["claim", "evidence_ids", "uncertainty"],
                "additionalProperties": False,
            },
        },
        "unknowns": {"type": "array", "items": {"type": "string"}},
        "next_checks": {"type": "array", "items": {"type": "string"}},
        "safety_boundary": {"type": "string"},
    },
    "required": [
        "conclusion", "impact_state", "facts", "inferences",
        "unknowns", "next_checks", "safety_boundary",
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
    r"止损|止盈|目标价|抄底|逃顶|满仓)"
)


class AINotConfigured(RuntimeError):
    pass


class AIError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category  # timeout / quota / schema / network / unknown


def is_configured() -> bool:
    return bool(settings.openai_api_key and settings.openai_model)


def evidence_fingerprint(evidence_ids: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(evidence_ids)).encode("utf-8")).hexdigest()[:20]


def _client():
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise AIError("unknown", "未安装 openai Python 包") from exc
    return OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.ai_timeout_seconds,
        max_retries=1,
    )


def _call_model(instructions: str, context: dict) -> dict:
    """调用 Responses API 并解析 JSON。失败抛 AIError。"""
    client = _client()
    try:
        response = client.responses.create(
            model=settings.openai_model,
            instructions=instructions,
            input=json.dumps(context, ensure_ascii=False, default=str),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "grounded_analysis",
                    "strict": True,
                    "schema": ANALYSIS_SCHEMA,
                }
            },
            temperature=0.2,
            max_output_tokens=2400,
        )
    except Exception as exc:
        text = str(exc)
        if "timeout" in text.lower() or isinstance(exc, TimeoutError):
            raise AIError("timeout", "模型调用超时") from exc
        if "quota" in text.lower() or "insufficient" in text.lower() or "429" in text:
            raise AIError("quota", "模型额度或频率受限") from exc
        if "api key" in text.lower() or "401" in text:
            raise AIError("network", "API Key 无效或未配置") from exc
        raise AIError("network", f"模型调用失败: {text[:200]}") from exc

    raw = getattr(response, "output_text", None)
    if not raw:
        # 兼容不同 SDK 版本的输出结构
        chunks = []
        for item in getattr(response, "output", []) or []:
            for part in getattr(item, "content", []) or []:
                if getattr(part, "type", "") in ("output_text", "text"):
                    chunks.append(getattr(part, "text", ""))
        raw = "".join(chunks)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AIError("schema", "模型输出不是合法 JSON") from exc


def validate_result(result: dict, evidence_lookup: dict[str, dict]) -> tuple[dict, list[str]]:
    """校验并清洗结构化输出。返回 (清洗后结果, 处理说明)。"""
    notes: list[str] = []

    if not isinstance(result, dict):
        raise AIError("schema", "模型输出不是 JSON 对象")
    for field in ("conclusion", "impact_state", "facts", "inferences",
                  "unknowns", "next_checks", "safety_boundary"):
        if field not in result:
            raise AIError("schema", f"缺少字段 {field}")
    if result["impact_state"] not in IMPACT_LABELS:
        notes.append("impact_state 非法，已降级为 insufficient")
        result["impact_state"] = "insufficient"

    def clean_refs(items: list, kind: str) -> list[dict]:
        cleaned = []
        for item in items:
            if not isinstance(item, dict) or not str(item.get("claim", "")).strip():
                continue
            valid_ids, had_invalid = [], False
            for evidence_id in item.get("evidence_ids") or []:
                if evidence_id in evidence_lookup:
                    valid_ids.append(evidence_id)
                else:
                    had_invalid = True
            if had_invalid:
                notes.append(f"{kind}中存在无效证据编号，已删除")
            cleaned.append({
                "claim": str(item["claim"]).strip(),
                "evidence_ids": valid_ids,
                **({"uncertainty": str(item.get("uncertainty", "")).strip()}
                   if "uncertainty" in item or kind == "inferences" else {}),
            })
        return cleaned

    facts = clean_refs(result.get("facts") or [], "已知事实")
    # 无有效引用的事实不得进入"已知事实"
    facts = [fact for fact in facts if fact["evidence_ids"]]
    inferences = clean_refs(result.get("inferences") or [], "推断")

    only_title_evidence = all(
        evidence.get("content_status") == "title_only"
        for evidence in evidence_lookup.values()
    ) and bool(evidence_lookup)
    if only_title_evidence and facts:
        notes.append("本次证据仅有标题，正文级事实已降级为推断")
        for fact in facts:
            fact["claim"] = f"（标题信息）{fact['claim']}"
        inferences = [{"claim": fact["claim"], "evidence_ids": fact["evidence_ids"],
                       "uncertainty": "仅有标题，无法核验细节"} for fact in facts]
        facts = []

    result["facts"] = facts
    result["inferences"] = inferences
    result["unknowns"] = [str(item) for item in (result.get("unknowns") or []) if str(item).strip()]
    result["next_checks"] = [str(item) for item in (result.get("next_checks") or []) if str(item).strip()]
    result["safety_boundary"] = str(result.get("safety_boundary") or "").strip() or (
        "以上为研究信息整理，不构成投资建议。"
    )

    if TRADING_PATTERN.search(str(result.get("conclusion", ""))):
        result["conclusion"] = (
            "（以下为条件化分析，非交易指令）" + str(result["conclusion"])
        )
        notes.append("结论涉及交易指令表述，已改为条件化分析")

    # 证据不足时强制降级
    if not facts and result["impact_state"] not in ("insufficient",):
        result["impact_state"] = "insufficient"
        notes.append("无有效引用事实，影响状态降级为 insufficient")
    return result, notes


def _build_context(
    code: str,
    name: str,
    question: str,
    snapshot: dict | None,
    event: dict | None,
    evidence_items: list[dict],
    thesis: dict | None,
    recent_messages: list[dict],
) -> dict:
    context: dict[str, Any] = {
        "stock": {"code": code, "name": name},
        "question": question,
        "product_boundary": "仅做研究信息整理；禁止买卖建议、目标价与交易时点；输出为中文结构化 JSON。",
    }
    if snapshot:
        context["market_snapshot"] = {
            key: snapshot.get(key)
            for key in ("price", "prev_close", "open", "high", "low", "change_pct",
                        "volume", "amount", "pe_dynamic", "pb", "price_time")
        }
    if event:
        context["event"] = {
            "event_id": event.get("event_id"),
            "title": event.get("title"),
            "published_at": event.get("published_at"),
            "source_type": event.get("source_type"),
        }
    context["evidence"] = [
        {
            "evidence_id": item["evidence_id"],
            "source_type": item["source_type"],
            "source_level": item["source_level"],
            "title": item["title"],
            "excerpt": item["excerpt"],
            "published_at": item["published_at"],
            "content_status": item["content_status"],
        }
        for item in evidence_items
    ]
    if thesis:
        context["user_thesis"] = {
            "version": thesis.get("version"),
            "core_thesis": thesis.get("core_thesis"),
            "watch_variables": thesis.get("watch_variables"),
            "invalid_conditions": thesis.get("invalid_conditions"),
        }
    if recent_messages:
        context["recent_messages"] = recent_messages[-6:]
    return context


def _sse(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def run_grounded_stream(
    mode: str,                      # research / chat
    asset: dict,
    question: str,
    event: dict | None,
    evidence_items: list[dict],
    thesis: dict | None,
    recent_messages: list[dict],
    snapshot: dict | None,
    save_result: Callable[[dict, str], int] | None = None,
) -> Generator[str, None, None]:
    """执行一次真实模型调用，按 SSE 状态推进，结束时产出 completed / failed 事件。"""
    instructions = settings.prompt_path.read_text(encoding="utf-8")
    code, name = asset["stock_code"], asset["stock_name"]
    lookup = {item["evidence_id"]: item for item in evidence_items}
    context = _build_context(code, name, question, snapshot, event, evidence_items,
                             thesis, recent_messages)
    fingerprint = evidence_fingerprint(list(lookup.keys()))
    thesis_version = (thesis or {}).get("version")

    yield _sse("status", {"state": "context_ready", "evidence_count": len(lookup)})

    if not is_configured():
        yield _sse("failed", {
            "category": "not_configured",
            "message": "尚未配置 OPENAI_API_KEY 或 OPENAI_MODEL，请在 .env 中配置后重启服务。当前仅可查看行情、事件与原始来源。",
        })
        return

    yield _sse("status", {"state": "model_running", "model": settings.openai_model})
    result: dict | None = None
    last_error: AIError | None = None
    for attempt in range(2):  # 校验失败允许重试一次
        try:
            candidate = _call_model(instructions, context)
        except AIError as exc:
            last_error = exc
            break  # 网络/额度类错误重试无意义
        try:
            yield _sse("status", {"state": "validating"})
            result, notes = validate_result(candidate, lookup)
            if notes and attempt == 0:
                context["validation_feedback"] = (
                    f"上一次输出存在以下问题，请修正后重新输出：{'；'.join(notes)}"
                )
                result = None
                continue
            break
        except AIError as exc:
            last_error = exc
            if attempt == 1:
                break
            context["validation_feedback"] = f"上一次输出不符合 Schema（{exc}），请严格按 Schema 输出。"

    if result is None:
        category = last_error.category if last_error else "schema"
        message = last_error.message if last_error else "本次分析未通过证据校验"
        yield _sse("failed", {"category": category, "message": message})
        return

    analysis_id = None
    if save_result:
        analysis_id = save_result(result, fingerprint)
    yield _sse("completed", {
        "mode": mode,
        "question": question,
        "analysis_id": analysis_id,
        "event_id": (event or {}).get("event_id"),
        "evidence_fingerprint": fingerprint,
        "thesis_version": thesis_version,
        "model": settings.openai_model,
        "created_at": db.utcnow(),
        "result": result,
        "impact_label": IMPACT_LABELS.get(result["impact_state"], "信息不足"),
        "evidence": [item for item in (get_evidence(eid) or {} for eid in
                                       sorted({eid for fact in result["facts"]
                                               for eid in fact["evidence_ids"]}))],
    })
