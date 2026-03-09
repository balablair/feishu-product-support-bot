"""
对话历史管理的单元测试（不依赖真实 API）
"""
import collections
import time
import unittest
from unittest.mock import patch, MagicMock


class TestConversationHistory(unittest.TestCase):
    """测试 _get_context_key / _get_history / _add_to_history 的行为"""

    def setUp(self):
        # 每个测试前清空历史，避免状态污染
        import app
        with app._history_lock:
            app._histories.clear()
            app._history_timestamps.clear()
        self.app = app

    def test_context_key_with_thread(self):
        """有 root_id 时，key 应为 thread:{root_id}"""
        msg = MagicMock()
        msg.root_id = "thread_abc"
        msg.chat_id = "chat_xyz"
        key = self.app._get_context_key(msg, "user_001")
        self.assertEqual(key, "thread:thread_abc")

    def test_context_key_without_thread(self):
        """无 root_id 时，key 应为 chat:{chat_id}:user:{sender_id}"""
        msg = MagicMock()
        msg.root_id = ""
        msg.chat_id = "chat_xyz"
        key = self.app._get_context_key(msg, "user_001")
        self.assertEqual(key, "chat:chat_xyz:user:user_001")

    def test_context_key_root_id_none(self):
        """root_id 为 None 时与空字符串行为一致"""
        msg = MagicMock()
        msg.root_id = None
        msg.chat_id = "chat_xyz"
        key = self.app._get_context_key(msg, "user_001")
        self.assertEqual(key, "chat:chat_xyz:user:user_001")

    def test_history_empty_by_default(self):
        """新 key 的历史应为空列表"""
        history = self.app._get_history("brand_new_key")
        self.assertEqual(history, [])

    def test_add_and_get_history(self):
        """追加一轮对话后，历史应包含 user + assistant 两条"""
        self.app._add_to_history("key1", "你好", "你好！有什么可以帮你？")
        history = self.app._get_history("key1")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0], {"role": "user", "content": "你好"})
        self.assertEqual(history[1], {"role": "assistant", "content": "你好！有什么可以帮你？"})

    def test_history_respects_max_turns(self):
        """超出 MAX_HISTORY_TURNS 时，最旧的记录应被丢弃"""
        max_turns = self.app.MAX_HISTORY_TURNS
        for i in range(max_turns + 3):
            self.app._add_to_history("key2", f"问题{i}", f"回答{i}")
        history = self.app._get_history("key2")
        self.assertEqual(len(history), max_turns * 2)
        # 最新的内容应保留
        self.assertEqual(history[-1]["content"], f"回答{max_turns + 2}")

    def test_history_ttl_expiry(self):
        """超过 TTL 后，历史应自动重置"""
        self.app._add_to_history("key3", "旧消息", "旧回复")
        # 手动设置时间戳为过去，模拟 TTL 超时
        with self.app._history_lock:
            self.app._history_timestamps["key3"] = time.time() - self.app.HISTORY_TTL - 1
        history = self.app._get_history("key3")
        self.assertEqual(history, [])

    def test_multiple_users_independent_history(self):
        """不同用户在同一群的历史应相互独立"""
        self.app._add_to_history("chat:chat1:user:alice", "alice的问题", "给alice的回答")
        self.app._add_to_history("chat:chat1:user:bob", "bob的问题", "给bob的回答")
        alice_history = self.app._get_history("chat:chat1:user:alice")
        bob_history = self.app._get_history("chat:chat1:user:bob")
        self.assertEqual(alice_history[0]["content"], "alice的问题")
        self.assertEqual(bob_history[0]["content"], "bob的问题")


