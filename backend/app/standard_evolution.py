from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, TypedDict

import httpx


class EvolutionAgentError(RuntimeError):
    """Raised when the LangGraph evolution workflow cannot finish safely."""


class EvolutionState(TypedDict, total=False):
    material: dict[str, Any]
    content: str
    analysis: dict[str, Any]
    expansion: dict[str, Any]
    draft: str
    agent_review: dict[str, Any]
    issues: list[str]
    missing_points: list[str]
    retry_count: int


def _parse_json(value: str) -> dict[str, Any]:
    text = value.strip()
    match = re.search(r"```(?:json|markdown|md)?\s*(.*?)\s*```", text, flags=re.I | re.S)
    if match:
        text = match.group(1).strip()
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]

    last_error = ""
    for attempt in range(3):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = str(exc)[:160]
            if attempt == 0:
                # 尝试1：修复未闭合的字符串 — 在最后一个完整引号后补上关闭引号和括号
                text = _repair_truncated_json(text)
            elif attempt == 1:
                # 尝试2：去掉不完整的最后一行，补上括号
                text = _repair_truncated_json(text, aggressive=True)
            else:
                raise EvolutionAgentError(f"Agent JSON 解析失败：{last_error}") from exc
        else:
            break

    if not isinstance(parsed, dict):
        raise EvolutionAgentError("Agent 必须返回 JSON object")
    return parsed


def _repair_truncated_json(text: str, *, aggressive: bool = False) -> str:
    """Attempt to repair a JSON string that was truncated mid-response."""
    text = text.rstrip()
    if not text.endswith("}"):
        # Count open vs closed brackets
        open_braces = text.count("{") - text.count("}")
        open_brackets = text.count("[") - text.count("]")
        # Check for unterminated string: odd number of unescaped quotes
        in_string = False
        escaped = False
        last_complete_string_end = 0
        for i, ch in enumerate(text):
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                if not in_string:
                    last_complete_string_end = i + 1

        if in_string or aggressive:
            # Truncated inside a string or aggressive mode — cut back to last complete position
            if last_complete_string_end > 0:
                text = text[:last_complete_string_end].rstrip().rstrip(",")
            # Close any remaining open structures
            open_braces = text.count("{") - text.count("}")
            open_brackets = text.count("[") - text.count("]")
            text += "]" * max(0, open_brackets)
            text += "}" * max(0, open_braces)
        elif open_brackets > 0 or open_braces > 0:
            text += "]" * max(0, open_brackets)
            text += "}" * max(0, open_braces)
    return text


