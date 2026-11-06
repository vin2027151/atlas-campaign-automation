"""Quick Chat: message rules, history cap, rate limit, stub send. Run: .venv/bin/python -m unittest tests.test_quickchat"""
import os
import unittest

os.environ["ATLAS_LLM_MODE"] = "stub"

import quickchat  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import app  # noqa: E402


class QuickChatTests(unittest.TestCase):
    def test_rules(self):
        msgs = quickchat.clean_messages([{"role": "assistant", "content": "old"}, {"role": "user", "content": "a"},
                                         {"role": "user", "content": "b"}])
        self.assertEqual(msgs, [{"role": "user", "content": "a\n\nb"}])
        with self.assertRaises(quickchat.ChatError):
            quickchat.clean_messages([{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}])
        with self.assertRaises(quickchat.ChatError):
            quickchat.clean_messages([{"role": "user", "content": "x" * 4001}])
        with self.assertRaises(quickchat.ChatError):
            quickchat.clean_messages([{"role": "system", "content": "x"}])

    def test_cap_20(self):
        many = []
        for i in range(30):
            many += [{"role": "user", "content": "q%d" % i}, {"role": "assistant", "content": "a%d" % i}]
        many.append({"role": "user", "content": "last"})
        msgs = quickchat.clean_messages(many)
        self.assertLessEqual(len(msgs), quickchat.MAX_HISTORY)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[-1]["content"], "last")

    def test_context_sections(self):
        doc, meta = quickchat.build_context()
        for h in ("## 1. Company and offerings", "## 2. Account state summary", "## 8. The 30-day plan", "## 9. Full account state"):
            self.assertIn(h, doc)
        self.assertIn("$199/mo", doc)
        self.assertTrue(meta["snapshot_id"])

    def test_api_and_rate_limit(self):
        c = TestClient(app.app)
        r = c.post("/api/chat/send", json={"messages": [{"role": "user", "content": "hi"}]}, headers={"cf-connecting-ip": "203.0.113.9"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["reply"])
        old = quickchat.PER_IP_PER_HOUR
        quickchat.PER_IP_PER_HOUR = 1
        try:
            r = c.post("/api/chat/send", json={"messages": [{"role": "user", "content": "again"}]}, headers={"cf-connecting-ip": "203.0.113.9"})
            self.assertEqual(r.status_code, 429)
        finally:
            quickchat.PER_IP_PER_HOUR = old
        self.assertEqual(c.post("/api/chat/send", json={"messages": []}).status_code, 400)
        self.assertEqual(c.get("/api/chat/context").status_code, 200)


if __name__ == "__main__":
    unittest.main()
