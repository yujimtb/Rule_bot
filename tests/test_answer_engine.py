from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import subprocess
from unittest.mock import patch

from rulebot.answer_engine import answer_question
from rulebot.document_store import load_chunks


class AnswerEngineTest(unittest.TestCase):
    def test_loads_markdown_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rules.md").write_text("# 生活\n\n## 食器\n割れた食器はスタッフへ報告します。\n", encoding="utf-8")
            (root / "qa.csv").write_text("question,answer\n消灯は？,消灯後は静かにします。\n", encoding="utf-8")

            chunks = load_chunks(root)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(any("割れた食器" in chunk.text for chunk in chunks))
        self.assertTrue(any("消灯後" in chunk.text for chunk in chunks))

    def test_loads_numbered_markdown_heading_as_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rules.md").write_text(
                "# はじめに\n\n前文です。\n\n9. # **ゲストに関して** {#guest}\n\n* ゲストの滞在可能時間は7:00 - 24:00までとします。\n",
                encoding="utf-8",
            )

            chunks = load_chunks(root)

        self.assertTrue(any("ゲストに関して" in chunk.location for chunk in chunks))
        self.assertTrue(any("滞在可能時間" in chunk.text for chunk in chunks if "ゲストに関して" in chunk.location))

    def test_answers_known_question_with_citation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rules.md").write_text(
                "# 生活ルール\n\n## 割れた食器\n食器を割った場合はスタッフへ報告してください。\n",
                encoding="utf-8",
            )

            answer = answer_question("食器を割ったらどうする？", root)

        self.assertIn("食器", answer.answer)
        self.assertTrue(answer.citations)
        self.assertFalse(answer.unknowns)

    def test_unknown_question_does_not_guess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rules.md").write_text("# 生活ルール\n\n## 食器\n食器は丁寧に扱います。\n", encoding="utf-8")

            answer = answer_question("Wi-Fiのパスワードは？", root)

        self.assertIn("確認できません", answer.answer)
        self.assertFalse(answer.citations)
        self.assertTrue(answer.unknowns)

    def test_slack_format_contains_required_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rules.md").write_text("# 生活ルール\n\n## 消灯\n消灯後は静かにしてください。\n", encoding="utf-8")

            answer = answer_question("消灯後に話してよい？", root)
            text = answer.to_slack_text()

        self.assertIn("*回答*", text)
        self.assertIn("*根拠*", text)
        self.assertIn("*不明な点*", text)

    def test_codex_app_server_backend_runs_in_answer_service_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rules.md").write_text("# 生活ルール\n\n## ゲスト\n宿泊できません。\n", encoding="utf-8")
            with patch.dict("os.environ", {"AGENT_CLI_PROVIDER": "codex_app_server"}, clear=True), patch(
                "rulebot.codex_agent._run_codex_app_server",
                return_value={
                    "answer": "宿泊できません。",
                    "citations": ["rules.md"],
                    "unknowns": [],
                    "usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10},
                    "usage_chargeable": False,
                },
            ) as run:
                answer = answer_question("ゲストは宿泊できますか？", root, backend="agent")

        run.assert_called_once()
        self.assertEqual(answer.answer, "宿泊できません。")
        self.assertFalse(answer.usage_chargeable)
        self.assertEqual(answer.usage["effective_tokens"], 30)

    def test_agent_command_error_is_sanitized(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Failed to refresh token: 401 Unauthorized refresh_token_reused",
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "AGENT_CLI_PROVIDER": "codex",
                "AGENT_COMMAND": "python -m fake",
                "AGENT_TIMEOUT_SECONDS": "60",
            },
            clear=True,
        ), patch("rulebot.answer_engine.subprocess.run", return_value=completed):
            answer = answer_question("ゲストの滞在時間は？", Path(tmp), backend="agent")

        self.assertEqual(answer.answer, "回答生成に失敗しました。")
        self.assertIn("再ログイン", answer.unknowns[0])
        self.assertNotIn("refresh_token", answer.unknowns[0])


if __name__ == "__main__":
    unittest.main()
