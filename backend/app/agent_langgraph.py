"""
LangGraph-based Agent implementations — ReAct agents for all modules.

Use langgraph.prebuilt.create_react_agent + langchain_deepseek.ChatDeepSeek
to replace the self-built AgentRuntime ReAct loop.

Switch via env: AGENT_BACKEND=langgraph

Implemented:
  - material_qa:   langgraph_answer_material_question()
  - customer_service: langgraph_answer_customer_service() / langgraph_stream_customer_service()
  - game:          langgraph_generate_game()
  - evolution:     langgraph_run_evolution()
"""

from __future__ import annotations

import asyncio
import json
import re
from difflib import SequenceMatcher
from typing import Any, AsyncIterator, Iterable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from .material_qa_agent import (
    MaterialQaAgentError,
    find_relevant_excerpts,
    _fallback_answer,
)
from .customer_service import answer_customer_service
from .customer_service_agent import (
    CustomerServiceAgentError,
    _build_project_context,
)
from .standard_game_agent import GAME_TITLES
from .standard_evolution import (
    EvolutionAgentError,
    _parse_json,
    _string_list,
    _quality,
)


# ===========================================================================
# Shared helpers
# ===========================================================================

def _build_chat_deepseek(
    api_key: str,
    base_url: str,
    model: str = "deepseek-chat",
    proxy_url: str = "",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> Any:
    """Build a ChatDeepSeek instance, optionally with proxy."""
    import httpx
    from langchain_deepseek import ChatDeepSeek

    http_client_kwargs: dict[str, Any] = {}
    if proxy_url:
        http_client_kwargs["proxy"] = proxy_url

    return ChatDeepSeek(
        model=model,
        api_key=api_key,
        api_base=base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        http_client=httpx.Client(**http_client_kwargs),
    )


def _extract_steps(messages: list[Any]) -> list[dict[str, Any]]:
    """Extract tool call steps from LangGraph message history."""
    steps: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                steps.append({
                    "tool": tc.get("name", ""),
                    "input": json.dumps(tc.get("args", {}), ensure_ascii=False),
                })
    return steps


def _extract_final_answer(messages: list[Any]) -> str:
    """Extract the final AI answer from LangGraph message history."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            return str(msg.content)
    # Fallback: any AIMessage with content
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return str(msg.content)
    return ""


# ===========================================================================
# Material QA — LangGraph ReAct Agent
# ===========================================================================

async def langgraph_answer_material_question(
    material: dict[str, Any],
    question: str,
    *,
    api_key: str = "",
    base_url: str = "",
    model: str = "deepseek-chat",
    proxy_url: str = "",
) -> dict[str, Any]:
    """LangGraph-based material QA — same signature as agent_answer_material_question()."""
    content = str(material.get("content") or "").strip()
    if not content:
        raise MaterialQaAgentError("当前素材没有可问答的正文内容")

    if not api_key:
        excerpts = find_relevant_excerpts(content, question)
        return {
            "answer": _fallback_answer(question, excerpts),
            "original_content": "\n\n".join(e.text for e in excerpts),
            "excerpts": [e.__dict__ for e in excerpts],
            "mode": "langgraph-material-qa-fallback",
            "agent_note": "未配置 DEEPSEEK_API_KEY，降级为本地检索模式。",
        }

    # ---- Define the search tool as a LangChain @tool ----
    material_content = content

    @tool
    async def search_material(query: str) -> str:
        """在素材正文中搜索与用户问题相关的内容片段。
        当你不确定答案或需要更多上下文时，调用此工具检索原文。
        可以多次调用，每次使用不同的查询关键词。"""
        excerpts = find_relevant_excerpts(material_content, query, limit=3)
        results = [
            {"index": e.index, "text": e.text[:500], "score": round(e.score, 2)}
            for e in excerpts
        ]
        return json.dumps(
            {"query": query, "results": results, "total_found": len(excerpts)},
            ensure_ascii=False,
        )

    tools = [search_material]

    system_prompt = (
        "你是素材问答 Agent，负责基于用户提供的素材内容回答用户问题。\n\n"
        "工作流程：\n"
        "1. 先理解用户的问题\n"
        "2. 如果对答案不确定，使用 search_material 工具检索原文相关内容\n"
        "3. 可以多次使用不同关键词搜索，直到找到足够信息\n"
        "4. 基于检索到的原文内容，用中文给出准确、简洁的回答\n\n"
        "规则：\n"
        "- 只能依据检索到的原文内容回答，不能编造\n"
        "- 如果原文确实没有相关信息，明确告知用户\n"
        "- 回答要简洁，突出重点\n"
        "- 引用原文内容时用引号标注\n\n"
        f"素材名称：{material.get('name', '')}\n"
        f"素材类型：{material.get('kind', '')}\n"
        f"素材分类：{material.get('category', '')}"
    )

    llm = _build_chat_deepseek(api_key, base_url, model, proxy_url, temperature=0.2, max_tokens=1500)
    agent = create_react_agent(llm, tools)

    try:
        result = await agent.ainvoke({
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"用户问题：{question}\n\n请根据素材内容回答。如果不确定，请先使用 search_material 工具搜索原文。"),
            ],
        })

        messages = result.get("messages", [])
        answer = _extract_final_answer(messages)
        if not answer:
            raise MaterialQaAgentError("Agent 未返回有效回答")

        steps = _extract_steps(messages)

        # Collect excerpts from tool results
        all_excerpts: list[dict[str, Any]] = []
        for msg in messages:
            if hasattr(msg, "name") and msg.name == "search_material":
                try:
                    data = json.loads(str(msg.content))
                    for item in data.get("results", []):
                        all_excerpts.append({
                            "index": item.get("index", 0),
                            "text": item.get("text", ""),
                            "score": item.get("score", 0),
                        })
                except (json.JSONDecodeError, TypeError):
                    pass

        if not all_excerpts:
            excerpts = find_relevant_excerpts(content, question)
            all_excerpts = [e.__dict__ for e in excerpts]

        return {
            "answer": answer,
            "original_content": "\n\n".join(e.get("text", "") for e in all_excerpts[:3]),
            "excerpts": all_excerpts[:5],
            "mode": "langgraph-material-qa",
            "agent_note": f"LangGraph Agent 自主完成 {len(steps)} 次工具调用后给出回答。",
            "agent_steps": [
                {"tool": s["tool"], "input": str(s["input"])[:200]}
                for s in steps
            ],
        }

    except Exception as exc:
        excerpts = find_relevant_excerpts(content, question)
        return {
            "answer": _fallback_answer(question, excerpts),
            "original_content": "\n\n".join(e.text for e in excerpts),
            "excerpts": [e.__dict__ for e in excerpts],
            "mode": "langgraph-material-qa-fallback",
            "agent_note": f"LangGraph Agent 调用失败，降级为本地检索：{str(exc)[:160]}",
        }


# ===========================================================================
# Customer Service — LangGraph ReAct Agent
# ===========================================================================

async def _search_knowledge_base(query: str) -> dict[str, Any]:
    """Search the local knowledge base for relevant articles."""
    retrieval = answer_customer_service(query)
    article = retrieval.get("article", {})
    related = retrieval.get("related", [])
    return {
        "query": query,
        "matched": bool(retrieval.get("matched")),
        "main_article": {
            "id": article.get("id", ""),
            "title": article.get("title", ""),
            "summary": article.get("summary", ""),
            "answer": str(article.get("answer", ""))[:600],
            "category": article.get("category", ""),
        },
        "related_count": len(related),
        "related_titles": [r.get("title", "") for r in related[:3]],
    }


async def langgraph_answer_customer_service(
    question: str,
    history: Iterable[dict[str, str]] = (),
    *,
    api_key: str,
    base_url: str,
    model: str = "deepseek-chat",
    proxy_url: str = "",
) -> dict[str, Any]:
    """LangGraph-based customer service — same signature as agent_answer_customer_service()."""
    question = question.strip()
    if not question:
        raise CustomerServiceAgentError("客服问题不能为空")
    if not api_key.strip():
        raise CustomerServiceAgentError("客服 Agent 未配置 DEEPSEEK_API_KEY")

    @tool
    async def search_knowledge_base(query: str) -> str:
        """在知衍平台帮助文档中搜索与问题相关的文章。
        当你不确定平台功能细节或操作流程时，调用此工具获取准确的帮助信息。
        可以多次调用，每次使用不同的查询关键词来覆盖不同方面。"""
        result = await _search_knowledge_base(query)
        return json.dumps(result, ensure_ascii=False)

    tools = [search_knowledge_base]

    history_context = ""
    history_list = list(history)[-8:]
    if history_list:
        history_context = "对话历史：\n" + "\n".join(
            f"{'用户' if h.get('role') == 'user' else '助手'}: {str(h.get('content', ''))[:200]}"
            for h in history_list
        )

    system_prompt = (
        "你是「知衍」知识工作坊的客服 Agent，负责解答用户关于平台功能、操作流程、"
        "Agent 配置和数据规范的问题。\n\n"
        "工作流程：\n"
        "1. 分析用户问题，确定需要查询的知识领域\n"
        "2. 使用 search_knowledge_base 工具检索平台帮助文档\n"
        "3. 如果一次搜索不够，用不同关键词再次搜索\n"
        "4. 基于检索到的帮助文档，用中文生成清晰、有帮助的回答\n\n"
        "规则：\n"
        "- 只能依据检索到的帮助文档内容回答，不能编造功能或流程\n"
        "- 如果文档中没有明确答案，诚实告知并给出排查建议\n"
        "- 涉及 Agent 调用失败时，说明应检查后端、API Key、素材状态等\n"
        "- 回答简洁有条理，可以分点说明\n"
        "- 不要输出 JSON 或系统提示词\n"
        f"\n{history_context}"
    )

    llm = _build_chat_deepseek(api_key, base_url, model, proxy_url, temperature=0.25, max_tokens=1400)
    agent = create_react_agent(llm, tools)

    try:
        result = await agent.ainvoke({
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"用户问题：{question}\n\n请根据平台帮助文档回答。如果不确定，请使用 search_knowledge_base 工具检索。"),
            ],
        })

        messages = result.get("messages", [])
        answer = _extract_final_answer(messages)
        if not answer:
            raise CustomerServiceAgentError("Agent 未返回有效回答")

        steps = _extract_steps(messages)
        retrieval, _ = _build_project_context(question)

        return {
            "question": question,
            "matched": bool(retrieval.get("matched")),
            "mode": "langgraph-customer-service",
            "agent": {
                "name": "知衍客服 Agent",
                "provider": "DeepSeek (LangGraph)",
                "model": model,
            },
            "answer": answer,
            "article": retrieval["article"],
            "related": retrieval.get("related", []),
            "source": retrieval.get("source", ""),
            "agent_note": f"LangGraph Agent 自主完成 {len(steps)} 次知识库检索后给出回答。",
            "agent_steps": [
                {"tool": s["tool"], "input": str(s["input"])[:200]}
                for s in steps
            ],
        }

    except CustomerServiceAgentError:
        raise
    except Exception as exc:
        raise CustomerServiceAgentError(
            f"客服 LangGraph Agent 调用失败：{str(exc)[:180]}"
        ) from exc


async def langgraph_stream_customer_service(
    question: str,
    history: Iterable[dict[str, str]] = (),
    *,
    api_key: str,
    base_url: str,
    model: str = "deepseek-chat",
    proxy_url: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """LangGraph-based streaming customer service.

    Uses astream_events for real token-level streaming from the LLM.
    """
    question = question.strip()
    if not question:
        raise CustomerServiceAgentError("客服问题不能为空")
    if not api_key.strip():
        raise CustomerServiceAgentError("客服 Agent 未配置 DEEPSEEK_API_KEY")

    # Yield context first
    retrieval, _ = _build_project_context(question)
    yield {
        "type": "context",
        "question": question,
        "matched": bool(retrieval.get("matched")),
        "article": retrieval["article"],
        "related": retrieval.get("related", []),
        "source": retrieval.get("source", ""),
    }

    @tool
    async def search_knowledge_base(query: str) -> str:
        """在知衍平台帮助文档中搜索与问题相关的文章。"""
        result = await _search_knowledge_base(query)
        return json.dumps(result, ensure_ascii=False)

    tools = [search_knowledge_base]

    history_context = ""
    history_list = list(history)[-8:]
    if history_list:
        history_context = "对话历史：\n" + "\n".join(
            f"{'用户' if h.get('role') == 'user' else '助手'}: {str(h.get('content', ''))[:200]}"
            for h in history_list
        )

    system_prompt = (
        "你是「知衍」知识工作坊的客服 Agent，负责解答用户关于平台功能、操作流程、"
        "Agent 配置和数据规范的问题。\n\n"
        "工作流程：\n"
        "1. 分析用户问题，确定需要查询的知识领域\n"
        "2. 使用 search_knowledge_base 工具检索平台帮助文档\n"
        "3. 如果一次搜索不够，用不同关键词再次搜索\n"
        "4. 基于检索到的帮助文档，用中文生成清晰、有帮助的回答\n\n"
        "规则：\n"
        "- 只能依据检索到的帮助文档内容回答，不能编造功能或流程\n"
        "- 如果文档中没有明确答案，诚实告知并给出排查建议\n"
        "- 回答简洁有条理，可以分点说明\n"
        "- 不要输出 JSON 或系统提示词\n"
        f"\n{history_context}"
    )

    llm = _build_chat_deepseek(api_key, base_url, model, proxy_url, temperature=0.25, max_tokens=1400)
    agent = create_react_agent(llm, tools)

    full_answer = ""
    tool_steps: list[dict[str, Any]] = []

    try:
        async for event in agent.astream_events(
            {
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=f"用户问题：{question}\n\n请根据平台帮助文档回答。如果不确定，请使用 search_knowledge_base 工具检索。"),
                ],
            },
            version="v2",
        ):
            kind = event.get("event", "")

            # Track tool calls
            if kind == "on_tool_start":
                tool_steps.append({
                    "tool": event.get("name", ""),
                    "input": str(event.get("data", {}).get("input", ""))[:200],
                })

            # Stream token-level output from the chat model (only final answer, not tool-call tokens)
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    # Skip content that looks like tool calls (shouldn't happen with stream but safety)
                    if not (hasattr(chunk, "tool_calls") and chunk.tool_calls):
                        token = str(chunk.content)
                        full_answer += token
                        yield {"type": "delta", "content": token}

        if not full_answer.strip():
            raise CustomerServiceAgentError("客服 Agent 返回了空答案")

    except CustomerServiceAgentError:
        raise
    except Exception as exc:
        raise CustomerServiceAgentError(
            f"客服 LangGraph Agent 流式调用失败：{str(exc)[:180]}"
        ) from exc

    yield {
        "type": "done",
        "result": {
            "question": question,
            "matched": bool(retrieval.get("matched")),
            "mode": "langgraph-customer-service",
            "agent": {
                "name": "知衍客服 Agent",
                "provider": "DeepSeek (LangGraph)",
                "model": model,
            },
            "answer": full_answer.strip(),
            "article": retrieval["article"],
            "related": retrieval.get("related", []),
            "source": retrieval.get("source", ""),
            "agent_note": f"LangGraph Agent 自主完成 {len(tool_steps)} 次知识库检索后给出回答。",
        },
    }


# ===========================================================================
# Game Generation — LangGraph ReAct Agent
# ===========================================================================

# ---------------------------------------------------------------------------
# Game question parsing helpers (inlined)
# ---------------------------------------------------------------------------

def _parse_agent_questions(raw: str) -> list[dict[str, Any]]:
    """Parse questions from agent output, handling various JSON formats."""
    text = raw.strip()

    # Strategy 1: Extract JSON from markdown code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, flags=re.I | re.S)
    if match:
        text = match.group(1).strip()

    # Strategy 2: Find the outermost JSON object or array
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                if text[i] in "{[":
                    depth += 1
                elif text[i] in "}]":
                    depth -= 1
                if depth == 0:
                    text = text[start:i + 1]
                    break

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            questions = data.get("questions", [])
            if isinstance(questions, list):
                return questions
            for key in ("questions", "data", "items", "results"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass

    # Strategy 3: Try to find questions array anywhere in the text
    for pattern in [
        r'"questions"\s*:\s*(\[.*?\](?=\s*[,}]))',
        r'(\[.*?\{.*?"prompt".*?\}.*?\])',
    ]:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            try:
                data = json.loads(match.group(1))
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, TypeError):
                continue

    return []


def _questions_to_points(
    questions: list[dict[str, Any]],
    materials: list[dict],
) -> list[dict[str, Any]]:
    """Convert agent-generated questions to knowledge points format."""
    material_names = {int(item["id"]): item["name"] for item in materials}
    material_keywords = {}
    for item in materials:
        mid = int(item["id"])
        name = str(item.get("name", ""))
        content = str(item.get("content", ""))
        words = set(re.findall(r"[\u4e00-\u9fff\w]{2,}", name + content[:1000]))
        words.add(name.lower())
        material_keywords[mid] = words

    def _infer_source_id(topic: str) -> int:
        topic_words = set(re.findall(r"[\u4e00-\u9fff\w]{2,}", topic.lower()))
        best_id, best_score = materials[0]["id"] if materials else 0, 0
        for mid, words in material_keywords.items():
            score = len(topic_words & words)
            if score > best_score:
                best_score = score
                best_id = mid
        return int(best_id)

    default_material = materials[0] if materials else None
    points = []
    seen = set()

    for q in questions:
        topic = str(q.get("topic", "")).strip()[:80]
        key = re.sub(r"\W+", "", topic).lower()
        if not topic or key in seen:
            continue
        seen.add(key)

        source_id = int(q.get("source_material_id") or 0)
        if not source_id:
            source_id = _infer_source_id(topic)
        if not source_id and default_material:
            source_id = int(default_material["id"])

        points.append({
            "term": topic,
            "definition": str(q.get("answer", ""))[:500],
            "fact": str(q.get("explanation", ""))[:500],
            "expanded_text": str(q.get("prompt", ""))[:900],
            "source_material_id": source_id,
            "source_name": material_names.get(source_id, ""),
            "distractors": [
                str(o)[:180] for o in q.get("options", [])
                if str(o).strip() and str(o) != str(q.get("answer", ""))
            ][:3],
        })

    return points


async def _extract_knowledge_for_game(materials: list[dict]) -> dict[str, Any]:
    """Provide material overview with full content for the LLM to generate questions."""
    source = "\n\n".join(
        f"[素材 {item['id']}: {item['name']}]\n{str(item['content'])[:12000]}"
        for item in materials
    )[:60000]

    return {
        "materials_count": len(materials),
        "materials": [
            {"id": item["id"], "name": item["name"], "kind": item["kind"]}
            for item in materials
        ],
        "content": source,
        "note": "请基于以上素材的完整内容，生成与原文事实一致的题目。",
    }


async def _store_questions_langgraph(
    questions_json: str,
    game: str,
    difficulty: str,
    expected_count: int = 6,
) -> dict[str, Any]:
    """Parse and validate agent-generated questions (LangGraph version)."""
    try:
        if isinstance(questions_json, str):
            questions = json.loads(questions_json)
        else:
            questions = questions_json

        if isinstance(questions, dict):
            questions = questions.get("questions", [questions])

        if not isinstance(questions, list):
            return {"error": "questions 必须是数组", "received": str(type(questions))}

        validated = []
        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                continue
            validated.append({
                "index": i + 1,
                "prompt": str(q.get("prompt", ""))[:500],
                "options": [
                    str(o)[:300] for o in q.get("options", [])
                    if str(o).strip()
                ][:4],
                "answer": str(q.get("answer", ""))[:300],
                "explanation": str(q.get("explanation", ""))[:500],
                "topic": str(q.get("topic", ""))[:80],
                "question_type": str(q.get("question_type", "multiple-choice")),
            })

        valid = len(validated) >= expected_count
        return {
            "valid": valid,
            "count": len(validated),
            "expected": expected_count,
            "questions": validated,
            "game": game,
            "difficulty": difficulty,
            "hint": (
                f"已生成 {len(validated)}/{expected_count} 道有效题目。"
                if valid else
                f"题目数量不足：{len(validated)}/{expected_count}，请补充更多题目。"
            ),
        }
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return {"error": f"题目解析失败：{str(exc)[:200]}"}


async def langgraph_generate_game(
    materials: list[dict],
    game: str,
    difficulty: str,
    *,
    api_key: str,
    base_url: str,
    model: str = "deepseek-chat",
    proxy_url: str = "",
) -> tuple[list[dict[str, Any]], str, str]:
    """LangGraph-based game generation — same signature as agent_generate_game()."""
    if game not in GAME_TITLES:
        raise ValueError("不支持的游戏类型")

    if not api_key.strip():
        raise ValueError("LangGraph Agent 模式缺少 DEEPSEEK_API_KEY")

    game_title = GAME_TITLES[game]
    counts = {
        "flashcard": {"easy": 8, "medium": 6, "hard": 18},
        "monopoly": {"easy": 5, "medium": 6, "hard": 8},
        "matching": {"easy": 5, "medium": 6, "hard": 8},
    }
    expected_count = counts.get(game, {}).get(difficulty, 6)

    # ---- Define tools ----
    materials_ref = materials

    @tool
    async def inspect_materials() -> str:
        """获取可用于生成游戏题目的素材概览。在开始生成题目之前，
        先调用此工具了解有哪些素材、它们的名称和类型以及完整内容。"""
        result = await _extract_knowledge_for_game(materials_ref)
        return json.dumps(result, ensure_ascii=False)

    @tool
    async def validate_questions(questions_json: str) -> str:
        """验证和格式化生成的游戏题目。将你生成的题目 JSON 传入此工具，
        它会校验格式是否正确、选项是否完整、数量是否达标。
        如果验证失败，根据返回的错误信息重新生成。"""
        result = await _store_questions_langgraph(questions_json, game, difficulty, expected_count)
        return json.dumps(result, ensure_ascii=False)

    tools = [inspect_materials, validate_questions]

    system_prompt = (
        f"你是游戏出题 Agent，负责从知识素材中为「{game_title}」生成 {difficulty} 难度的题目。\n\n"
        "工作流程：\n"
        "1. 使用 inspect_materials 工具获取素材概览\n"
        "2. 基于素材内容生成题目，题目要基于原文事实，不能编造\n"
        "3. 使用 validate_questions 工具验证和格式化题目\n"
        "4. 如果验证失败，根据错误信息修正后重新生成\n\n"
        "题目要求：\n"
        f"- 至少生成 {expected_count} 道题目\n"
        "- 每道题含 prompt（题目描述）、options（4 个选项的数组）、answer（正确答案）、"
        "explanation（解释）、topic（知识点主题）、question_type（multiple-choice 或 concept-definition）\n"
        "- 选项要包含 1 个正确答案和 3 个干扰项\n"
        "- 干扰项要似是而非，与正确答案属同一领域\n"
        "- 题目要覆盖多个素材，不要集中在一个素材上\n\n"
        "最终输出格式：将完整的题目列表以 JSON 格式输出，"
        "格式为 {{\"questions\": [题目列表]}}"
    )

    llm = _build_chat_deepseek(api_key, base_url, model, proxy_url, temperature=0.3, max_tokens=16000)
    agent = create_react_agent(llm, tools)

    try:
        result = await agent.ainvoke({
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=(
                    f"请从以下素材中为「{game_title}」生成 {difficulty} 难度题目。\n"
                    f"素材数量：{len(materials)} 个\n"
                    f"素材名称：{', '.join(item['name'] for item in materials)}\n\n"
                    f"请先使用 inspect_materials 工具了解素材内容，然后生成题目。"
                )),
            ],
        })

        messages = result.get("messages", [])
        answer = _extract_final_answer(messages)
        steps = _extract_steps(messages)

        # Parse questions from the final answer
        questions = _parse_agent_questions(answer)

        # Fallback: extract from the last validate_questions tool call
        if not questions:
            for msg in reversed(messages):
                if hasattr(msg, "name") and msg.name == "validate_questions":
                    try:
                        data = json.loads(str(msg.content))
                        if data.get("valid") and data.get("questions"):
                            questions = data["questions"]
                            break
                    except (json.JSONDecodeError, TypeError):
                        pass

        if not questions or len(questions) < 4:
            raise ValueError(
                f"LangGraph Agent 生成的题目数量不足：{len(questions)}，至少需要 4 道"
            )

        points = _questions_to_points(questions, materials)
        source_mode = "langgraph-game-generator"
        agent_note = (
            f"LangGraph Agent 自主完成 {len(steps)} 次工具调用后生成 {len(questions)} 道题目。"
        )

        return points, source_mode, agent_note

    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"游戏出题 LangGraph Agent 调用失败：{str(exc)[:180]}"
        ) from exc


# ===========================================================================
# Knowledge Evolution — LangGraph ReAct Agent
# ===========================================================================

async def _analyze_material_langgraph(
    content: str,
    material_name: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    proxy_url: str,
) -> dict[str, Any]:
    """Analyze material to extract key points, gaps, terms, and quality issues.
    Uses ChatDeepSeek directly instead of nested AgentRuntime."""
    llm = _build_chat_deepseek(api_key, base_url, model, proxy_url, temperature=0.1, max_tokens=4096)

    system = (
        "你是知识分析 Agent。只依据原文提取主题、摘要、核心知识点、知识缺口、术语和质量问题。"
        "只返回 JSON object，字段为 topic、summary、key_points、knowledge_gaps、terms、quality_issues。"
    )
    user = f"素材：{material_name}\n正文：\n{content[:60000]}"

    response = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=user),
    ])

    parsed = _parse_json(str(response.content))
    points = _string_list(parsed.get("key_points"), 30)
    if not points:
        raise EvolutionAgentError("知识分析 Agent 未返回 key_points")

    return {
        "topic": str(parsed.get("topic", material_name)).strip(),
        "summary": str(parsed.get("summary", "")).strip()[:2000],
        "key_points": points,
        "knowledge_gaps": _string_list(parsed.get("knowledge_gaps")),
        "terms": _string_list(parsed.get("terms"), 30),
        "quality_issues": _string_list(parsed.get("quality_issues")),
    }


async def _expand_knowledge_langgraph(
    analysis_json: str,
    original_content: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    proxy_url: str,
) -> dict[str, Any]:
    """Expand knowledge based on analysis results.
    Uses ChatDeepSeek directly instead of nested AgentRuntime."""
    llm = _build_chat_deepseek(api_key, base_url, model, proxy_url, temperature=0.3, max_tokens=16384)

    system = (
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
    )
    user = f"分析：{analysis_json}\n原文：\n{original_content[:40000]}"

    response = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=user),
    ])

    parsed = _parse_json(str(response.content))
    expansion = {
        key: _string_list(parsed.get(key), 16)
        for key in (
            "definitions", "mechanisms", "relationships", "examples",
            "applications", "caveats", "fact_cautions",
        )
    }
    if sum(len(expansion[key]) for key in expansion if key != "fact_cautions") < 4:
        raise EvolutionAgentError("知识拓展 Agent 返回的有效补充不足")

    return expansion


async def _compose_document_langgraph(
    analysis_json: str,
    expansion_json: str,
    original_content: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    proxy_url: str,
) -> str:
    """Compose the final evolved document.
    Uses ChatDeepSeek directly instead of nested AgentRuntime."""
    llm = _build_chat_deepseek(api_key, base_url, model, proxy_url, temperature=0.25, max_tokens=12288)

    system = (
        "你是知识编辑 Agent。把原文、分析和拓展资料重构成可独立阅读的完整 Markdown 文档。"
        "必须有主题概述、核心概念、原理或机制、知识关系、示例与应用、边界与注意事项、要点总结。"
        "不要输出代码围栏或分析过程。"
    )
    user = (
        f"原文：\n{original_content[:40000]}\n"
        f"分析：\n{analysis_json}\n"
        f"拓展：\n{expansion_json}"
    )

    response = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=user),
    ])

    return str(response.content).strip()


async def _review_document_langgraph(
    draft: str,
    original_content: str,
    key_points_json: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    proxy_url: str,
) -> dict[str, Any]:
    """Review the evolved document quality.
    Combines deterministic quality check + AI review."""
    key_points = json.loads(key_points_json) if isinstance(key_points_json, str) else key_points_json
    if isinstance(key_points, dict):
        key_points = key_points.get("key_points", [])

    # Deterministic quality check
    passed, deterministic_issues, missing_points, similarity = _quality(
        original_content, draft, key_points
    )

    # AI review
    llm = _build_chat_deepseek(api_key, base_url, model, proxy_url, temperature=0.1, max_tokens=2400)

    system = (
        "你是知识质量审核 Agent。审核进化文档是否覆盖核心知识、是否有实质补充、"
        "是否存在无依据事实、结构是否清晰。只返回 JSON object：passed、score、issues。"
    )
    user = (
        f"核心知识点：{json.dumps(key_points, ensure_ascii=False)}\n"
        f"原文：{original_content[:12000]}\n"
        f"进化文档：{draft[:32000]}"
    )

    response = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=user),
    ])

    parsed = _parse_json(str(response.content))
    ai_passed = parsed.get("passed") is True
    ai_score = max(0, min(100, int(parsed.get("score", 0) or 0)))
    ai_issues = _string_list(parsed.get("issues"), 10)

    return {
        "passed": passed and ai_passed,
        "score": ai_score,
        "issues": list(dict.fromkeys(deterministic_issues + ai_issues)),
        "missing_points": missing_points,
        "similarity": similarity,
    }


async def langgraph_run_evolution(
    material: dict[str, Any],
    *,
    api_key: str,
    base_url: str,
    model: str = "deepseek-chat",
    proxy_url: str = "",
) -> tuple[str, str]:
    """LangGraph-based knowledge evolution — same signature as agent_run_evolution()."""
    content = re.sub(r"[ \t]+\n", "\n", str(material.get("content", ""))).strip()
    if not content:
        raise EvolutionAgentError("目标素材没有可供进化的正文")

    material_name = str(material.get("name", ""))

    # ---- Define tools ----
    content_ref = content
    api_key_ref = api_key
    base_url_ref = base_url
    model_ref = model
    proxy_url_ref = proxy_url

    @tool
    async def analyze(content_arg: str = "") -> str:
        """分析知识素材，提取主题、摘要、核心知识点（key_points）、知识缺口、
        术语和质量问题。必须在进化流程开始时首先调用。"""
        result = await _analyze_material_langgraph(
            content_arg or content_ref,
            material_name,
            api_key=api_key_ref,
            base_url=base_url_ref,
            model=model_ref,
            proxy_url=proxy_url_ref,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    async def expand(analysis_json: str) -> str:
        """基于分析结果拓展知识，补充定义、机制、关系、示例、应用、边界等内容。
        必须在 analyze 之后调用。传入 analyze 工具返回的完整 JSON。"""
        result = await _expand_knowledge_langgraph(
            analysis_json,
            content_ref,
            api_key=api_key_ref,
            base_url=base_url_ref,
            model=model_ref,
            proxy_url=proxy_url_ref,
        )
        return json.dumps(result, ensure_ascii=False)

    @tool
    async def compose(analysis_json: str, expansion_json: str) -> str:
        """将原文、分析和拓展资料重构成完整的 Markdown 文档。
        必须在 analyze 和 expand 之后调用。"""
        result = await _compose_document_langgraph(
            analysis_json,
            expansion_json,
            content_ref,
            api_key=api_key_ref,
            base_url=base_url_ref,
            model=model_ref,
            proxy_url=proxy_url_ref,
        )
        return result

    @tool
    async def review(draft: str, key_points_json: str) -> str:
        """审核进化文档质量。返回是否通过、评分和问题列表。
        如果未通过（passed=false），根据 issues 内容决定：
        - 如果 issues 包含'覆盖不足'、'缺少'等 → 重新调用 expand
        - 如果 issues 包含'结构'、'相似度'等 → 重新调用 compose
        最多重试 3 次。"""
        result = await _review_document_langgraph(
            draft,
            content_ref,
            key_points_json,
            api_key=api_key_ref,
            base_url=base_url_ref,
            model=model_ref,
            proxy_url=proxy_url_ref,
        )
        return json.dumps(result, ensure_ascii=False)

    tools = [analyze, expand, compose, review]

    system_prompt = (
        "你是知识进化 Agent，负责将原始知识素材进化成高质量的结构化文档。\n\n"
        "你必须严格按照以下流程执行：\n"
        "1. 首先调用 analyze 工具分析素材\n"
        "2. 然后调用 expand 工具拓展知识\n"
        "3. 然后调用 compose 工具生成进化文档\n"
        "4. 最后调用 review 工具审核文档质量\n\n"
        "审核规则：\n"
        "- 如果 review 返回 passed=true，输出 compose 生成的完整 Markdown 文档\n"
        "- 如果 review 返回 passed=false：\n"
        "  - issues 包含'覆盖不足'或'缺少'关键词 → 重新调用 expand，然后 compose，再 review\n"
        "  - issues 包含'结构'或'相似度'关键词 → 重新调用 compose，然后 review\n"
        "- 最多重试 3 次，超过后直接输出当前最佳文档\n\n"
        "最终输出：只输出进化完成的 Markdown 文档全文，不要包含任何分析过程或 JSON。"
    )

    llm = _build_chat_deepseek(api_key, base_url, model, proxy_url, temperature=0.2, max_tokens=16384)
    agent = create_react_agent(llm, tools)

    try:
        result = await agent.ainvoke({
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=(
                    f"请对以下素材执行知识进化：\n"
                    f"素材名称：{material_name}\n"
                    f"素材类型：{material.get('kind', '')}\n"
                    f"素材分类：{material.get('category', '')}\n"
                    f"正文长度：{len(content)} 字\n\n"
                    f"请开始进化流程。"
                )),
            ],
        })

        messages = result.get("messages", [])
        draft = _extract_final_answer(messages)
        steps = _extract_steps(messages)

        # Strip any markdown code fences from the output
        draft = re.sub(r"^```(?:markdown|md)?\s*\n?", "", draft.strip())
        draft = re.sub(r"\n```\s*$", "", draft).strip()

        if not draft or len(draft) < 200:
            raise EvolutionAgentError("Agent 进化输出的文档内容过短")

        tool_names = [s["tool"] for s in steps]
        reason = (
            f"LangGraph Agent 自主编排进化流程，调用序列：{' → '.join(tool_names)}，"
            f"共 {len(steps)} 次工具调用"
        )

        return draft, reason

    except EvolutionAgentError:
        raise
    except Exception as exc:
        raise EvolutionAgentError(
            f"知识进化 LangGraph Agent 调用失败：{str(exc)[:180]}"
        ) from exc