def _string_list(value: Any, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        key = re.sub(r"\s+", "", text).lower()
        if text and key not in seen:
            result.append(text[:500])
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _quality(original: str, evolved: str, key_points: list[str]) -> tuple[bool, list[str], list[str], float]:
    issues: list[str] = []
    minimum = max(int(len(original) * 1.35), len(original) + 300) if len(original) <= 6000 else len(original) + 500
    if len(evolved) < minimum:
        issues.append(f"正文扩展不足，当前 {len(evolved)} 字，至少需要 {minimum} 字")
    if len(re.findall(r"(?m)^#{1,4}\s+\S+", evolved)) < 4:
        issues.append("Markdown 结构不足，至少需要 4 个标题")

    # 关键词级覆盖率检测：用 key_point 中的关键词 token 匹配，而非整句子串
    doc_lower = evolved.lower()
    missing = _find_missing_points(key_points, doc_lower)
    if len(missing) > max(0, len(key_points) // 4):
        issues.append(f"核心知识点覆盖不足，缺少 {len(missing)} 项：" + "；".join(missing[:8]))

    normalized = re.sub(r"[\W_]+", "", evolved, flags=re.UNICODE).lower()
    similarity = SequenceMatcher(
        None,
        re.sub(r"[\W_]+", "", original, flags=re.UNICODE).lower(),
        normalized,
    ).ratio()
    if len(original) >= 80 and similarity > 0.88:
        issues.append(f"与原文相似度过高：{similarity:.0%}")
    if not re.search(r"(?m)^#{1,4}\s+.*(示例|应用|实践|案例)", evolved):
        issues.append("缺少示例或应用章节")
    if not re.search(r"(?m)^#{1,4}\s+.*(边界|注意|局限|风险|误区)", evolved):
        issues.append("缺少边界、注意事项或风险章节")
    return not issues, issues, missing if len(missing) > max(0, len(key_points) // 4) else [], similarity


def _extract_tokens(text: str) -> list[str]:
    """Extract meaningful keyword tokens from a key_point for fuzzy matching."""
    tokens: list[str] = []
    # Single CJK characters, excluding common stop characters
    stop_chars = set("的是在了不和这那我有他她它什么怎么就也都还对从到把将被而可已与如无虽然于及个以们要为以但到")
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.extend(ch for ch in cjk_chars if ch not in stop_chars)
    # English words >= 2 chars (e.g. TypeScript, JSON, API)
    alpha_words = re.findall(r"[a-zA-Z]{2,}", text)
    tokens.extend(w.lower() for w in alpha_words)
    # Digits/symbols combos like ES6, Vue3
    tech_terms = re.findall(r"[A-Za-z]+\d+|\d+[A-Za-z]+", text)
    tokens.extend(t.lower() for t in tech_terms)
    return list(dict.fromkeys(tokens))  # deduplicate, preserve order


def _point_covered(point: str, doc_lower: str) -> bool:
    """Check if a key_point is reasonably covered via keyword-token overlap."""
    tokens = _extract_tokens(point)
    if not tokens:
        # Fallback: check if point text appears as substring
        return re.sub(r"[\W_]+", "", point, flags=re.UNICODE).lower() in re.sub(r"[\W_]+", "", doc_lower, flags=re.UNICODE)
    matched = sum(1 for t in tokens if t in doc_lower)
    # Require >= 50% of tokens to be present
    return matched >= max(1, len(tokens) // 2)


def _find_missing_points(key_points: list[str], doc_lower: str) -> list[str]:
    """Return key_points not well-covered in the document."""
    return [p for p in key_points if not _point_covered(p, doc_lower)]


class LangGraphEvolutionPipeline:
    def __init__(self, api_key: str, base_url: str, model: str = "deepseek-chat", proxy_url: str = "") -> None:
        if not api_key.strip():
            raise EvolutionAgentError("标准知识进化 Agent 缺少 DEEPSEEK_API_KEY")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.proxy_url = proxy_url.strip()

    async def _chat(
        self,
        client: httpx.AsyncClient,
        system: str,
        user: str,
        *,
        max_tokens: int,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            value = response.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise EvolutionAgentError(f"DeepSeek Agent 调用失败：{str(exc)[:180]}") from exc
        if not str(value).strip():
            raise EvolutionAgentError("DeepSeek Agent 返回空内容")
        return str(value).strip()

    async def run(self, material: dict[str, Any]) -> tuple[str, str]:
        try:
            from langgraph.graph import END, StateGraph
        except ImportError as exc:
            raise EvolutionAgentError(
                "缺少 LangGraph 运行环境，请安装 langgraph>=0.2.0；标准模式不启用串行降级"
            ) from exc

        content = re.sub(r"[ \t]+\n", "\n", str(material.get("content", ""))).strip()
        if not content:
            raise EvolutionAgentError("目标素材没有可供进化的正文")

        client_options: dict[str, Any] = {"timeout": httpx.Timeout(90.0, connect=15.0)}
        if self.proxy_url:
            client_options["proxy"] = self.proxy_url
        async with httpx.AsyncClient(**client_options) as client:
            async def analyze_node(state: EvolutionState) -> dict[str, Any]:
                raw = await self._chat(
                    client,
                    "你是知识分析 Agent。只依据原文提取主题、摘要、核心知识点、知识缺口、术语和质量问题。只返回 JSON object，字段为 topic、summary、key_points、knowledge_gaps、terms、quality_issues。",
                    f"素材：{material.get('name', '')}\n正文：\n{state['content'][:60_000]}",
                    max_tokens=4096,
                    json_mode=True,
                    temperature=0.1,
                )
                parsed = _parse_json(raw)
                points = _string_list(parsed.get("key_points"), 30)
                if not points:
                    raise EvolutionAgentError("知识分析 Agent 未返回 key_points")
                return {"analysis": {
                    "topic": str(parsed.get("topic", material.get("name", "知识主题"))).strip(),
                    "summary": str(parsed.get("summary", "")).strip()[:2000],
                    "key_points": points,
                    "knowledge_gaps": _string_list(parsed.get("knowledge_gaps")),
                    "terms": _string_list(parsed.get("terms"), 30),
                    "quality_issues": _string_list(parsed.get("quality_issues")),
                }}

            async def expand_node(state: EvolutionState) -> dict[str, Any]:
                issues = state.get("issues") or []
                missing = state.get("missing_points") or []
                is_retry = bool(issues or missing)
                feedback_block = ""
                if is_retry:
                    feedback_lines = []
                    if missing:
                        feedback_lines.append("【必须补充覆盖的缺失知识点】\n" + "\n".join(f"- {p}" for p in missing[:10]))
                    for issue in issues:
                        if "覆盖不足" not in issue:  # 避免重复 missing points
                            feedback_lines.append(f"【审核反馈】{issue}")
                    if feedback_lines:
                        feedback_block = "\n\n=== 上一轮审核未通过，请针对以下反馈补充拓展内容 ===\n" + "\n".join(feedback_lines)
                raw = await self._chat(
                    client,
                    (
                        "你是知识拓展 Agent。基于原文和知识分析结果补充定义、机制、关系、示例、应用、边界和事实谨慎提示。"
                        "不得虚构事实。只返回一个 JSON object，格式严格如下（每个字段的值都必须是字符串数组，不能是单个字符串）：\n"
                        '{\n'
                        '  "definitions": ["核心概念A的准确定义", "核心概念B的准确定义"],\n'
                        '  "mechanisms": ["原理或运作机制的说明"],\n'
                        '  "relationships": ["概念之间的关系说明"],\n'
                        '  "examples": ["具体示例或场景"],\n'
                        '  "applications": ["实际应用场景"],\n'
                        '  "caveats": ["边界条件、注意事项或常见误区"],\n'
                        '  "fact_cautions": ["需要特别谨慎陈述的事实点"]\n'
                        '}\n'
                        "至少 definitions、mechanisms、examples、applications 每个字段都要提供至少 1 条内容。"
                    ),
                    f"分析：{json.dumps(state['analysis'], ensure_ascii=False)}\n原文：\n{state['content'][:40_000]}{feedback_block}",
                    max_tokens=16384,
                    json_mode=True,
                    temperature=0.3,
                )
                parsed = _parse_json(raw)
                expansion = {key: _string_list(parsed.get(key), 16) for key in (
                    "definitions", "mechanisms", "relationships", "examples",
                    "applications", "caveats", "fact_cautions",
                )}
                if sum(len(expansion[key]) for key in expansion if key != "fact_cautions") < 4:
                    raise EvolutionAgentError("知识拓展 Agent 返回的有效补充不足")
                return {"expansion": expansion}

            async def compose_node(state: EvolutionState) -> dict[str, Any]:
                issues = state.get("issues") or []
                missing = state.get("missing_points") or []
                is_retry = bool(issues)
                retry_block = ""
                if is_retry:
                    feedback_lines: list[str] = []
                    if missing:
                        feedback_lines.append(
                            "【必须逐一补充以下缺失的核心知识点，每个知识点至少用一个独立段落阐述】\n"
                            + "\n".join(f"{i+1}. {p}" for i, p in enumerate(missing[:10]))
                        )
                    for issue in issues:
                        if "覆盖不足" not in issue:  # missing 已单独列出
                            feedback_lines.append(f"【待修复】{issue}")
                    if feedback_lines:
                        retry_block = (
                            "\n\n=== 上一版审核未通过，必须在本次重写中修复以下问题 ===\n"
                            + "\n".join(feedback_lines)
                            + "\n\n请重新生成一篇全新的进化文档，严格按照上述反馈逐一修复。不要重复上一版的错误。"
                        )
                draft = await self._chat(
                    client,
                    "你是知识编辑 Agent。把原文、分析和拓展资料重构成可独立阅读的完整 Markdown 文档。必须有主题概述、核心概念、原理或机制、知识关系、示例与应用、边界与注意事项、要点总结。不要输出代码围栏或分析过程。",
                    f"原文：\n{state['content'][:40_000]}\n分析：\n{json.dumps(state['analysis'], ensure_ascii=False)}\n拓展：\n{json.dumps(state['expansion'], ensure_ascii=False)}{retry_block}",
                    max_tokens=12288,
                    temperature=0.25,
                )
                return {"draft": draft.strip()}

            async def review_node(state: EvolutionState) -> dict[str, Any]:
                passed, deterministic_issues, missing_points, similarity = _quality(
                    state["content"], state["draft"], state["analysis"]["key_points"]
                )
                raw = await self._chat(
                    client,
                    "你是知识质量审核 Agent。审核进化文档是否覆盖核心知识、是否有实质补充、是否存在无依据事实、结构是否清晰。只返回 JSON object：passed、score、issues。",
                    f"核心知识点：{json.dumps(state['analysis']['key_points'], ensure_ascii=False)}\n原文：{state['content'][:12_000]}\n进化文档：{state['draft'][:32_000]}",
                    max_tokens=2400,
                    json_mode=True,
                    temperature=0.1,
                )
                parsed = _parse_json(raw)
                review = {
                    "passed": passed and parsed.get("passed") is True,
                    "score": max(0, min(100, int(parsed.get("score", 0) or 0))),
                    "issues": _string_list(parsed.get("issues"), 10),
                    "similarity": similarity,
                }
                return {
                    "agent_review": review,
                    "issues": list(dict.fromkeys(deterministic_issues + review["issues"])),
                    "missing_points": missing_points,
                    "retry_count": int(state.get("retry_count", 0)) + 1,
                }

            def route_after_review(state: EvolutionState) -> str:
                if state["agent_review"]["passed"] or int(state.get("retry_count", 0)) >= 3:
                    return "finish"
                # 覆盖类问题 → 回退到 expand 重新生成拓展资料
                issues = state.get("issues") or []
                missing = state.get("missing_points") or []
                coverage_keywords = ("覆盖不足", "扩展不足", "缺少示例", "缺少边界", "相似度过高")
                if missing or any(any(kw in issue for kw in coverage_keywords) for issue in issues):
                    return "reexpand"
                return "rewrite"

            graph = StateGraph(EvolutionState)
            graph.add_node("analyze", analyze_node)
            graph.add_node("expand", expand_node)
            graph.add_node("compose", compose_node)
            graph.add_node("review", review_node)
            graph.set_entry_point("analyze")
            graph.add_edge("analyze", "expand")
            graph.add_edge("expand", "compose")
            graph.add_edge("compose", "review")
            graph.add_conditional_edges(
                "review",
                route_after_review,
                {"rewrite": "compose", "reexpand": "expand", "finish": END},
            )
            result = await graph.compile().ainvoke({
                "material": material,
                "content": content,
                "retry_count": 0,
            })

        review = result["agent_review"]
        if not review["passed"]:
            raise EvolutionAgentError(f"知识进化质量审核未通过：{'；'.join(result.get('issues', [])[:4])}")
        reason = (
            f"LangGraph 四节点工作流已完成，提取 {len(result['analysis']['key_points'])} 个核心知识点，"
            f"识别 {len(result['analysis']['knowledge_gaps'])} 个知识缺口，质量评分 {review['score']}，"
            f"与原文相似度 {review['similarity']:.0%}"
        )
        return result["draft"], reason


async def run_evolution_agents(
    material: dict[str, Any],
    *,
    api_key: str,
    base_url: str,
    model: str = "deepseek-chat",
    proxy_url: str = "",
) -> tuple[str, str]:
    return await LangGraphEvolutionPipeline(api_key, base_url, model, proxy_url).run(material)
