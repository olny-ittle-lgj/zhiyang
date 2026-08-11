import json
import unittest
from unittest.mock import AsyncMock, patch

from app.evolution import (
    EvolutionAgentError,
    EvolutionAgentPipeline,
    _parse_json_object,
    evaluate_evolution_quality,
)


ANALYSIS = {
    "topic": "向量检索",
    "summary": "向量检索通过语义表示查找相近内容。",
    "key_points": ["向量检索用于语义相似内容查找", "嵌入模型把文本转换为向量"],
    "knowledge_gaps": ["缺少相似度度量说明"],
    "terms": ["嵌入模型", "余弦相似度"],
    "quality_issues": ["缺少示例"],
}

EXPANSION = {
    "definitions": ["嵌入是对象的稠密数值表示"],
    "mechanisms": ["查询与文档使用同一模型编码后比较距离"],
    "relationships": ["向量检索通常与关键词检索组成混合检索"],
    "examples": ["知识库可用查询向量召回语义相近片段"],
    "applications": ["适用于问答检索和相似内容推荐"],
    "caveats": ["结果质量依赖嵌入模型与数据质量"],
    "fact_cautions": ["具体阈值需要依据数据集验证"],
}


def good_document() -> str:
    sections = [
        "# 向量检索知识指南",
        "## 主题概述\n向量检索用于语义相似内容查找，并支持从知识库召回相关信息。",
        "## 核心概念\n嵌入模型把文本转换为向量。嵌入是对象的稠密数值表示，使语义关系能够参与计算。",
        "## 原理与机制\n查询和文档使用同一嵌入模型编码，再通过相似度度量排序。这个过程包括编码、候选召回和结果排序。",
        "## 知识关系\n向量检索关注语义相近，关键词检索关注字面匹配，两者可以组成混合检索并互相补充。",
        "## 示例与应用\n在知识问答中，系统先把问题编码，再召回相关知识片段供后续回答使用。它也可用于相似内容推荐。",
        "## 边界与注意事项\n结果质量依赖嵌入模型、语料质量和评测方式。具体相似度阈值应依据真实数据验证，不能直接照搬。",
        "## 要点总结\n核心链路是统一编码、相似度计算和候选排序。落地时还要持续评估召回质量与事实边界。",
    ]
    return "\n\n".join(sections) + "\n\n" + ("补充说明用于形成完整且可独立阅读的知识文档。" * 12)


class EvolutionParsingTests(unittest.TestCase):
    def test_json_parser_accepts_code_fence_and_surrounding_text(self):
        parsed = _parse_json_object("结果如下：\n```json\n{\"topic\": \"检索\"}\n```\n完成")
        self.assertEqual(parsed["topic"], "检索")

    def test_json_parser_rejects_malformed_agent_response(self):
        with self.assertRaises(EvolutionAgentError):
            _parse_json_object("这不是 JSON")

    def test_quality_gate_rejects_near_copy(self):
        original = "向量检索用于语义检索。嵌入模型把文本转换为向量。" * 15
        result = evaluate_evolution_quality(
            original,
            "# 标题\n\n## 核心概念\n" + original + "\n\n## 示例与应用\n示例\n\n## 边界与注意事项\n注意",
            ["向量检索用于语义检索", "嵌入模型把文本转换为向量"],
        )
        self.assertFalse(result.passed)
        self.assertTrue(any("扩展不足" in issue or "相似度" in issue for issue in result.issues))

    def test_quality_gate_accepts_expanded_structured_document(self):
        result = evaluate_evolution_quality(
            "向量检索用于语义相似内容查找。嵌入模型把文本转换为向量。",
            good_document(),
            ANALYSIS["key_points"],
        )
        self.assertTrue(result.passed, result.issues)


class EvolutionPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_extracts_expands_composes_and_reviews(self):
        pipeline = EvolutionAgentPipeline("test-key", "https://example.invalid")
        replies = [
            json.dumps(ANALYSIS, ensure_ascii=False),
            json.dumps(EXPANSION, ensure_ascii=False),
            good_document(),
            json.dumps({"passed": True, "score": 94, "issues": []}, ensure_ascii=False),
        ]
        with patch.object(pipeline, "_chat", new=AsyncMock(side_effect=replies)) as chat:
            evolved, reason = await pipeline.run({
                "name": "向量检索",
                "category": "人工智能",
                "content": "向量检索用于语义相似内容查找。嵌入模型把文本转换为向量。",
            })
        self.assertEqual(evolved, good_document())
        self.assertIn("2 个核心知识点", reason)
        self.assertIn("质量评分 94", reason)
        self.assertEqual(chat.await_count, 4)

    async def test_pipeline_rewrites_once_when_first_draft_fails(self):
        pipeline = EvolutionAgentPipeline("test-key", "https://example.invalid")
        replies = [
            json.dumps(ANALYSIS, ensure_ascii=False),
            json.dumps(EXPANSION, ensure_ascii=False),
            "# 向量检索\n\n原文基本不变。",
            json.dumps({"passed": False, "score": 40, "issues": ["扩写不足"]}, ensure_ascii=False),
            good_document(),
            json.dumps({"passed": True, "score": 91, "issues": []}, ensure_ascii=False),
        ]
        with patch.object(pipeline, "_chat", new=AsyncMock(side_effect=replies)) as chat:
            evolved, _ = await pipeline.run({
                "name": "向量检索",
                "category": "人工智能",
                "content": "向量检索用于语义相似内容查找。嵌入模型把文本转换为向量。",
            })
        self.assertEqual(evolved, good_document())
        self.assertEqual(chat.await_count, 6)

    async def test_pipeline_does_not_silently_accept_agent_failure(self):
        pipeline = EvolutionAgentPipeline("test-key", "https://example.invalid")
        with patch.object(
            pipeline,
            "_chat",
            new=AsyncMock(side_effect=EvolutionAgentError("知识进化 Agent 调用失败")),
        ):
            with self.assertRaisesRegex(EvolutionAgentError, "调用失败"):
                await pipeline.run({"name": "失败测试", "category": "测试", "content": "有效正文"})


if __name__ == "__main__":
    unittest.main()
