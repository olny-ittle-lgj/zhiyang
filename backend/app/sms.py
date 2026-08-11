"""
阿里云短信验证码模块。

API 选择策略（自动降级）：
  1. 优先尝试 Dypnsapi (SendSmsVerifyCode / CheckSmsVerifyCode)
  2. 失败则尝试 Dysmsapi (SendSms / 自校验)
  3. 全部失败则降级为演示模式（验证码 246810）

已配置的签名/模板：
  签名: 恒创联众
  模板: 100001
  模板内容: 您的验证码为${code}。尊敬的客户，以上验证码${min}分钟内有效，请注意保密，切勿告知他人。
  已认证手机号: 15197518572
"""

from __future__ import annotations

import logging
import os
import secrets as _secrets

from .services import redis_cache_set, redis_cache_get, redis_cache_delete

logger = logging.getLogger("zhiyan.sms")


def _verification_passed(result: dict) -> bool:
    model = result.get("Model")
    if not isinstance(model, dict):
        return False
    verify_result = model.get("VerifyResult")
    if verify_result is True:
        return True
    return isinstance(verify_result, str) and verify_result.upper() == "PASS"


def _access_key_id() -> str:
    return os.getenv("ALIYUN_ACCESS_KEY_ID", "")


def _access_key_secret() -> str:
    return os.getenv("ALIYUN_ACCESS_KEY_SECRET", "")


def _region_id() -> str:
    return os.getenv("ALIYUN_REGION_ID", "cn-hangzhou")


def _sign_name() -> str:
    return os.getenv("SMS_SIGN_NAME", "")


def _template_code() -> str:
    return os.getenv("SMS_TEMPLATE_CODE", "100001")


def is_configured() -> bool:
    return all([_access_key_id(), _access_key_secret(), _sign_name(), _template_code()])


# ---------------------------------------------------------------------------
# 方式一: Dysmsapi (SendSms) — 传统短信 API
# ---------------------------------------------------------------------------