class TestGenerateReply(unittest.TestCase):
    """测试 generate_reply 的消息构建逻辑"""

    @patch("app.requests.post")
    def test_history_is_included_in_messages(self, mock_post):
        """传入 history 时，messages 列表应包含历史记录"""
        mock_post.return_value.json.return_value = {
            "choices": [{"message": {"content": "回复内容"}}]
        }
        mock_post.return_value.raise_for_status = MagicMock()

        import app
        with patch.object(app.Config, "OPENAI_API_KEY", "sk-test"):
            history = [
                {"role": "user", "content": "上一条问题"},
                {"role": "assistant", "content": "上一条回答"},
            ]
            app.generate_reply("当前问题", history=history)

        called_messages = mock_post.call_args[1]["json"]["messages"]
        roles = [m["role"] for m in called_messages]
        # 应该是 system → user(历史) → assistant(历史) → user(当前)
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(called_messages[-1]["content"], "当前问题")

    @patch("app.requests.post")
    def test_no_history_sends_single_user_message(self, mock_post):
        """不传 history 时，messages 应只有 system + 当前 user"""
        mock_post.return_value.json.return_value = {
            "choices": [{"message": {"content": "回复"}}]
        }
        mock_post.return_value.raise_for_status = MagicMock()

        import app
        with patch.object(app.Config, "OPENAI_API_KEY", "sk-test"):
            app.generate_reply("问题", history=None)

        called_messages = mock_post.call_args[1]["json"]["messages"]
        self.assertEqual(len(called_messages), 2)
        self.assertEqual(called_messages[0]["role"], "system")
        self.assertEqual(called_messages[1]["role"], "user")

    @patch("app.requests.post", side_effect=Exception("timeout"))
    def test_fallback_on_api_failure(self, mock_post):
        """API 调用失败时应返回兜底文本而非抛出异常"""
        import app
        with patch.object(app.Config, "OPENAI_API_KEY", "sk-test"):
            result = app.generate_reply("问题")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


class TestFeedbackClassification(unittest.TestCase):
    """测试反馈分类的解析逻辑"""

    def test_parse_valid_category(self):
        """合法分类应被正确解析"""
        from feedback import _CATEGORIES
        self.assertIn("Bug报错", _CATEGORIES)
        self.assertIn("功能建议", _CATEGORIES)
        self.assertIn("使用问题", _CATEGORIES)
        self.assertIn("其他", _CATEGORIES)

    @patch("feedback.requests.post")
    def test_non_feedback_returns_none(self, mock_post):
        """AI 回复'无'时应返回 (None, None)"""
        mock_post.return_value.json.return_value = {
            "choices": [{"message": {"content": "无"}}]
        }
        mock_post.return_value.raise_for_status = MagicMock()

        from feedback import ai_detect_and_classify
        with patch("feedback.Config") as cfg:
            cfg.OPENAI_API_KEY = "sk-test"
            cfg.OPENAI_API_URL = "https://example.com"
            cfg.OPENAI_MODEL = "test-model"
            category, summary = ai_detect_and_classify("今天天气不错")
        self.assertIsNone(category)
        self.assertIsNone(summary)

    @patch("feedback.requests.post")
    def test_bug_feedback_parsed_correctly(self, mock_post):
        """AI 回复 Bug 分类时应正确解析"""
        mock_post.return_value.json.return_value = {
            "choices": [{"message": {"content": "Bug报错\n登录页面白屏"}}]
        }
        mock_post.return_value.raise_for_status = MagicMock()

        from feedback import ai_detect_and_classify
        with patch("feedback.Config") as cfg:
            cfg.OPENAI_API_KEY = "sk-test"
            cfg.OPENAI_API_URL = "https://example.com"
            cfg.OPENAI_MODEL = "test-model"
            category, summary = ai_detect_and_classify("点击登录按钮后页面变白了")
        self.assertEqual(category, "Bug报错")
        self.assertEqual(summary, "登录页面白屏")

    @patch("feedback.requests.post")
    def test_unknown_category_falls_back_to_other(self, mock_post):
        """AI 返回不在列表中的分类时应降级为'其他'"""
        mock_post.return_value.json.return_value = {
            "choices": [{"message": {"content": "崩溃\n应用闪退"}}]
        }
        mock_post.return_value.raise_for_status = MagicMock()

        from feedback import ai_detect_and_classify
        with patch("feedback.Config") as cfg:
            cfg.OPENAI_API_KEY = "sk-test"
            cfg.OPENAI_API_URL = "https://example.com"
            cfg.OPENAI_MODEL = "test-model"
            category, summary = ai_detect_and_classify("打开 app 闪退")
        self.assertEqual(category, "其他")


class TestConfig(unittest.TestCase):
    """测试配置加载"""

    def test_admin_open_ids_parsed_as_set(self):
        """ADMIN_OPEN_IDS 应被解析为 set"""
        from config import Config
        self.assertIsInstance(Config.ADMIN_OPEN_IDS, set)

    def test_max_history_turns_is_int(self):
        from config import Config
        self.assertIsInstance(Config.MAX_HISTORY_TURNS, int)
        self.assertGreater(Config.MAX_HISTORY_TURNS, 0)

    def test_history_ttl_is_int(self):
        from config import Config
        self.assertIsInstance(Config.HISTORY_TTL, int)
        self.assertGreater(Config.HISTORY_TTL, 0)


if __name__ == "__main__":
    unittest.main()
