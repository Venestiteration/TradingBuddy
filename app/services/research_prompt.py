from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]

PROMPT_FILES = {
    "constitution": ROOT_DIR / "prompts" / "product_constitution.md",
    "soul": ROOT_DIR / "prompts" / "research_soul.md",
    "tasks": ROOT_DIR / "prompts" / "research_tasks.md",
}


def compose_research_prompt(mode: str) -> str:
    """Compose the immutable prompt layers in their required priority order."""
    if mode not in {"daily", "event", "chat"}:
        raise ValueError(f"unsupported research mode: {mode}")
    layers = [
        PROMPT_FILES[name].read_text(encoding="utf-8").strip()
        for name in ("constitution", "soul", "tasks")
    ]
    return "\n\n".join([*layers, f"当前任务模式：{mode}"])
