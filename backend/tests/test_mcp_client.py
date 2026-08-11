import unittest

from app.mcp_client import FetchMcpError, _ensure_public_url, normalize_page_content


class NormalizePageContentTests(unittest.TestCase):
    def test_html_is_readable_and_ignores_non_content_tags(self):
        content = normalize_page_content(
            "<article><h1>Title</h1><script>bad()</script><p>Body</p><style>.x{}</style></article>"
        )
        self.assertIn("Title", content)
        self.assertIn("Body", content)
        self.assertNotIn("bad", content)
        self.assertNotIn(".x", content)

    def test_content_is_bounded(self):
        self.assertEqual(normalize_page_content("abcdef", max_chars=4), "abcd")


class UrlSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_loopback_address_is_rejected(self):
        with self.assertRaises(FetchMcpError):
            await _ensure_public_url("http://127.0.0.1/private")

    async def test_localhost_name_is_rejected(self):
        with self.assertRaises(FetchMcpError):
            await _ensure_public_url("http://localhost/private")


if __name__ == "__main__":
    unittest.main()
