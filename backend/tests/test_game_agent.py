import unittest

from app.game_agent import build_game_questions


class LocalGameAgentTests(unittest.TestCase):
    def setUp(self):
        self.points = [
            {
                "term": f"知识点{index}",
                "definition": f"知识点{index} 的标准定义",
                "fact": f"知识点{index} 的素材依据",
                "expanded_text": f"知识点{index} 的扩展解释",
                "source_material_id": 7,
                "source_name": "向量检索笔记.md",
                "distractors": [f"错误定义{index}-A", f"错误定义{index}-B", f"错误定义{index}-C"],
            }
            for index in range(1, 19)
        ]

    def test_builds_all_three_game_frameworks(self):
        for game in ("flashcard", "monopoly", "matching"):
            questions = build_game_questions(game, "medium", self.points)
            self.assertEqual(len(questions), 6)
            self.assertTrue(all(question["answer"] in question["options"] for question in questions))
            expected_type = "concept-definition" if game == "matching" else "multiple-choice"
            self.assertTrue(all(question["question_type"] == expected_type for question in questions))

        hard_memory = build_game_questions("flashcard", "hard", self.points)
        self.assertEqual(len(hard_memory), 18)


if __name__ == "__main__":
    unittest.main()
