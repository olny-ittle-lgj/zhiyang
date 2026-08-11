from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


class MaterialQaAgentError(Exception):
    """Raised when the material QA agent cannot produce a usable result."""


@dataclass
class MaterialExcerpt:
    index: int
    text: str
    score: float


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _question_terms(question: str) -> set[str]:
    lowered = question.lower()
    terms = {item for item in re.findall(r"[a-z0-9_]{2,}", lowered)}
    cjk = re.findall(r"[\u4e00-\u9fff]", question)
    terms.update(cjk)
    terms.update("".join(cjk[index:index + 2]) for index in range(max(0, len(cjk) - 1)))
    return {term for term in terms if term}


def _split_material(content: str) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", content or "") if item.strip()]
    if len(paragraphs) < 2:
        paragraphs = [item.strip() for item in re.split(r"(?<=[。！？.!?])\s*", content or "") if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) <= 900:
            current = f"{current}\n{paragraph}".strip()
        else:
            if current:
                chunks.append(current)
            current = paragraph[:1400]
    if current:
        chunks.append(current)
    return chunks or [content[:1400]]


def find_relevant_excerpts(content: str, question: str, limit: int = 3) -> list[MaterialExcerpt]:
    chunks = _split_material(content)
    terms = _question_terms(question)
    scored: list[MaterialExcerpt] = []
    for index, chunk in enumerate(chunks, start=1):
        normalized = _normalize_text(chunk).lower()
        score = 0.0
        for term in terms:
            if term in normalized:
                score += 2.0 if len(term) > 1 else 0.45
        if question.strip() and question.strip().lower() in normalized:
            score += 8.0
        if score > 0:
            scored.append(MaterialExcerpt(index=index, text=chunk.strip(), score=score))
    if not scored and chunks:
        scored.append(MaterialExcerpt(index=1, text=chunks[0].strip(), score=0))
    return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]


def _fallback_answer(question: str, excerpts: list[MaterialExcerpt]) -> str:
    if not excerpts or excerpts[0].score <= 0:
        return "当前素材中没有检索到与问题直接对应的内容。建议换一个更贴近原文关键词的问题，或先补充该素材的正文信息。"
    points = []
    for excerpt in excerpts:
        text = _normalize_text(excerpt.text)
        if text:
            points.append(text[:220])
    joined = "；".join(points[:2])
    return f"根据检索到的原文片段，可以这样理解：{joined}。以上解释仅依据当前素材原文生成。"


def _parse_agent_json(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.S | re.I)
    if match:
        cleaned = match.group(1).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise MaterialQaAgentError("Material QA Agent 必须返回 JSON object")
    return data


async def answer_material_question(
    material: dict[str, Any],
    question: str,
    *,
    api_key: str = "",
    base_url: str = "",
    model: str = "deepseek-chat",
    proxy_url: str = "",
) -> dict[str, Any]:
    content = str(material.get("content") or "").strip()
    if not content:
        raise MaterialQaAgentError("当前素材没有可问答的正文内容")

    excerpts = find_relevant_excerpts(content, question)
    original_content = "\n\n".join(excerpt.text for excerpt in excerpts).strip()
    if not original_content:
        original_content = content[:1200]

    if not api_key:
        return {
            "answer": _fallback_answer(question, excerpts),
            "original_content": original_content,
            "excerpts": [excerpt.__dict__ for excerpt in excerpts],
            "mode": "local-material-agent",
            "agent_note": "未配置 DEEPSEEK_API_KEY，已使用本地素材问答 Agent。",
        }

    prompt = {
        "material": {
            "name": material.get("name", ""),
            "kind": material.get("kind", ""),
            "category": material.get("category", ""),
        },
        "question": question,
        "original_excerpts": original_content,
    }
    try:
        import httpx

        client_options: dict[str, Any] = {"timeout": 60}
        if proxy_url.strip():
            client_options["proxy"] = proxy_url.strip()
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是单文档问答 Agent。只能依据给定 original_excerpts 回答。"
                                "返回 JSON object，字段为 polished_answer。"
                                "如果片段不足以回答，明确说明原文没有直接依据，并给出可追问方向。"
                            ),
                        },
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1000,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            parsed = _parse_agent_json(str(raw))
            answer = str(parsed.get("polished_answer") or "").strip()
            if not answer:
                raise MaterialQaAgentError("Material QA Agent 返回空答案")
    except Exception as exc:
        return {
            "answer": _fallback_answer(question, excerpts),
            "original_content": original_content,
            "excerpts": [excerpt.__dict__ for excerpt in excerpts],
            "mode": "local-material-agent",
            "agent_note": f"DeepSeek Agent 调用失败，已使用本地 Agent：{str(exc)[:160]}",
        }

    return {
        "answer": answer,
        "original_content": original_content,
        "excerpts": [excerpt.__dict__ for excerpt in excerpts],
        "mode": "deepseek-material-agent",
        "agent_note": "已使用 DeepSeek 单素材问答 Agent 润色解释。",
    }
