from __future__ import annotations

import random
import re
from typing import Any

import httpx

from .embeddings import StandardRuntimeError, bge_m3_embedding
from .standard_evolution import _parse_json
from .services import milvus_insert, milvus_search


GAME_TITLES = {
    "flashcard": "知识点卡片对对碰",
    "monopoly": "知识大富翁",
    "matching": "智识对弈",
}


def _matching_vector_text(point: dict[str, Any]) -> str:
    return " ".join(
        str(point.get(key, ""))
        for key in ("term", "definition", "fact", "expanded_text", "source_name")
    ).strip()


def _material_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\.[a-z0-9]{1,8}$", "", text)
    return re.sub(r"\W+", "", text)


def _resolve_source_material_id(raw_value: Any, materials: list[dict], point: dict[str, Any]) -> int:
    material_names = {int(item["id"]): str(item["name"]) for item in materials}
    try:
        source_id = int(raw_value)
        if source_id in material_names:
            return source_id
    except (TypeError, ValueError):
        pass

    raw_key = _material_key(raw_value)
    aliases: dict[str, int] = {}
    for material in materials:
        material_id = int(material["id"])
        name = str(material.get("name") or "")
        stem = name.rsplit(".", 1)[0]
        for alias in (material_id, name, stem):
            key = _material_key(alias)
            if key:
                aliases[key] = material_id

    if raw_key and raw_key in aliases:
        return aliases[raw_key]

    if raw_key:
        matches = [
            material_id
            for key, material_id in aliases.items()
            if len(raw_key) >= 4 and (raw_key in key or key in raw_key)
        ]
        if len(set(matches)) == 1:
            return matches[0]

    if len(materials) == 1:
        return int(materials[0]["id"])

    evidence = _material_key(" ".join(str(point.get(key, "")) for key in ("term", "definition", "fact", "expanded_text")))
    best: tuple[int, int] | None = None
    for material in materials:
        material_id = int(material["id"])
        haystack = _material_key(f"{material.get('name', '')} {material.get('category', '')} {str(material.get('content', ''))[:2000]}")
        score = 0
        for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", evidence):
            if token in haystack:
                score += min(len(token), 12)
        if best is None or score > best[1]:
            best = (material_id, score)
    if best and best[1] >= 6:
        return best[0]

    raise ValueError(f"Agent 返回了无法映射到已选素材的 source_material_id：{raw_value}")


async def agent_extract_knowledge(
    materials: list[dict],
    *,
    api_key: str,
    base_url: str,
    model: str = "deepseek-chat",
    proxy_url: str = "",
    requested_count: int = 10,
    purpose: str = "game",
) -> tuple[list[dict[str, Any]], str, str]:
    if not api_key.strip():
        raise ValueError("标准 Agent 模式缺少 DEEPSEEK_API_KEY，拒绝本地提取降级")
    requested_count = max(8, min(300, requested_count)) if purpose == "graph" else max(6, min(80, requested_count))
    source = "\n\n".join(
        f"[素材 {item['id']}: {item['name']}]\n{str(item['content'])[:12_000]}"
        for item in materials
    )[:60_000]
    if purpose == "graph":
        system = (
            "你是知识图谱核心词提取 Agent。只依据用户素材提取可独立成为节点的具体概念、"
            "方法、实体、机制或关键结论。term 必须是 2-5 个字的名词或专有名词，不能是句子、"
            "泛化词或连接词。只返回 JSON 对象，字段为 knowledge_points。每个对象必须包含 "
            "term、definition、fact、expanded_text、source_material_id、distractors。"
            "source_material_id 必须填写素材标题前方括号中的数字 ID，不能填写文件名或素材名。"
        )
    else:
        system = (
            "你是游戏题库知识提取 Agent。只依据用户素材提取适合学习游戏的核心知识。只返回 "
            "JSON 对象，字段为 knowledge_points。每个对象必须包含 term、definition、fact、"
            "expanded_text、source_material_id、distractors。definition 和 fact 必须能由原文支持，"
            "expanded_text 补充机制、关系、边界或应用，不得虚构事实。distractors 返回 2-3 个"
            "明确错误但类型相近的短文本。source_material_id 必须填写素材标题前方括号中的数字 ID，"
            "不能填写文件名或素材名。"
        )
    try:
        client_options: dict[str, Any] = {"timeout": httpx.Timeout(60.0, connect=15.0)}
        if proxy_url.strip():
            client_options["proxy"] = proxy_url.strip()
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key.strip()}"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": source}],
                    "temperature": 0.2,
                    "max_tokens": 16000 if purpose == "graph" else 8000,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
        parsed = _parse_json(str(raw))
        extracted = parsed.get("knowledge_points")
        if not isinstance(extracted, list):
            raise ValueError("Agent 未返回 knowledge_points 数组")
        material_names = {int(item["id"]): item["name"] for item in materials}
        points: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in extracted[:requested_count]:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term", "")).strip()[:80]
            definition = str(item.get("definition", "")).strip()[:500]
            fact = str(item.get("fact", definition)).strip()[:500]
            expanded_text = str(item.get("expanded_text", "")).strip()[:900]
            source_id = _resolve_source_material_id(item.get("source_material_id"), materials, item)
            key = re.sub(r"\W+", "", term).lower()
            if not term or not definition or not key or key in seen:
                continue
            seen.add(key)
            points.append({
                "term": term,
                "definition": definition,
                "fact": fact or definition,
                "expanded_text": expanded_text or f"{term}：{definition}",
                "source_material_id": source_id,
                "source_name": material_names[source_id],
                "distractors": [
                    str(value).strip()[:180]
                    for value in item.get("distractors", [])
                    if str(value).strip()
                ][:3],
            })
        if len(points) < 4:
            raise ValueError(f"Agent 有效知识点不足：{len(points)}")
        return points, "deepseek-agent", "已使用 DeepSeek JSON schema 提取并校验知识点"
    except Exception as exc:
        raise ValueError(f"标准知识提取 Agent 调用失败，未启用本地降级：{str(exc)[:180]}") from exc


