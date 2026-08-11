import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


TEST_DIR = Path(tempfile.mkdtemp(prefix="zhiyan-tests-"))
os.environ["DATABASE_PATH"] = str(TEST_DIR / "test.db")
os.environ["UPLOAD_DIR"] = str(TEST_DIR / "uploads")

from fastapi.testclient import TestClient
from app.main import app
from app.material_qa_agent import answer_material_question as local_answer_material_question
from app.mcp_client import FetchMcpNotConfigured


class ApiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        response = cls.client.post("/api/auth/login", json={"username": "demo@zhiyan.ai", "password": "demo123456"})
        assert response.status_code == 200, response.text
        cls.headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_health_and_dashboard(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        dashboard = self.client.get("/api/dashboard", headers=self.headers)
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("knowledge_total", dashboard.json())

    def test_material_and_chat_flow(self):
        created = self.client.post("/api/materials/text", headers=self.headers, json={"name": "测试知识", "content": "向量检索用于寻找语义相似的知识片段。", "category": "测试"})
        self.assertEqual(created.status_code, 201)
        materials = self.client.get("/api/materials?q=测试", headers=self.headers).json()
        self.assertTrue(any(item["name"] == "测试知识" for item in materials))
        answer = self.client.post("/api/ai/chat", headers=self.headers, json={"question": "什么是向量检索？"})
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(answer.json()["citations"])

    def test_material_ask_returns_original_and_answer(self):
        materials = self.client.get("/api/materials", headers=self.headers).json()
        material = next(item for item in materials if item["status"] == "ready" and item["content"])
        async def local_agent(material, question, **_):
            return await local_answer_material_question(material, question)

        with patch("app.main.answer_material_question", new=local_agent):
            answer = self.client.post(
                f"/api/materials/{material['id']}/ask",
                headers=self.headers,
                json={"question": "What is this material about?"},
            )
        self.assertEqual(answer.status_code, 200)
        payload = answer.json()
        self.assertEqual(payload["mode"], "local-material-agent")
        self.assertTrue(payload["original_content"])
        self.assertTrue(payload["answer"])

    def test_manual_text_normalizes_and_validates_input(self):
        created = self.client.post(
            "/api/materials/text",
            headers=self.headers,
            json={"name": "  手动笔记  ", "content": "  第一行\n第二行  ", "category": "  "},
        )
        self.assertEqual(created.status_code, 201)
        material = created.json()
        self.assertEqual(material["name"], "手动笔记")
        self.assertEqual(material["content"], "第一行\n第二行")
        self.assertEqual(material["category"], "未分类")
        self.assertEqual(material["size"], len("第一行\n第二行".encode("utf-8")))

        empty = self.client.post(
            "/api/materials/text",
            headers=self.headers,
            json={"name": "空白内容", "content": "   ", "category": "测试"},
        )
        self.assertEqual(empty.status_code, 422)
        self.assertIn("知识内容", empty.json()["detail"])

        self.assertEqual(
            self.client.delete(f"/api/materials/{material['id']}", headers=self.headers).status_code,
            204,
        )

    def test_url_requires_fetch_mcp_configuration(self):
        with patch(
            "app.main.fetch_url_content",
            new=AsyncMock(side_effect=FetchMcpNotConfigured("Fetch MCP is not configured")),
        ):
            response = self.client.post(
                "/api/materials/url",
                headers=self.headers,
                json={"name": "probe", "url": "https://example.com", "category": "test"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("Fetch MCP", response.json()["detail"])

    def test_url_preview_then_commit(self):
        url = "https://example.com/article"
        content = "Example article\n\nA useful preview body."
        before = len(self.client.get("/api/materials", headers=self.headers).json())
        with patch("app.main.fetch_url_content", new=AsyncMock(return_value=content)) as fetch:
            preview = self.client.post(
                "/api/materials/url/preview",
                headers=self.headers,
                json={"url": url},
            )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["title"], "Example article")
        self.assertEqual(len(self.client.get("/api/materials", headers=self.headers).json()), before)

        with patch("app.main.fetch_url_content", new=AsyncMock()) as fetch_on_commit:
            created = self.client.post(
                "/api/materials/url",
                headers=self.headers,
                json={
                    "name": "Confirmed article",
                    "url": url,
                    "category": "Research",
                    "content": preview.json()["content"],
                },
            )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["origin_url"], url)
        self.assertEqual(created.json()["content"], content)
        fetch.assert_awaited_once_with(url)
        fetch_on_commit.assert_not_awaited()

    def test_image_ocr_preview_then_commit(self):
        image = b"fake-png-for-mocked-ocr"
        metadata = {"width": 1200, "height": 800, "format": "PNG"}
        ocr_result = {
            **metadata,
            "content": "Knowledge Graph\nOCR preview text",
            "lines": 2,
            "confidence": 0.9632,
        }
        before = len(self.client.get("/api/materials", headers=self.headers).json())
        with (
            patch("app.main.inspect_image", return_value=metadata),
            patch("app.main.extract_image_text", return_value=ocr_result) as recognize,
        ):
            preview = self.client.post(
                "/api/materials/image/preview",
                headers=self.headers,
                files={"file": ("knowledge.png", image, "image/png")},
            )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["content"], ocr_result["content"])
        self.assertEqual(len(self.client.get("/api/materials", headers=self.headers).json()), before)
        recognize.assert_called_once_with(image)

        with patch("app.main.inspect_image", return_value=metadata):
            created = self.client.post(
                "/api/materials/image",
                headers=self.headers,
                files={"file": ("knowledge.png", image, "image/png")},
                data={
                    "name": "OCR knowledge",
                    "category": "Research",
                    "content": preview.json()["content"],
                },
            )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["source"], "image")
        self.assertEqual(created.json()["status"], "ready")
        file_response = self.client.get(
            f"/api/materials/{created.json()['id']}/file", headers=self.headers
        )
        self.assertEqual(file_response.status_code, 200)
        self.assertEqual(file_response.content, image)
        self.assertEqual(
            self.client.delete(f"/api/materials/{created.json()['id']}", headers=self.headers).status_code,
            204,
        )
        self.assertEqual(
            self.client.get(f"/api/materials/{created.json()['id']}/file", headers=self.headers).status_code,
            404,
        )

    def test_video_preview_then_commit(self):
        video = b"fake-video-for-mocked-analysis"
        analysis = {
            "duration": 75.3,
            "width": 1920,
            "height": 1080,
            "content": "Embedded subtitle\nKeyframe OCR text",
            "subtitle_lines": 1,
            "keyframes": 3,
            "confidence": 0.9123,
        }
        before = len(self.client.get("/api/materials", headers=self.headers).json())
        with patch("app.main.analyze_video_text", return_value=analysis) as analyze:
            preview = self.client.post(
                "/api/materials/video/preview",
                headers=self.headers,
                files={"file": ("lecture.webm", video, "video/webm")},
            )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["content"], analysis["content"])
        self.assertEqual(preview.json()["characters"], len(analysis["content"]))
        self.assertEqual(len(self.client.get("/api/materials", headers=self.headers).json()), before)
        analyze.assert_called_once_with(video, ".webm")

        created = self.client.post(
            "/api/materials/video",
            headers=self.headers,
            files={"file": ("lecture.webm", video, "video/webm")},
            data={
                "name": "Video knowledge",
                "category": "Research",
                "content": preview.json()["content"],
            },
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["source"], "video")
        self.assertEqual(created.json()["kind"], "视频")
        self.assertEqual(created.json()["status"], "ready")
        file_response = self.client.get(
            f"/api/materials/{created.json()['id']}/file", headers=self.headers
        )
        self.assertEqual(file_response.status_code, 200)
        self.assertEqual(file_response.content, video)

    def test_evolution_review_flow(self):
        first = self.client.post(
            "/api/materials/text", headers=self.headers,
            json={"name": "待进化知识 A", "content": "原始知识 A。", "category": "测试"},
        ).json()
        second = self.client.post(
            "/api/materials/text", headers=self.headers,
            json={"name": "待进化知识 B", "content": "原始知识 B。", "category": "测试"},
        ).json()
        with patch(
            "app.main._generate_evolution_proposal",
            new=AsyncMock(side_effect=[
                ("# 进化知识 A\n\n结构化正文 A。", "补充结构"),
                ("# 进化知识 B\n\n结构化正文 B。", "补充结构"),
            ]),
        ):
            started = self.client.post(
                "/api/evolution/start", headers=self.headers,
                json={"mode": "manual", "material_ids": [first["id"], second["id"]]},
            )
        self.assertEqual(started.status_code, 201)
        self.assertEqual(started.json()["status"], "review")

        overview = self.client.get("/api/evolution", headers=self.headers).json()
        pending = [item for item in overview["pending"] if item["task_id"] == started.json()["task_id"]]
        self.assertEqual([item["material_id"] for item in pending], [first["id"], second["id"]])

        accepted_text = "# 人工确认版本 A\n\n已完成进化。"
        accepted = self.client.patch(
            f"/api/evolution/reviews/{pending[0]['id']}", headers=self.headers,
            json={"decision": "accepted", "proposed_text": accepted_text},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["version"], 1)
        rejected = self.client.patch(
            f"/api/evolution/reviews/{pending[1]['id']}", headers=self.headers,
            json={"decision": "rejected"},
        )
        self.assertEqual(rejected.status_code, 200)

        materials = {
            item["id"]: item for item in self.client.get("/api/materials", headers=self.headers).json()
        }
        self.assertEqual(materials[first["id"]]["content"], accepted_text)
        self.assertEqual(materials[second["id"]]["content"], "原始知识 B。")
        versions = self.client.get(
            f"/api/materials/{first['id']}/evolution-versions", headers=self.headers,
        ).json()
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["previous_content"], "原始知识 A。")
        self.assertEqual(versions[0]["new_content"], accepted_text)
        self.assertEqual(
            self.client.patch(
                f"/api/evolution/reviews/{pending[0]['id']}", headers=self.headers,
                json={"decision": "accepted"},
            ).status_code,
            409,
        )
        completed = self.client.get("/api/evolution", headers=self.headers).json()["latest"]
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["accepted_count"], 1)
        self.assertEqual(completed["rejected_count"], 1)

        with patch(
            "app.main._generate_evolution_proposal",
            new=AsyncMock(return_value=("# 自动进化版本\n\n已自动应用。", "自动优化")),
        ):
            automatic = self.client.post(
                "/api/evolution/start", headers=self.headers,
                json={"mode": "auto", "material_ids": [first["id"]]},
            )
        self.assertEqual(automatic.status_code, 201)
        self.assertEqual(automatic.json()["status"], "completed")
        self.assertEqual(automatic.json()["task"]["accepted_count"], 1)
        self.assertEqual(automatic.json()["reviews"][0]["decision"], "accepted")
        self.assertEqual(automatic.json()["reviews"][0]["version"], 2)
        versions = self.client.get(
            f"/api/materials/{first['id']}/evolution-versions", headers=self.headers,
        ).json()
        self.assertEqual([item["version"] for item in versions], [2, 1])

        rolled_back = self.client.post(
            f"/api/evolution/reviews/{automatic.json()['reviews'][0]['id']}/rollback",
            headers=self.headers,
        )
        self.assertEqual(rolled_back.status_code, 200)
        self.assertEqual(rolled_back.json()["decision"], "rolled_back")
        self.assertEqual(rolled_back.json()["version"], 3)
        restored = {
            item["id"]: item for item in self.client.get("/api/materials", headers=self.headers).json()
        }
        self.assertEqual(restored[first["id"]]["content"], accepted_text)
        rolled_overview = self.client.get("/api/evolution", headers=self.headers).json()
        self.assertEqual(rolled_overview["latest"]["rolled_back_count"], 1)
        versions = self.client.get(
            f"/api/materials/{first['id']}/evolution-versions", headers=self.headers,
        ).json()
        self.assertEqual([item["version"] for item in versions], [3, 2, 1])

        disposable = self.client.post(
            "/api/materials/text", headers=self.headers,
            json={"name": "审核中删除", "content": "待删除正文。", "category": "测试"},
        ).json()
        with patch(
            "app.main._generate_evolution_proposal",
            new=AsyncMock(return_value=("# 待删除建议", "结构优化")),
        ):
            interrupted = self.client.post(
                "/api/evolution/start", headers=self.headers,
                json={"mode": "manual", "material_ids": [disposable["id"]]},
            )
        self.assertEqual(interrupted.status_code, 201)
        self.assertEqual(
            self.client.delete(f"/api/materials/{disposable['id']}", headers=self.headers).status_code,
            204,
        )
        interrupted_overview = self.client.get("/api/evolution", headers=self.headers).json()
        self.assertFalse(interrupted_overview["pending"])
        self.assertEqual(interrupted_overview["latest"]["status"], "completed")

        for material_id in (first["id"], second["id"]):
            self.assertEqual(
                self.client.delete(f"/api/materials/{material_id}", headers=self.headers).status_code,
                204,
            )

    def test_auto_evolution_is_all_or_nothing(self):
        first = self.client.post(
            "/api/materials/text", headers=self.headers,
            json={"name": "自动事务 A", "content": "事务原文 A。", "category": "测试"},
        ).json()
        second = self.client.post(
            "/api/materials/text", headers=self.headers,
            json={"name": "自动事务 B", "content": "事务原文 B。", "category": "测试"},
        ).json()
        oversized = "超" * 100_001
        with patch(
            "app.main._generate_evolution_proposal",
            new=AsyncMock(side_effect=[
                ("# 自动进化 A\n\n有效结果。", "质量审核通过"),
                (oversized, "超长结果"),
            ]),
        ):
            response = self.client.post(
                "/api/evolution/start", headers=self.headers,
                json={"mode": "auto", "material_ids": [first["id"], second["id"]]},
            )
        self.assertEqual(response.status_code, 413)
        materials = {
            item["id"]: item for item in self.client.get("/api/materials", headers=self.headers).json()
        }
        self.assertEqual(materials[first["id"]]["content"], "事务原文 A。")
        self.assertEqual(materials[second["id"]]["content"], "事务原文 B。")
        overview = self.client.get("/api/evolution", headers=self.headers).json()
        self.assertEqual(overview["latest"]["status"], "failed")
        self.assertEqual(overview["latest"]["review_count"], 0)
        self.assertIn("原素材未发生变更", overview["latest"]["summary"])
        for material_id in (first["id"], second["id"]):
            self.assertEqual(
                self.client.delete(f"/api/materials/{material_id}", headers=self.headers).status_code,
                204,
            )

    def test_game_graph_settings_and_share(self):
        question = self.client.get("/api/games/flashcard/question?difficulty=medium", headers=self.headers).json()
        result = self.client.post("/api/games/flashcard/submit", headers=self.headers, json={"question_id": question["id"], "answer": question["options"][0], "duration": 12})
        self.assertEqual(result.status_code, 200)
        graph = self.client.get("/api/graph", headers=self.headers).json()
        self.assertGreater(len(graph["nodes"]), 3)
        settings = self.client.get("/api/settings", headers=self.headers).json()
        settings["trigger_time"] = "03:30"
        self.assertEqual(self.client.put("/api/settings", headers=self.headers, json=settings).status_code, 200)
        share = self.client.post("/api/shares", headers=self.headers, json={"name": "测试分享", "description": "只读空间", "scope": "all", "expires_days": 7}).json()
        public = self.client.get(f"/api/share/{share['id']}")
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.json()["name"], "测试分享")

    def test_memory_game_completion_records_both_difficulties(self):
        easy = self.client.post(
            "/api/games/flashcard/complete",
            headers=self.headers,
            json={"difficulty": "easy", "moves": 8, "duration": 24},
        )
        self.assertEqual(easy.status_code, 200, easy.text)
        self.assertEqual(easy.json()["moves"], 8)
        self.assertEqual(easy.json()["xp"], 180)

        hard = self.client.post(
            "/api/games/flashcard/complete",
            headers=self.headers,
            json={"difficulty": "hard", "moves": 18, "duration": 75},
        )
        self.assertEqual(hard.status_code, 200, hard.text)
        self.assertEqual(hard.json()["moves"], 18)
        self.assertEqual(hard.json()["xp"], 360)
        self.assertGreater(hard.json()["score"], easy.json()["score"])

        impossible = self.client.post(
            "/api/games/flashcard/complete",
            headers=self.headers,
            json={"difficulty": "hard", "moves": 17, "duration": 30},
        )
        self.assertEqual(impossible.status_code, 422)

        missing_pack = self.client.post(
            "/api/games/flashcard/complete",
            headers=self.headers,
            json={"difficulty": "easy", "moves": 8, "duration": 30, "pack_id": 999999},
        )
        self.assertEqual(missing_pack.status_code, 404)

        overview = self.client.get("/api/games", headers=self.headers).json()
        flashcard_best = next(item for item in overview["best"] if item["game"] == "flashcard")
        self.assertGreaterEqual(flashcard_best["score"], hard.json()["score"])

    def test_agent_game_packs_from_selected_materials(self):
        material = self.client.post(
            "/api/materials/text", headers=self.headers,
            json={
                "name": "检索学习材料",
                "content": "向量检索用于寻找语义相似内容。嵌入模型将文本转换为向量。混合检索结合语义与关键词匹配。",
                "category": "人工智能",
            },
        ).json()
        points = [
            {
                "term": f"知识点 {index}", "definition": f"知识点 {index} 的正确定义。",
                "fact": f"这是知识点 {index} 的素材解释。", "source_material_id": material["id"],
                "source_name": material["name"], "distractors": [f"错误定义 {index}-A", f"错误定义 {index}-B"],
            }
            for index in range(1, 9)
        ]
        with patch(
            "app.main.agent_extract_knowledge",
            new=AsyncMock(return_value=(points, "deepseek-agent", "Agent 提取完成")),
        ):
            packs = {}
            for game in ("flashcard", "monopoly", "matching"):
                response = self.client.post(
                    "/api/games/generate", headers=self.headers,
                    json={"game": game, "difficulty": "medium", "material_ids": [material["id"]]},
                )
                self.assertEqual(response.status_code, 201, response.text)
                packs[game] = response.json()

        for game, pack in packs.items():
            self.assertEqual(pack["game"], game)
            self.assertEqual(pack["source_mode"], "deepseek-agent")
            self.assertEqual(pack["material_ids"], [material["id"]])
            self.assertEqual(len(pack["questions"]), 6)
            self.assertNotIn("answer", pack["questions"][0])
            question = pack["questions"][0]
            point = next(
                item for item in points
                if item["definition"] == question["prompt"]
            ) if game == "matching" else next(
                item for item in points if item["term"] == question["topic"]
            )
            answer = point["term"] if game == "matching" else point["definition"]
            submitted = self.client.post(
                f"/api/games/{game}/submit", headers=self.headers,
                json={"question_id": question["id"], "pack_id": pack["id"], "answer": answer, "duration": 5},
            )
            self.assertEqual(submitted.status_code, 200)
            self.assertTrue(submitted.json()["correct"])
            wrong_pack = self.client.post(
                f"/api/games/{game}/submit", headers=self.headers,
                json={"question_id": question["id"], "pack_id": pack["id"] + 999, "answer": answer, "duration": 5},
            )
            self.assertEqual(wrong_pack.status_code, 422)

        memory_complete = self.client.post(
            "/api/games/flashcard/complete", headers=self.headers,
            json={"difficulty": "easy", "moves": 8, "duration": 20, "pack_id": packs["flashcard"]["id"]},
        )
        self.assertEqual(memory_complete.status_code, 200, memory_complete.text)

        overview = self.client.get("/api/games", headers=self.headers).json()
        self.assertTrue(any(item["id"] == material["id"] for item in overview["materials"]))
        self.assertGreaterEqual(len(overview["recent_packs"]), 3)
        self.assertEqual(
            self.client.delete(f"/api/materials/{material['id']}", headers=self.headers).status_code,
            204,
        )

if __name__ == "__main__":
    unittest.main()
