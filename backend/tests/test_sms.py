import unittest
import json
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from app.sms import _try_dypnsapi_send, _verification_passed


class SmsVerificationResultTests(unittest.TestCase):
    def test_accepts_pass_string(self):
        self.assertTrue(_verification_passed({"Model": {"VerifyResult": "PASS"}}))

    def test_accepts_boolean_true(self):
        self.assertTrue(_verification_passed({"Model": {"VerifyResult": True}}))

    def test_rejects_failed_or_missing_result(self):
        self.assertFalse(_verification_passed({"Model": {"VerifyResult": "FAIL"}}))
        self.assertFalse(_verification_passed({"Model": {}}))
        self.assertFalse(_verification_passed({}))

    @patch("urllib.request.urlopen")
    def test_dypns_send_uses_provider_generated_code_placeholder(self, urlopen):
        response = MagicMock()
        response.read.return_value = b'{"Code":"OK"}'
        urlopen.return_value.__enter__.return_value = response

        result = _try_dypnsapi_send("13800138000")

        request = urlopen.call_args.args[0]
        query = parse_qs(urlparse(request.full_url).query)
        template_params = json.loads(query["TemplateParam"][0])
        self.assertEqual(template_params["code"], "##code##")
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
