from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Annotated, Callable, Optional
from urllib.parse import urlparse

from fastapi import Header, HTTPException

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class VisitorAIConfig:
    api_key: str
    model: str
    base_url: str
    resolved_ips: tuple[str, ...]
    api_mode: str = "responses"


def _public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return address.is_global and not any((
        address.is_private,
        address.is_loopback,
        address.is_link_local,
        address.is_multicast,
        address.is_reserved,
        address.is_unspecified,
    ))


def build_visitor_ai_config(
    api_key: str | None,
    model: str | None,
    base_url: str | None,
    api_mode: str | None = None,
    resolver: Callable = socket.getaddrinfo,
) -> VisitorAIConfig:
    key = (api_key or "").strip()
    model_name = (model or "").strip()
    url = (base_url or "").strip() or DEFAULT_OPENAI_BASE_URL
    if not key or len(key) > 512:
        raise HTTPException(status_code=400, detail="请填写有效的 API Key")
    if not model_name or len(model_name) > 128:
        raise HTTPException(status_code=400, detail="请填写有效的模型名称")
    if len(url) > 512:
        raise HTTPException(status_code=400, detail="API 地址过长")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="API 地址不是允许的公网地址") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="API 地址必须是不含凭据的 HTTPS 公网地址")
    if parsed.query or parsed.fragment or host == "localhost" or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="API 地址不是允许的公网地址")
    mode = (api_mode or "").strip().lower()
    if not mode:
        mode = "responses" if host == "api.openai.com" else "chat"
    if mode not in {"responses", "chat"}:
        raise HTTPException(status_code=400, detail="API 调用模式不受支持")
    try:
        addresses = [item[4][0] for item in resolver(host, parsed.port or 443, type=socket.SOCK_STREAM)]
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="无法解析 API 地址") from exc
    if not addresses or any(not _public_ip(value) for value in addresses):
        raise HTTPException(status_code=400, detail="API 地址不能指向本机或内网")
    return VisitorAIConfig(
        api_key=key,
        model=model_name,
        base_url=url.rstrip("/"),
        resolved_ips=tuple(dict.fromkeys(addresses)),
        api_mode=mode,
    )


def visitor_ai_config(
    api_key: Annotated[Optional[str], Header(alias="X-TB-API-Key")] = None,
    model: Annotated[Optional[str], Header(alias="X-TB-Model")] = None,
    base_url: Annotated[Optional[str], Header(alias="X-TB-Base-URL")] = None,
    api_mode: Annotated[Optional[str], Header(alias="X-TB-API-Mode")] = None,
) -> VisitorAIConfig:
    return build_visitor_ai_config(api_key, model, base_url, api_mode=api_mode)