def _try_dysmsapi_send(phone: str, code: str) -> dict | None:
    """尝试通过 Dysmsapi.SendSms 发送验证码。返回 None 表示不可用。"""
    try:
        from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
        from alibabacloud_dysmsapi20170525 import models as dysmsapi_models
        from alibabacloud_tea_openapi import models as open_api_models

        config = open_api_models.Config(
            access_key_id=_access_key_id(),
            access_key_secret=_access_key_secret(),
            endpoint="dysmsapi.aliyuncs.com",
        )
        client = DysmsapiClient(config)
        request = dysmsapi_models.SendSmsRequest(
            phone_numbers=phone,
            sign_name=_sign_name(),
            template_code=_template_code(),
            template_param=f'{{"code":"{code}","min":"5"}}',
        )
        response = client.send_sms(request)
        if response.body.code == "OK":
            return {"success": True, "message": "验证码已发送，5分钟内有效"}
        else:
            logger.warning("Dysmsapi.SendSms 失败: %s - %s", response.body.code, response.body.message)
            return None
    except Exception as exc:
        logger.warning("Dysmsapi.SendSms 不可用: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 方式二: Dypnsapi (SendSmsVerifyCode) — 号码认证 API
# ---------------------------------------------------------------------------

def _try_dypnsapi_send(phone: str) -> dict | None:
    """尝试通过 Dypnsapi.SendSmsVerifyCode 发送验证码。"""
    try:
        import hashlib
        import hmac
        import json as _json
        import urllib.request
        import urllib.error
        import urllib.parse
        import base64
        from datetime import datetime, timezone

        # 阿里云自动生成 6 位数字验证码，填充模板 ${code} 变量
        params = {
            "AccessKeyId": _access_key_id(),
            "Action": "SendSmsVerifyCode",
            "CodeLength": 6,
            "CodeType": 1,
            "Format": "JSON",
            "OutId": "zhiyan",
            "PhoneNumber": phone,
            "SignName": _sign_name(),
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": _secrets.token_hex(16),
            "SignatureVersion": "1.0",
            "TemplateCode": _template_code(),
            # Dypnsapi must generate the code so CheckSmsVerifyCode can validate it.
            "TemplateParam": _json.dumps({"code": "##code##", "min": "5"}),
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Version": "2017-05-25",
        }

        # 阿里云 V1 签名
        sorted_keys = sorted(params.keys())
        canonical = "&".join(
            f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(params[k]), safe='')}"
            for k in sorted_keys
        )
        string_to_sign = f"GET&{urllib.parse.quote('/', safe='')}&{urllib.parse.quote(canonical, safe='')}"
        signature = hmac.new(
            f"{_access_key_secret()}&".encode(), string_to_sign.encode(), hashlib.sha1
        ).digest()
        params["Signature"] = base64.b64encode(signature).decode()

        url = f"https://dypnsapi.aliyuncs.com/?{urllib.parse.urlencode(params)}"
        logger.info("Dypnsapi URL: ...Signature=%s...", params["Signature"][:20])
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = _json.loads(resp.read())
        except urllib.error.HTTPError as http_err:
            err_body = http_err.read().decode() if http_err.fp else ""
            logger.error("Dypnsapi HTTP %s: %s", http_err.code, err_body[:500])
            return None

        logger.info("Dypnsapi 响应: %s", _json.dumps(result, ensure_ascii=False))
        if result.get("Code") == "OK":
            return {"success": True, "message": "验证码已发送，5分钟内有效"}
        else:
            logger.warning("Dypnsapi.SendSmsVerifyCode 失败: %s - %s",
                           result.get("Code"), result.get("Message"))
            return None
    except Exception as exc:
        logger.warning("Dypnsapi.SendSmsVerifyCode 不可用: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 发送验证码（自动选择可用 API）
# ---------------------------------------------------------------------------

def send_sms_code(phone: str) -> dict:
    """发送验证码，依次尝试 Dysmsapi → Dypnsapi → 演示模式。"""
    if not is_configured():
        return _demo_fallback(phone, "SMS 未完整配置")

    # 生成 6 位验证码
    code = "%06d" % (_secrets.randbelow(900000) + 100000)
    redis_cache_set(f"sms:code:{phone}", code, ttl=300)

    # 方式一: Dypnsapi.SendSmsVerifyCode（号码认证 — 模板 100001 专属）
    result = _try_dypnsapi_send(phone)
    if result and result["success"]:
        return result

    # 方式二: Dysmsapi.SendSms（传统短信 — 备用）
    result = _try_dysmsapi_send(phone, code)
    if result and result["success"]:
        return result

    # 全部失败 → 降级演示模式
    return _demo_fallback(phone, "阿里云短信 API 暂不可用")


# ---------------------------------------------------------------------------
# 校验验证码
# ---------------------------------------------------------------------------

def verify_sms_code(phone: str, code: str) -> bool:
    """校验验证码。优先通过阿里云 CheckSmsVerifyCode，否则本地 Redis 比对。"""
    if not code or len(code) < 4:
        return False

    # 尝试 Dypnsapi.CheckSmsVerifyCode
    if is_configured():
        try:
            import hashlib
            import hmac
            import urllib.request
            import urllib.error
            import urllib.parse
            import base64
            from datetime import datetime, timezone

            params = {
                "AccessKeyId": _access_key_id(),
                "Action": "CheckSmsVerifyCode",
                "Format": "JSON",
                "OutId": "zhiyan",
                "PhoneNumber": phone,
                "VerifyCode": code,
                "SignatureMethod": "HMAC-SHA1",
                "SignatureNonce": _secrets.token_hex(16),
                "SignatureVersion": "1.0",
                "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "Version": "2017-05-25",
            }
            sorted_keys = sorted(params.keys())
            canonical = "&".join(
                f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(params[k]), safe='')}"
                for k in sorted_keys
            )
            string_to_sign = f"GET&{urllib.parse.quote('/', safe='')}&{urllib.parse.quote(canonical, safe='')}"
            signature = hmac.new(
                f"{_access_key_secret()}&".encode(), string_to_sign.encode(), hashlib.sha1
            ).digest()
            params["Signature"] = base64.b64encode(signature).decode()

            url = f"https://dypnsapi.aliyuncs.com/?{urllib.parse.urlencode(params)}"
            import json as _verify_json
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    result = _verify_json.loads(resp.read())
            except urllib.error.HTTPError as http_err:
                error_body = http_err.read().decode(errors="replace") if http_err.fp else ""
                logger.error("CheckSmsVerifyCode HTTP %s: %s", http_err.code, error_body[:500])
                return False

            logger.info("CheckSmsVerifyCode 响应: %s", _verify_json.dumps(result, ensure_ascii=False))
            if result.get("Code") == "OK":
                return _verification_passed(result)
            logger.warning("CheckSmsVerifyCode 失败: %s - %s", result.get("Code"), result.get("Message"))
            return False
        except Exception as exc:
            logger.warning("CheckSmsVerifyCode 不可用: %s", exc)

    # 降级: Redis 本地比对
    return _demo_verify(phone, code)


# ---------------------------------------------------------------------------
# 演示模式
# ---------------------------------------------------------------------------

def _demo_fallback(phone: str, reason: str) -> dict:
    demo_code = "246810"
    redis_cache_set(f"sms:code:{phone}", demo_code, ttl=300)
    return {"success": False, "message": f"{reason}，已降级为演示模式", "demo_code": demo_code}


def _demo_verify(phone: str, code: str) -> bool:
    stored = redis_cache_get(f"sms:code:{phone}")
    if stored is not None:
        if stored == code:
            redis_cache_delete(f"sms:code:{phone}")
            return True
        return False
    return code == "246810"
