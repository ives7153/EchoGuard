import unittest
from unittest.mock import patch

from upper_computer.ai.judgement import AISettings, run_ai_chat


class AIChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {
            "context_label": "当前快照 + 最近5分钟",
            "status": "数据不足",
            "detail": "参与节点：1；触发节点：无；时间窗口：最近 5 秒",
            "participants": "node2",
            "triggered": "无",
            "thresholds": "presence>=0.60, confidence>=0.65, gas>=1000ppm",
            "node_lines": ["node2 online=True presence=0.52 motion=0.18 confidence=0.73 gas_ppm=420"],
            "event_lines": ["SERIAL OK: Gateway connected"],
            "ai_detail": {"risk": "仅单节点参与，需继续观察。"},
        }

    def test_ai_disabled_uses_rule_fallback_chat(self) -> None:
        result = run_ai_chat(
            AISettings(enabled=False, embedding_enabled=False, llm_enabled=False),
            "为什么低置信？",
            self.context,
            [],
        )

        self.assertEqual(result["source"], "rule_fallback")
        self.assertIn("低置信", result["answer"])
        self.assertNotIn("数据不足", result["answer"])
        self.assertNotIn("参与节点", result["answer"])
        self.assertNotIn("确认生命", result["answer"])
        self.assertFalse(result["answer"].startswith("建议"))

    def test_jina_snippet_path_uses_local_jina_source(self) -> None:
        snippet = {
            "label": "低置信解释",
            "text": "低置信 confidence",
            "answer": "低置信多由 CSI 样本不足或 RSSI 偏弱导致。",
            "score": 0.91,
        }
        with patch("upper_computer.ai.judgement.retrieve_chat_snippets", return_value=[snippet]):
            result = run_ai_chat(
                AISettings(enabled=True, embedding_enabled=True, llm_enabled=False),
                "为什么低置信？",
                self.context,
                [],
            )

        self.assertEqual(result["source"], "local_jina")
        self.assertIn("CSI 样本不足", result["answer"])
        self.assertNotIn("当前规则结论", result["answer"])
        self.assertFalse(result["answer"].startswith("建议"))

    def test_llm_path_keeps_chat_source_when_available(self) -> None:
        with patch(
            "upper_computer.ai.judgement.generate_llm_chat_answer",
            return_value="依据当前数据仅单节点参与；风险是误判较高；建议继续采集。",
        ):
            result = run_ai_chat(
                AISettings(
                    enabled=True,
                    embedding_enabled=False,
                    llm_enabled=True,
                    llm_base_url="https://example.invalid",
                    llm_model="demo-model",
                ),
                "下一步怎么排查？",
                self.context,
                [{"role": "user", "content": "刚刚为什么低置信？"}],
            )

        self.assertEqual(result["source"], "llm_api")
        self.assertIn("继续采集", result["answer"])
        self.assertNotIn("依据当前", result["answer"])

    def test_model_identity_names_echo_guard_and_llm_model(self) -> None:
        result = run_ai_chat(
            AISettings(
                enabled=True,
                embedding_enabled=True,
                llm_enabled=True,
                llm_provider="zhipu_glm",
                llm_base_url="https://open.bigmodel.cn/api/paas/v4",
                llm_model="glm-5.1",
            ),
            "你的底层模型是什么？",
            self.context,
            [],
        )

        self.assertEqual(result["source"], "llm_api")
        self.assertIn("EchoGuard 的 AI 辅助助手", result["answer"])
        self.assertIn("智谱 GLM-5.1", result["answer"])
        self.assertIn("Jina embedding", result["answer"])
        self.assertNotIn("问答模块", result["answer"])

    def test_model_identity_explains_local_jina_is_not_chat_model(self) -> None:
        result = run_ai_chat(
            AISettings(enabled=True, embedding_enabled=True, llm_enabled=False),
            "你是什么模型？",
            self.context,
            [],
        )

        self.assertEqual(result["source"], "local_jina")
        self.assertIn("EchoGuard 的 AI 辅助助手", result["answer"])
        self.assertIn("Jina 是向量检索模型", result["answer"])


if __name__ == "__main__":
    unittest.main()