def index_matching_points(points: list[dict[str, Any]], pack_id: int, user_id: int) -> str:
    chunks = []
    for index, point in enumerate(points):
        text = _matching_vector_text(point)
        point["expanded_text"] = point.get("expanded_text") or text
        point["vector_text"] = text
        chunks.append({
            "chunk_id": f"game-{pack_id}-{index}",
            "user_id": str(user_id),
            "doc_id": str(pack_id),
            "text": text[:65_000],
            "vector": bge_m3_embedding(text),
            "topics": str(point.get("term", ""))[:500],
        })
    if not milvus_insert(chunks):
        raise StandardRuntimeError("标准模式要求 Milvus 写入成功，但 matching 向量写入失败")
    return "milvus-cosine-bge-m3"


def _milvus_hit_score(hit: dict[str, Any]) -> float | None:
    score = hit.get("distance", hit.get("score"))
    if score is None and isinstance(hit.get("entity"), dict):
        score = hit["entity"].get("distance", hit["entity"].get("score"))
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def matching_round(points: list[dict[str, Any]], pack_id: int, user_id: int) -> dict[str, Any]:
    if len(points) < 2:
        raise ValueError("知识点数量不足，无法生成比对回合")
    left_index, right_index = random.SystemRandom().sample(range(len(points)), 2)
    left, right = points[left_index], points[right_index]
    left_vector = bge_m3_embedding(_matching_vector_text(left))
    similarity = sum(a * b for a, b in zip(left_vector, bge_m3_embedding(_matching_vector_text(right))))
    expected_chunk_id = f"game-{pack_id}-{right_index}"
    hits = milvus_search(left_vector, str(user_id), top_k=max(10, len(points)), doc_id=str(pack_id))
    if not hits:
        raise StandardRuntimeError("标准模式要求 Milvus 检索成功，但 matching 没有返回结果")
    for hit in hits:
        entity = hit.get("entity") if isinstance(hit.get("entity"), dict) else hit
        hit_id = str(hit.get("id") or hit.get("chunk_id") or entity.get("chunk_id") or "")
        if hit_id == expected_chunk_id:
            hit_score = _milvus_hit_score(hit)
            if hit_score is not None:
                similarity = hit_score
            break
    threshold = 0.72
    return {
        "pair": [
            {**left, "expanded_text": left.get("expanded_text") or _matching_vector_text(left)},
            {**right, "expanded_text": right.get("expanded_text") or _matching_vector_text(right)},
        ],
        "dimension": {
            "field": "vector_similarity",
            "label": "BGE-M3 向量语义相似度",
            "rule": "vector",
            "threshold": threshold,
        },
        "similarity": round(max(-1.0, min(1.0, similarity)), 4),
        "threshold": threshold,
        "correct_answer": "similar" if similarity >= threshold else "different",
        "vector_engine": "milvus-cosine-bge-m3",
    }


def build_game_questions(game: str, difficulty: str, points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if game not in GAME_TITLES:
        raise ValueError("不支持的游戏类型")
    counts = {"easy": 5, "medium": 6, "hard": 8}
    if game == "flashcard":
        counts = {"easy": 8, "medium": 6, "hard": 18}
    count = counts.get(difficulty, 6)
    selected = [points[index % len(points)] for index in range(count)]
    all_definitions = [item["definition"] for item in points]
    all_terms = [item["term"] for item in points]
    questions: list[dict[str, Any]] = []
    for index, point in enumerate(selected):
        if game == "matching":
            answer = point["term"]
            prompt = point["definition"]
            distractors = [term for term in all_terms if term != answer]
            question_type = "concept-definition"
        else:
            answer = point["definition"]
            prompt = f"关于“{point['term']}”，以下哪项最符合素材中的知识？"
            distractors = list(point.get("distractors") or [])
            distractors.extend(value for value in all_definitions if value != answer)
            question_type = "multiple-choice"
        options = [answer]
        for value in distractors:
            if value and value not in options:
                options.append(value)
            if len(options) >= 4:
                break
        if len(options) < 4:
            raise ValueError(f"知识点 {point['term']} 没有足够的标准干扰项")
        random.SystemRandom().shuffle(options)
        questions.append({
            "game": game,
            "difficulty": difficulty,
            "prompt": prompt,
            "options": options,
            "answer": answer,
            "explanation": point["fact"],
            "topic": point["term"],
            "question_type": question_type,
            "source_material_id": point["source_material_id"],
            "source_name": point["source_name"],
            "sequence": index + 1,
        })
    return questions
