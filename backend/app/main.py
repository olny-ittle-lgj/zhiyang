from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import bcrypt
import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .auth import CurrentUser, create_token, decode_refresh_token, hash_password, issue_tokens, verify_password
from .config import settings
from .currency import (
    CURRENCY_LABELS,
    PERSONAL_DAILY_QUOTAS,
    STORE_ITEMS,
    claim_daily_checkin,
    consume_personal_quota,
    credit_personal,
    debit_personal,
    ensure_personal_wallet,
    list_transactions,
    purchase_store_item,
    wallet_snapshot,
)
from .customer_service import customer_service_knowledge
from .customer_service_agent import CustomerServiceAgentError, answer_customer_service_agent, stream_customer_service_agent
from .database import connection, execute, init_database, log_event, row, rows, utcnow
from .embeddings import StandardRuntimeError
from .material_qa_agent import MaterialQaAgentError, answer_material_question
from .standard_evolution import EvolutionAgentError, run_evolution_agents
from .standard_game_agent import GAME_TITLES, agent_extract_knowledge, build_game_questions, index_matching_points, matching_round
from .mcp_client import FetchMcpError, FetchMcpNotConfigured, fetch_url_content
from .ocr import OcrError, extract_image_text, inspect_image
from .video import VideoAnalysisError, analyze_video_text
from .schemas import ChatRequest, CustomerServiceAskRequest, EvolutionRequest, GameGenerateRequest, GameSubmitRequest, GraphRebuildRequest, GraphReviewRequest, LoginRequest, MatchingRoundRequest, MaterialAskRequest, MemoryGameCompleteRequest, RefreshTokenRequest, RegisterRequest, ReviewRequest, SettingsRequest, ShareRequest, StorePurchaseRequest, TextMaterialRequest, UrlMaterialRequest, UrlPreviewRequest
from .services import all_services_health, es_delete_document, es_search, es_index_document, get_elasticsearch, get_milvus, get_redis, hybrid_search, milvus_insert, milvus_search, mysql_initialize_schema, rabbitmq_publish, redis_cache_delete, redis_cache_delete_pattern, redis_cache_get, redis_cache_get_json, redis_cache_set, redis_cache_set_json
from .sms import is_configured as sms_configured, send_sms_code, verify_sms_code
from .team import public_router as team_public_router, router as team_router


app = FastAPI(title=settings.app_name, version="3.7.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(team_router)
app.include_router(team_public_router)


@app.exception_handler(StandardRuntimeError)
async def standard_runtime_error_handler(_, exc: StandardRuntimeError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".doc", ".docx", ".mp4", ".avi", ".mov", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".bmp", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}

# XP thresholds for level calculation
XP_PER_LEVEL = 500
_auto_evolution_task: asyncio.Task | None = None
_auto_evolution_runs: set[str] = set()


def calculate_level(xp: int) -> int:
    """Calculate level from total XP."""
    return max(1, xp // XP_PER_LEVEL + 1)


def calculate_xp_for_next_level(level: int) -> int:
    """XP needed to reach next level."""
    return level * XP_PER_LEVEL


async def _auto_evolution_scheduler() -> None:
    """Run opted-in automatic evolution once at each user's configured time."""
    global _auto_evolution_runs
    while True:
        now = datetime.now()
        today = now.date().isoformat()
        _auto_evolution_runs = {key for key in _auto_evolution_runs if key.startswith(today + ":")}
        trigger = now.strftime("%H:%M")
        due_users = rows(
            "SELECT s.user_id,s.trigger_time FROM user_settings s "
            "WHERE s.auto_evolution=1 AND s.evolution_mode='auto' AND s.trigger_time=?",
            (trigger,),
        )
        for item in due_users:
            run_key = f"{today}:{item['user_id']}:{trigger}"
            if run_key in _auto_evolution_runs:
                continue
            _auto_evolution_runs.add(run_key)
            material_rows = rows(
                "SELECT id FROM materials WHERE user_id=? AND status='ready' AND TRIM(content)<>'' "
                "ORDER BY id DESC LIMIT 10",
                (item["user_id"],),
            )
            if not material_rows:
                log_event(item["user_id"], "evolution", "schedule_skip", "定时自动进化没有可用素材")
                continue
            try:
                token = create_token(int(item["user_id"]))
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://scheduler") as client:
                    response = await client.post(
                        "/api/evolution/start",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"mode": "auto", "material_ids": [int(row_item["id"]) for row_item in material_rows]},
                    )
                if response.status_code >= 400:
                    log_event(item["user_id"], "evolution", "schedule_failed", response.text[:300])
                else:
                    log_event(item["user_id"], "evolution", "schedule_start", f"定时自动进化 {trigger}")
            except Exception as exc:
                log_event(item["user_id"], "evolution", "schedule_failed", str(exc)[:300])
        await asyncio.sleep(30)


@app.on_event("startup")
async def startup() -> None:
    global _auto_evolution_task
    init_database()
    # Keep the optional MySQL material mirror ready for write-through indexing.
    mysql_initialize_schema()
    _auto_evolution_task = asyncio.create_task(_auto_evolution_scheduler())


@app.on_event("shutdown")
async def shutdown() -> None:
    global _auto_evolution_task
    if _auto_evolution_task:
        _auto_evolution_task.cancel()
        try:
            await _auto_evolution_task
        except asyncio.CancelledError:
            pass
        _auto_evolution_task = None


def serialize_settings(data: dict) -> dict:
    data["auto_evolution"] = bool(data["auto_evolution"])
    data["gamified_review"] = bool(data["gamified_review"])
    # Normalize legacy rows so a disabled switch can never advertise auto mode.
    if not data["auto_evolution"]:
        data["evolution_mode"] = "manual"
    return data


def _service_status() -> dict:
    """Build dynamic service health status based on actual configuration."""
    db_ok = True
    try:
        row("SELECT 1")
    except Exception:
        db_ok = False

    return {
        "api": "online",
        "database": "active" if db_ok else "error",
        "deepseek": "configured" if settings.deepseek_api_key else "not_configured",
        "milvus": "not_configured",
        "redis": "not_configured",
        "elasticsearch": "not_configured",
        "sms": "configured" if os.getenv("SMS_API_KEY") or os.getenv("ALIYUN_ACCESS_KEY_ID") else "not_configured",
    }


def _invalidate_user_cache(user_id: int) -> None:
    """Invalidate all user-scoped Redis projections after a write."""
    redis_cache_delete(f"dashboard:{user_id}")
    redis_cache_delete_pattern(f"materials:{user_id}:*")


@app.get("/api/health")
def health() -> dict:
    dynamic = all_services_health()
    service_values = [dynamic.get(name) for name in ("redis", "elasticsearch", "mysql")]
    return {
        "status": "ok" if "error" not in service_values else "degraded",
        "version": "3.7.0",
        "services": {
            "api": "online",
            # SQLite is the transactional application database configured by
            # DATABASE_PATH. MySQL is reported separately as an optional
            # external service so health never claims the wrong primary DB.
            "database": _service_status()["database"],
            "mysql": dynamic.get("mysql", "not_configured"),
            "deepseek": "configured" if settings.deepseek_api_key else "not_configured",
            "deepseek_model": settings.deepseek_model,
            "bge_m3": dynamic.get("bge_m3", "not_configured"),
            "milvus": dynamic.get("milvus", "not_configured"),
            "redis": dynamic.get("redis", "not_configured"),
            "elasticsearch": dynamic.get("elasticsearch", "not_configured"),
            "rabbitmq": dynamic.get("rabbitmq", "not_configured"),
            "sms": "configured" if sms_configured() else "not_configured",
            "fetch_mcp": "configured" if settings.fetch_mcp_url else "not_configured",
        },
    }


@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterRequest) -> dict:
    if row("SELECT id FROM users WHERE username=?", (payload.username.lower(),)):
        raise HTTPException(409, "该账号已注册")
    user_id = execute("INSERT INTO users(username,password_hash,nickname,created_at) VALUES(?,?,?,?)", (payload.username.lower(), hash_password(payload.password), payload.nickname, utcnow()))
    execute("INSERT INTO user_settings(user_id) VALUES(?)", (user_id,))
    ensure_personal_wallet(user_id)
    log_event(user_id, "auth", "register", "账号注册成功")
    return issue_tokens(user_id)


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict:
    user = row("SELECT * FROM users WHERE username=?", (payload.username.lower(),))
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "账号或密码错误")
    log_event(user["id"], "auth", "login", "账号密码登录")
    # Calculate level/xp from game sessions
    total_xp = row("SELECT COALESCE(SUM(CASE WHEN correct THEN 100 ELSE 10 END), 0) xp FROM game_sessions WHERE user_id=?", (user["id"],))["xp"]
    level = calculate_level(total_xp)
    return {
        **issue_tokens(user["id"]),
        "user": {"id": user["id"], "nickname": user["nickname"], "username": user["username"],
                  "avatar": user.get("avatar", ""), "level": level, "xp": total_xp}
    }


@app.post("/api/auth/refresh")
def refresh_access_token(payload: RefreshTokenRequest) -> dict:
    """Rotate a valid 7-day refresh token into a fresh access/refresh pair."""
    token_payload = decode_refresh_token(payload.refresh_token)
    user = row("SELECT id FROM users WHERE id=?", (token_payload["user_id"],))
    if not user:
        raise HTTPException(401, "用户不存在，请重新登录")
    log_event(user["id"], "auth", "refresh", "无感刷新访问令牌")
    return issue_tokens(user["id"], team_id=token_payload.get("team_id"))


@app.post("/api/auth/phone/code")
def send_phone_code(payload: dict) -> dict:
    """发送手机验证码。Body: {"phone": "13800138000"}"""
    phone = payload.get("phone", "")
    if not re.fullmatch(r"1\d{10}", phone):
        raise HTTPException(422, "手机号格式不正确")

    result = send_sms_code(phone)
    return {
        "sent": result["success"],
        "expires_in": 300,
        "demo_code": result.get("demo_code"),
        "mode": "production" if sms_configured() else "demo",
        "message": result["message"],
    }


@app.post("/api/auth/phone/login")
def phone_login(payload: dict) -> dict:
    """手机验证码登录。Body: {"phone": "13800138000", "code": "246810"}"""
    phone = payload.get("phone", "")
    code = payload.get("code", "")
    if not re.fullmatch(r"1\d{10}", phone):
        raise HTTPException(422, "手机号格式不正确")

    if not verify_sms_code(phone, code):
        raise HTTPException(401, "验证码错误或已过期，请重新获取")

    # Find or create user
    user = row("SELECT * FROM users WHERE phone=?", (phone,))
    if not user:
        nickname = f"手机用户{phone[-4:]}"
        user_id = execute(
            "INSERT INTO users(username,password_hash,nickname,phone,created_at) VALUES(?,?,?,?,?)",
            (f"phone_{phone}", hash_password(secrets.token_hex(16)), nickname, phone, utcnow()))
        execute("INSERT INTO user_settings(user_id) VALUES(?)", (user_id,))
        ensure_personal_wallet(user_id)
        user = row("SELECT * FROM users WHERE id=?", (user_id,))
        log_event(user["id"], "auth", "register", f"手机号注册 {phone}")
    else:
        log_event(user["id"], "auth", "login", f"手机验证码登录 {phone}")
    total_xp = row("SELECT COALESCE(SUM(CASE WHEN correct THEN 100 ELSE 10 END), 0) xp FROM game_sessions WHERE user_id=?", (user["id"],))["xp"]
    level = calculate_level(total_xp)
    return {
        **issue_tokens(user["id"]),
        "user": {"id": user["id"], "nickname": user["nickname"], "username": user["username"],
                  "avatar": user.get("avatar", ""), "level": level, "xp": total_xp}
    }


@app.get("/api/auth/me")
def me(user: CurrentUser) -> dict:
    total_xp = row("SELECT COALESCE(SUM(CASE WHEN correct THEN 100 ELSE 10 END), 0) xp FROM game_sessions WHERE user_id=?", (user["id"],))["xp"]
    level = calculate_level(total_xp)
    return {**user, "level": level, "xp": total_xp}


@app.get("/api/currency/wallet")
def personal_currency_wallet(user: CurrentUser) -> dict:
    return wallet_snapshot("personal", int(user["id"]))


@app.get("/api/currency/transactions")
def personal_currency_transactions(
    user: CurrentUser,
    limit: int = Query(80, ge=1, le=200),
    currency: str | None = Query(None),
) -> dict:
    return {
        "scope": "personal",
        "items": list_transactions("personal", int(user["id"]), limit=limit, currency=currency),
    }


@app.get("/api/currency/store")
def currency_store(user: CurrentUser) -> dict:
    wallet = wallet_snapshot("personal", int(user["id"]))
    inventory = {item["item_id"]: int(item["quantity"]) for item in wallet.get("inventory", [])}
    return {
        "items": [{**item, "owned": inventory.get(item["item_id"], 0)} for item in STORE_ITEMS],
        "wallet": wallet,
        "currency_labels": CURRENCY_LABELS,
    }


@app.post("/api/currency/check-in")
def currency_check_in(user: CurrentUser) -> dict:
    result = claim_daily_checkin(int(user["id"]))
    result["wallet"] = wallet_snapshot("personal", int(user["id"]))
    return result


@app.post("/api/currency/store/purchase")
def currency_store_purchase(payload: StorePurchaseRequest, user: CurrentUser) -> dict:
    result = purchase_store_item(
        int(user["id"]),
        payload.item_id,
        payload.quantity,
        idempotency_key=payload.idempotency_key,
    )
    result["wallet"] = wallet_snapshot("personal", int(user["id"]))
    return result


@app.get("/api/dashboard")
def dashboard(user: CurrentUser) -> dict:
    cache_key = f"dashboard:{user['id']}"
    cached = redis_cache_get_json(cache_key)
    if isinstance(cached, dict) and "knowledge_balance" in cached:
        return cached

    # Real counts from database
    material_count = row("SELECT COUNT(*) count FROM materials WHERE user_id=?", (user["id"],))["count"]
    today_count = row("SELECT COUNT(*) count FROM materials WHERE user_id=? AND date(created_at)=date('now')", (user["id"],))["count"]

    # Game stats
    total_xp = row("SELECT COALESCE(SUM(CASE WHEN correct THEN 100 ELSE 10 END), 0) xp FROM game_sessions WHERE user_id=?", (user["id"],))["xp"]
    level = calculate_level(total_xp)
    game_sessions = row("SELECT COUNT(*) count, COALESCE(SUM(CASE WHEN correct THEN 1 ELSE 0 END),0) correct FROM game_sessions WHERE user_id=?", (user["id"],))
    total_sessions = game_sessions["count"]
    total_correct = game_sessions["correct"]
    mastery = round(total_correct / max(total_sessions, 1) * 100, 1)
    wallet = wallet_snapshot("personal", int(user["id"]))
    coins = wallet["knowledge_balance"]
    props = row("SELECT COUNT(*) count FROM game_sessions WHERE user_id=? AND correct=1", (user["id"],))["count"] % 20 + 3

    # Category distribution from actual materials
    categories = rows(
        "SELECT category, COUNT(*) count FROM materials WHERE user_id=? AND status='ready' GROUP BY category ORDER BY count DESC LIMIT 5",
        (user["id"],))
    if not categories:
        categories = [{"category": "未分类", "count": material_count}]
    total_cat = sum(c["count"] for c in categories) or 1
    cat_dist = [{"name": c["category"], "value": round(c["count"] / total_cat * 100)} for c in categories]

    # Learning trend (last 7 days of game activity)
    trend = []
    accuracy = []
    for day_offset in range(6, -1, -1):
        date_str = (datetime.now(timezone.utc) - timedelta(days=day_offset)).strftime("%Y-%m-%d")
        day_count = row(
            "SELECT COUNT(*) count FROM game_sessions WHERE user_id=? AND date(created_at)=?",
            (user["id"], date_str))["count"]
        day_correct = row(
            "SELECT COUNT(*) count FROM game_sessions WHERE user_id=? AND date(created_at)=? AND correct=1",
            (user["id"], date_str))["count"]
        trend.append(day_count)
        accuracy.append(round(day_correct / max(day_count, 1) * 100))

    # Latest evolution task
    task = row("SELECT * FROM evolution_tasks WHERE user_id=? ORDER BY id DESC LIMIT 1", (user["id"],))

    # Recent materials
    recent = rows("SELECT id,name,kind,status,created_at FROM materials WHERE user_id=? ORDER BY id DESC LIMIT 4", (user["id"],))

    result = {
        "knowledge_total": material_count,
        "today_added": today_count,
        "mastery": mastery,
        "level": level,
        "xp": total_xp,
        "next_level_xp": calculate_xp_for_next_level(level),
        "coins": coins,
        "knowledge_balance": wallet["knowledge_balance"],
        "truth_balance": wallet["truth_balance"],
        "truth_crystals": wallet["truth_balance"],
        "props": props,
        "category_distribution": cat_dist,
        "trend": trend if any(t > 0 for t in trend) else None,
        "accuracy": accuracy,
        "latest_task": task,
        "recent": recent,
    }

    # Cache for 60 seconds in Redis
    redis_cache_set_json(cache_key, result, ttl=60)
    return result


def _user_metrics(user_id: int) -> dict:
    material_stats = row(
        "SELECT COUNT(*) material_count,"
        "SUM(CASE WHEN status='ready' THEN 1 ELSE 0 END) ready_count,"
        "COUNT(DISTINCT COALESCE(NULLIF(TRIM(category),''),'未分类')) category_count,"
        "COALESCE(SUM(LENGTH(COALESCE(content,''))),0) content_chars,"
        "SUM(CASE WHEN source='upload' THEN 1 ELSE 0 END) upload_material_count,"
        "SUM(CASE WHEN source='manual' THEN 1 ELSE 0 END) manual_text_count,"
        "SUM(CASE WHEN source='url' THEN 1 ELSE 0 END) url_material_count,"
        "SUM(CASE WHEN source='image' THEN 1 ELSE 0 END) image_material_count,"
        "SUM(CASE WHEN source='video' THEN 1 ELSE 0 END) video_material_count "
        "FROM materials WHERE user_id=?",
        (user_id,),
    ) or {}
    material_ai_questions = row(
        "SELECT COUNT(*) count FROM system_logs "
        "WHERE user_id=? AND module='ai' AND action='material_ask'",
        (user_id,),
    )["count"]
    ai_chat_count = row(
        "SELECT COUNT(*) count FROM system_logs "
        "WHERE user_id=? AND module='ai' AND action='chat'",
        (user_id,),
    )["count"]
    customer_service_count = row(
        "SELECT COUNT(*) count FROM system_logs "
        "WHERE user_id=? AND module='customer_service' AND action='ask'",
        (user_id,),
    )["count"]
    favorite_count = row("SELECT COUNT(*) count FROM user_favorites WHERE user_id=?", (user_id,))["count"]
    evolution_stats = row(
        "SELECT COUNT(*) evolution_count,"
        "SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed_evolution_count "
        "FROM evolution_tasks WHERE user_id=?",
        (user_id,),
    ) or {}
    review_stats = row(
        "SELECT COUNT(*) evolution_review_count,"
        "SUM(CASE WHEN r.decision='accepted' THEN 1 ELSE 0 END) accepted_review_count,"
        "SUM(CASE WHEN r.decision='rejected' THEN 1 ELSE 0 END) rejected_review_count,"
        "SUM(CASE WHEN r.decision='rolled_back' THEN 1 ELSE 0 END) rollback_count "
        "FROM evolution_reviews r JOIN evolution_tasks t ON t.id=r.task_id WHERE t.user_id=?",
        (user_id,),
    ) or {}
    version_count = row(
        "SELECT COUNT(*) count FROM evolution_versions WHERE user_id=?",
        (user_id,),
    )["count"]
    sessions = row(
        "SELECT COUNT(*) game_sessions,"
        "COALESCE(SUM(correct),0) correct_count,"
        "COALESCE(SUM(score),0) coins,"
        "COALESCE(MAX(score),0) best_score,"
        "COUNT(DISTINCT game) game_count,"
        "SUM(CASE WHEN game='flashcard' THEN 1 ELSE 0 END) flashcard_sessions,"
        "SUM(CASE WHEN game='monopoly' THEN 1 ELSE 0 END) monopoly_sessions,"
        "SUM(CASE WHEN game='matching' THEN 1 ELSE 0 END) matching_sessions "
        "FROM game_sessions WHERE user_id=?",
        (user_id,),
    ) or {}
    pack_stats = row(
        "SELECT COUNT(*) pack_count,"
        "SUM(CASE WHEN source_mode='deepseek-agent' THEN 1 ELSE 0 END) ai_pack_count "
        "FROM game_packs WHERE user_id=?",
        (user_id,),
    ) or {}
    generated_question_count = row(
        "SELECT COUNT(*) count FROM game_questions WHERE user_id=?",
        (user_id,),
    )["count"]
    graph_stats = row(
        "SELECT COUNT(*) graph_nodes FROM graph_nodes WHERE user_id=?",
        (user_id,),
    ) or {}
    graph_edges = row(
        "SELECT COUNT(*) count FROM graph_edges WHERE user_id=?",
        (user_id,),
    )["count"]
    graph_review_stats = row(
        "SELECT COUNT(*) graph_review_count,"
        "SUM(CASE WHEN result='known' THEN 1 ELSE 0 END) graph_known_count,"
        "SUM(CASE WHEN result='weak' THEN 1 ELSE 0 END) graph_weak_count "
        "FROM graph_reviews WHERE user_id=?",
        (user_id,),
    ) or {}
    share_stats = row(
        "SELECT COUNT(*) share_count,"
        "SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) active_share_count,"
        "COALESCE(SUM(visits),0) share_visits "
        "FROM shares WHERE user_id=?",
        (user_id,),
    ) or {}
    settings_update_count = row(
        "SELECT COUNT(*) count FROM system_logs "
        "WHERE user_id=? AND module='settings' AND action='update'",
        (user_id,),
    )["count"]
    operation_log_count = row(
        "SELECT COUNT(*) count FROM system_logs WHERE user_id=?",
        (user_id,),
    )["count"]
    wallet = wallet_snapshot("personal", int(user_id))
    return {
        "material_count": int(material_stats.get("material_count") or 0),
        "ready_count": int(material_stats.get("ready_count") or 0),
        "category_count": int(material_stats.get("category_count") or 0),
        "content_chars": int(material_stats.get("content_chars") or 0),
        "upload_material_count": int(material_stats.get("upload_material_count") or 0),
        "manual_text_count": int(material_stats.get("manual_text_count") or 0),
        "url_material_count": int(material_stats.get("url_material_count") or 0),
        "image_material_count": int(material_stats.get("image_material_count") or 0),
        "video_material_count": int(material_stats.get("video_material_count") or 0),
        "material_ai_questions": int(material_ai_questions or 0),
        "ai_chat_count": int(ai_chat_count or 0),
        "customer_service_count": int(customer_service_count or 0),
        "favorite_count": favorite_count,
        "evolution_count": int(evolution_stats.get("evolution_count") or 0),
        "completed_evolution_count": int(evolution_stats.get("completed_evolution_count") or 0),
        "evolution_review_count": int(review_stats.get("evolution_review_count") or 0),
        "accepted_review_count": int(review_stats.get("accepted_review_count") or 0),
        "rejected_review_count": int(review_stats.get("rejected_review_count") or 0),
        "version_count": int(version_count or 0),
        "rollback_count": int(review_stats.get("rollback_count") or 0),
        "game_sessions": int(sessions.get("game_sessions") or 0),
        "correct_count": int(sessions.get("correct_count") or 0),
        "coins": int(wallet["knowledge_balance"]),
        "knowledge_balance": int(wallet["knowledge_balance"]),
        "truth_balance": int(wallet["truth_balance"]),
        "truth_crystals": int(wallet["truth_balance"]),
        "best_score": int(sessions.get("best_score") or 0),
        "game_count": int(sessions.get("game_count") or 0),
        "flashcard_sessions": int(sessions.get("flashcard_sessions") or 0),
        "monopoly_sessions": int(sessions.get("monopoly_sessions") or 0),
        "matching_sessions": int(sessions.get("matching_sessions") or 0),
        "pack_count": int(pack_stats.get("pack_count") or 0),
        "ai_pack_count": int(pack_stats.get("ai_pack_count") or 0),
        "generated_question_count": int(generated_question_count or 0),
        "graph_nodes": int(graph_stats.get("graph_nodes") or 0),
        "graph_edges": int(graph_edges or 0),
        "graph_review_count": int(graph_review_stats.get("graph_review_count") or 0),
        "graph_known_count": int(graph_review_stats.get("graph_known_count") or 0),
        "graph_weak_count": int(graph_review_stats.get("graph_weak_count") or 0),
        "share_count": int(share_stats.get("share_count") or 0),
        "active_share_count": int(share_stats.get("active_share_count") or 0),
        "share_visits": int(share_stats.get("share_visits") or 0),
        "settings_update_count": int(settings_update_count or 0),
        "operation_log_count": int(operation_log_count or 0),
        # Keep this legacy key for dashboard consumers that still read it.
        "shares": int(share_stats.get("share_count") or 0),
    }


def _achievement_items(metrics: dict) -> list[dict]:
    definitions = [
        ("first_material", "初识知衍", "导入或创建 1 条知识素材", "material_count", 1),
        ("material_collector", "知识采集者", "累计拥有 5 条知识素材", "material_count", 5),
        ("archive_library", "知识档案馆", "累计拥有 10 条知识素材", "material_count", 10),
        ("material_marathon", "素材马拉松", "累计拥有 25 条知识素材", "material_count", 25),
        ("ready_library", "入库完备", "拥有 5 条已就绪素材", "ready_count", 5),
        ("ready_archive", "就绪宝库", "拥有 10 条已就绪素材", "ready_count", 10),
        ("category_planner", "分类规划师", "建立 3 个知识分类", "category_count", 3),
        ("upload_pioneer", "上传先锋", "完成 1 次文件上传", "upload_material_count", 1),
        ("text_recorder", "文本记录员", "创建 1 条手动文本素材", "manual_text_count", 1),
        ("web_collector", "网页采集者", "采集 1 条网页素材", "url_material_count", 1),
        ("image_reader", "图像识别者", "完成 1 条图片素材识别", "image_material_count", 1),
        ("video_listener", "视频听记员", "完成 1 条视频素材提取", "video_material_count", 1),
        ("content_weaver", "内容编织者", "累计沉淀 5000 字知识正文", "content_chars", 5000),
        ("material_questioner", "素材提问者", "完成 1 次素材 AI 问答", "material_ai_questions", 1),
        ("deep_questioner", "深度提问者", "完成 10 次素材 AI 问答", "material_ai_questions", 10),
        ("archive_curator", "素材策展人", "收藏 3 条常用素材", "favorite_count", 3),
        ("favorite_library", "收藏图书馆", "收藏 10 条常用素材", "favorite_count", 10),
        ("evolution_start", "进化启动", "启动 1 次知识进化", "evolution_count", 1),
        ("evolution_operator", "进化执行者", "启动 3 次知识进化", "evolution_count", 3),
        ("evolution_master", "进化先驱", "完成 3 次知识进化", "completed_evolution_count", 3),
        ("evolution_architect", "进化架构师", "完成 10 次知识进化", "completed_evolution_count", 10),
        ("review_guardian", "审核守门人", "接受 1 条知识进化建议", "accepted_review_count", 1),
        ("quality_editor", "质量编辑", "接受 5 条知识进化建议", "accepted_review_count", 5),
        ("version_guardian", "版本守护者", "累计产生 5 个知识版本", "version_count", 5),
        ("rollback_expert", "回滚专家", "完成 1 次知识版本回滚", "rollback_count", 1),
        ("game_beginner", "复习启航", "完成 1 次学习挑战", "game_sessions", 1),
        ("game_runner", "连续训练", "完成 10 次学习挑战", "game_sessions", 10),
        ("game_marathon", "游戏马拉松", "完成 30 次学习挑战", "game_sessions", 30),
        ("accurate_mind", "精准记忆", "累计答对 20 次", "correct_count", 20),
        ("hundred_answers", "百题达人", "累计答对 50 次", "correct_count", 50),
        ("question_craftsman", "题目工匠", "累计生成 30 道游戏题目", "generated_question_count", 30),
        ("question_foundry", "题库熔炉", "累计生成 100 道游戏题目", "generated_question_count", 100),
        ("first_pack", "首个题包", "生成 1 个知识游戏题包", "pack_count", 1),
        ("ai_game_builder", "AI 出题官", "使用 Agent 生成 3 个游戏题包", "ai_pack_count", 3),
        ("mode_explorer", "全模式探索", "体验 3 种知识游戏模式", "game_count", 3),
        ("flashcard_player", "记忆挑战者", "完成 5 次智能闪卡", "flashcard_sessions", 5),
        ("monopoly_tycoon", "知识地产家", "完成 5 次知识大富翁", "monopoly_sessions", 5),
        ("matching_strategist", "智识对弈者", "完成 5 次智识对弈", "matching_sessions", 5),
        ("score_hunter", "高分猎手", "单局游戏得分达到 1000 分", "best_score", 1000),
        ("coin_spark", "智衍币新星", "累计获得 1000 枚智衍币", "coins", 1000),
        ("graph_builder", "图谱构建者", "生成 8 个知识节点", "graph_nodes", 8),
        ("graph_cartographer", "图谱制图师", "生成 30 个知识节点", "graph_nodes", 30),
        ("relation_connector", "关系连接者", "建立 10 条知识关系", "graph_edges", 10),
        ("graph_reviewer", "节点复习者", "完成 1 次知识图谱复习", "graph_review_count", 1),
        ("mastery_guardian", "掌握守护者", "完成 5 次已掌握反馈", "graph_known_count", 5),
        ("weak_spot_scout", "薄弱侦察员", "完成 5 次薄弱反馈", "graph_weak_count", 5),
        ("knowledge_sharer", "知识分享者", "创建 1 个知识分享", "share_count", 1),
        ("share_publisher", "分享出版人", "创建 3 个知识分享", "share_count", 3),
        ("workshop_admin", "工作坊管理员", "修改个人设置 3 次", "settings_update_count", 3),
        ("customer_service_student", "客服学习者", "完成 5 次客服 Agent 问答", "customer_service_count", 5),
    ]
    return [
        {
            "id": item_id,
            "title": title,
            "description": description,
            "unlocked": int(metrics.get(metric, 0) or 0) >= int(target),
            "progress": min(int(metrics.get(metric, 0) or 0), int(target)),
            "target": int(target),
            "percent": min(100, round(int(metrics.get(metric, 0) or 0) / max(1, int(target)) * 100)),
        }
        for item_id, title, description, metric, target in definitions
    ]


def _search_excerpt(text: str | None, term: str, limit: int = 118) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return ""
    index = compact.lower().find(term.lower())
    if index < 0:
        return compact[:limit] + ("..." if len(compact) > limit else "")
    start = max(0, index - 34)
    end = min(len(compact), index + len(term) + 84)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"


def _search_like(value: str) -> str:
    return f"%{value.strip()}%"


@app.get("/api/search")
def global_search(user: CurrentUser, q: str = Query(min_length=1, max_length=80), limit: int = Query(5, ge=1, le=10)) -> dict:
    query = q.strip()
    if not query:
        return {"query": "", "total": 0, "groups": []}

    cache_key = f"search:{user['id']}:{query.lower()}:{limit}"
    cached = redis_cache_get_json(cache_key)
    if isinstance(cached, dict):
        return cached

    pattern = _search_like(query)
    material_rows = rows(
        "SELECT m.id,m.name,m.kind,m.category,m.status,m.content,m.created_at,"
        "CASE WHEN f.material_id IS NULL THEN 0 ELSE 1 END favorite "
        "FROM materials m LEFT JOIN user_favorites f ON f.material_id=m.id AND f.user_id=? "
        "WHERE m.user_id=? AND (m.name LIKE ? OR m.category LIKE ? OR m.content LIKE ?) "
        "ORDER BY CASE WHEN m.name LIKE ? THEN 0 ELSE 1 END,m.id DESC LIMIT ?",
        (user["id"], user["id"], pattern, pattern, pattern, pattern, limit),
    )
    materials = [
        {
            "id": f"material:{item['id']}",
            "type": "material",
            "type_label": "素材",
            "title": item["name"],
            "subtitle": f"{item['kind']} / {item['category']} / {item['status']}",
            "excerpt": _search_excerpt(item.get("content"), query),
            "route": f"/materials?material={item['id']}",
            "meta": "已收藏" if item.get("favorite") else "素材库",
        }
        for item in material_rows
    ]

    graph_rows = rows(
        "SELECT id,label,category,summary,mastery,source_material_id FROM graph_nodes "
        "WHERE user_id=? AND (label LIKE ? OR category LIKE ? OR summary LIKE ?) "
        "ORDER BY CASE WHEN label LIKE ? THEN 0 ELSE 1 END,mastery DESC LIMIT ?",
        (user["id"], pattern, pattern, pattern, pattern, limit),
    )
    graph_nodes = [
        {
            "id": f"graph:{item['id']}",
            "type": "graph",
            "type_label": "图谱",
            "title": item["label"],
            "subtitle": f"{item['category']} / 掌握度 {item['mastery']}%",
            "excerpt": _search_excerpt(item.get("summary"), query),
            "route": f"/graph?node={item['id']}",
            "meta": "知识节点",
        }
        for item in graph_rows
    ]

    task_rows = rows(
        "SELECT id,mode,status,summary,error,created_at FROM evolution_tasks "
        "WHERE user_id=? AND (mode LIKE ? OR status LIKE ? OR summary LIKE ? OR error LIKE ?) "
        "ORDER BY id DESC LIMIT ?",
        (user["id"], pattern, pattern, pattern, pattern, limit),
    )
    tasks = [
        {
            "id": f"evolution:{item['id']}",
            "type": "evolution",
            "type_label": "进化",
            "title": f"进化任务 #{item['id']}",
            "subtitle": f"{item['mode']} / {item['status']}",
            "excerpt": _search_excerpt(item.get("summary") or item.get("error"), query),
            "route": f"/evolution?task={item['id']}",
            "meta": item["created_at"],
        }
        for item in task_rows
    ]

    groups = [
        {"type": "material", "label": "素材文档", "items": materials},
        {"type": "graph", "label": "知识图谱", "items": graph_nodes},
        {"type": "evolution", "label": "进化记录", "items": tasks},
    ]
    groups = [group for group in groups if group["items"]]
    result = {"query": query, "total": sum(len(group["items"]) for group in groups), "groups": groups}
    redis_cache_set_json(cache_key, result, ttl=20)
    return result


@app.get("/api/topbar")
def topbar_summary(user: CurrentUser) -> dict:
    metrics = _user_metrics(user["id"])
    read_state = row("SELECT last_read_at FROM notification_reads WHERE user_id=?", (user["id"],))
    if read_state:
        personal_unread = row(
            "SELECT COUNT(*) count FROM system_logs WHERE user_id=? AND created_at>?",
            (user["id"], read_state["last_read_at"]),
        )["count"]
    else:
        personal_unread = row("SELECT COUNT(*) count FROM system_logs WHERE user_id=?", (user["id"],))["count"]
    team_unread = row(
        "SELECT COUNT(*) count FROM team_member_notifications WHERE user_id=? AND read_at IS NULL",
        (user["id"],),
    )["count"]
    achievements = _achievement_items(metrics)
    return {
        "coins": metrics["coins"],
        "knowledge_balance": metrics["knowledge_balance"],
        "truth_balance": metrics["truth_balance"],
        "truth_crystals": metrics["truth_crystals"],
        "favorites": metrics["favorite_count"],
        "unread_notifications": int(personal_unread or 0) + int(team_unread or 0),
        "unlocked_achievements": sum(1 for item in achievements if item["unlocked"]),
        "total_achievements": len(achievements),
    }


@app.get("/api/notifications")
def notifications(user: CurrentUser, limit: int = Query(20, ge=1, le=80)) -> dict:
    read_state = row("SELECT last_read_at FROM notification_reads WHERE user_id=?", (user["id"],))
    last_read_at = read_state["last_read_at"] if read_state else ""
    items = []
    system_items = rows(
        "SELECT id,module,action,detail,created_at FROM system_logs WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user["id"], limit),
    )
    for item in system_items:
        item["id"] = f"system:{item['id']}"
        item["source"] = "personal"
        item["title"] = f"{item['module']} / {item['action']}"
        item["read"] = bool(last_read_at and item["created_at"] <= last_read_at)
        items.append(item)
    team_items = rows(
        "SELECT n.id,n.module,n.action,n.title,n.detail,n.created_at,n.read_at,t.name team_name "
        "FROM team_member_notifications n LEFT JOIN teams t ON t.id=n.team_id "
        "WHERE n.user_id=? ORDER BY n.id DESC LIMIT ?",
        (user["id"], limit),
    )
    for item in team_items:
        item["id"] = f"team:{item['id']}"
        item["source"] = "team"
        item["module"] = item["team_name"] or "团队通知"
        item["read"] = bool(item.get("read_at"))
        items.append(item)
    items.sort(key=lambda value: value.get("created_at") or "", reverse=True)
    items = items[:limit]
    unread = sum(1 for item in items if not item["read"])
    return {"items": items, "unread": unread, "last_read_at": last_read_at}


@app.post("/api/notifications/read")
def mark_notifications_read(user: CurrentUser) -> dict:
    now = utcnow()
    execute(
        "INSERT INTO notification_reads(user_id,last_read_at) VALUES(?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET last_read_at=excluded.last_read_at",
        (user["id"], now),
    )
    execute(
        "UPDATE team_member_notifications SET read_at=COALESCE(read_at,?) WHERE user_id=? AND read_at IS NULL",
        (now, user["id"]),
    )
    return {"last_read_at": now, "unread": 0}


@app.get("/api/achievements")
def achievements(user: CurrentUser) -> dict:
    metrics = _user_metrics(user["id"])
    items = _achievement_items(metrics)
    return {
        "items": items,
        "unlocked": sum(1 for item in items if item["unlocked"]),
        "total": len(items),
        "metrics": metrics,
    }


@app.get("/api/favorites")
def favorites(user: CurrentUser) -> dict:
    items = rows(
        "SELECT m.*,f.created_at favorite_at FROM user_favorites f "
        "JOIN materials m ON m.id=f.material_id "
        "WHERE f.user_id=? AND m.user_id=? ORDER BY f.created_at DESC",
        (user["id"], user["id"]),
    )
    return {"items": items, "total": len(items)}


@app.post("/api/materials/{material_id}/favorite")
def add_favorite(material_id: int, user: CurrentUser) -> dict:
    material = row("SELECT id,name FROM materials WHERE id=? AND user_id=?", (material_id, user["id"]))
    if not material:
        raise HTTPException(404, "素材不存在")
    execute(
        "INSERT OR IGNORE INTO user_favorites(user_id,material_id,created_at) VALUES(?,?,?)",
        (user["id"], material_id, utcnow()),
    )
    _invalidate_user_cache(user["id"])
    log_event(user["id"], "favorite", "add", f"收藏素材 {material['name']}")
    return {"material_id": material_id, "favorite": True}


@app.delete("/api/materials/{material_id}/favorite")
def remove_favorite(material_id: int, user: CurrentUser) -> dict:
    execute("DELETE FROM user_favorites WHERE user_id=? AND material_id=?", (user["id"], material_id))
    _invalidate_user_cache(user["id"])
    log_event(user["id"], "favorite", "remove", f"取消收藏素材 #{material_id}")
    return {"material_id": material_id, "favorite": False}


@app.get("/api/materials")
def list_materials(user: CurrentUser, status: str | None = None, q: str = "") -> list[dict]:
    cache_key = f"materials:{user['id']}:{status or '*'}:{q.strip().lower()}"
    cached = redis_cache_get_json(cache_key)
    if isinstance(cached, list):
        return cached
    query = (
        "SELECT m.*,CASE WHEN f.material_id IS NULL THEN 0 ELSE 1 END favorite "
        "FROM materials m LEFT JOIN user_favorites f ON f.material_id=m.id AND f.user_id=? "
        "WHERE m.user_id=?"
    )
    params: list = [user["id"]]
    params.append(user["id"])
    if status:
        query += " AND m.status=?"
        params.append(status)
    if q:
        query += " AND (m.name LIKE ? OR m.content LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    result = rows(query + " ORDER BY m.id DESC", tuple(params))
    redis_cache_set_json(cache_key, result, ttl=30)
    return result


@app.post("/api/materials/upload", status_code=201)
async def upload_material(user: CurrentUser, file: UploadFile = File(...), category: str = "未分类") -> dict:
    name = Path(file.filename or "upload").name
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "不支持的文件类型")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "文件超过大小限制")
    target = settings.upload_dir / f"{uuid.uuid4().hex}{extension}"
    target.write_bytes(data)
    kind = "视频" if extension in VIDEO_EXTENSIONS else "图片" if extension in IMAGE_EXTENSIONS else extension[1:].upper()
    status = "processing" if extension in VIDEO_EXTENSIONS | IMAGE_EXTENSIONS else "ready"
    content = data.decode("utf-8", errors="ignore")[:100_000] if extension in {".txt", ".md"} else f"{name} 的本地处理内容"
    material_id = execute("INSERT INTO materials(user_id,name,source,kind,size,status,category,content,file_path,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (user["id"], name, "upload", kind, len(data), status, category, content, target.name, utcnow()))
    if status == "ready":
        credit_personal(
            int(user["id"]),
            "knowledge",
            4,
            reason_code="material_upload",
            reason="上传文档并完成入库",
            idempotency_key=f"material:upload:{material_id}",
            reference_type="material",
            reference_id=str(material_id),
        )
    log_event(user["id"], "material", "upload", f"上传 {name}")
    material = row("SELECT * FROM materials WHERE id=?", (material_id,))
    es_index_document("zhiyan_materials", str(material_id), {
        "id": material_id, "name": name, "kind": kind,
        "content": content, "category": category,
        "user_id": user["id"], "status": status,
    })
    _invalidate_user_cache(user["id"])
    if status == "ready":
        _safe_graph_refresh(user["id"], [material_id])
    return material


async def _read_ocr_image(file: UploadFile) -> tuple[bytes, str]:
    name = Path(file.filename or "image").name
    extension = Path(name).suffix.lower()
    if extension not in IMAGE_EXTENSIONS:
        raise HTTPException(415, "仅支持 PNG、JPG、JPEG、BMP 和 TIFF 图片")
    data = await file.read(settings.ocr_max_image_bytes + 1)
    if len(data) > settings.ocr_max_image_bytes:
        raise HTTPException(413, "图片超过 OCR 大小限制")
    if not data:
        raise HTTPException(422, "图片内容不能为空")
    try:
        inspect_image(data)
    except OcrError as exc:
        raise HTTPException(422, str(exc)) from exc
    return data, extension


async def _read_video_upload(file: UploadFile) -> tuple[bytes, str]:
    name = Path(file.filename or "video").name
    extension = Path(name).suffix.lower()
    if extension not in VIDEO_EXTENSIONS:
        raise HTTPException(415, "仅支持 MP4、MOV、MKV、AVI 和 WebM 视频")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "视频超过大小限制")
    if not data:
        raise HTTPException(422, "视频内容不能为空")
    return data, extension


@app.post("/api/materials/video/preview")
async def preview_video(user: CurrentUser, file: UploadFile = File(...)) -> dict:
    data, extension = await _read_video_upload(file)
    try:
        result = await asyncio.to_thread(analyze_video_text, data, extension)
    except VideoAnalysisError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not result["content"]:
        raise HTTPException(422, "未从视频中提取到内嵌字幕或可识别的画面文字")
    return {
        **result,
        "filename": Path(file.filename or "video").name,
        "size": len(data),
        "characters": len(str(result["content"])),
        "analyzed_at": utcnow(),
    }


@app.post("/api/materials/video", status_code=201)
async def create_video_material(
    user: CurrentUser,
    file: UploadFile = File(...),
    name: str = Form(...),
    category: str = Form("未分类"),
    content: str = Form(...),
) -> dict:
    data, extension = await _read_video_upload(file)
    clean_name = name.strip()
    clean_content = content.strip()
    clean_category = category.strip() or "未分类"
    if not clean_name:
        raise HTTPException(422, "素材名称不能为空")
    if not clean_content:
        raise HTTPException(422, "视频文本不能为空")
    if len(clean_content) > settings.fetch_mcp_max_chars:
        raise HTTPException(413, "视频文本超过可入库的长度上限")

    quota = consume_personal_quota(
        int(user["id"]),
        "video_transcribe",
        idempotency_key=f"video-transcribe:{user['id']}:{uuid.uuid4().hex}",
        reference_type="material",
        reference_id=clean_name,
    )
    target = settings.upload_dir / f"{uuid.uuid4().hex}{extension}"
    target.write_bytes(data)
    material_id = execute(
        "INSERT INTO materials(user_id,name,source,kind,size,status,category,content,file_path,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user["id"], clean_name, "video", "视频", len(data), "ready", clean_category, clean_content, target.name, utcnow()),
    )
    credit_personal(
        int(user["id"]),
        "knowledge",
        8,
        reason_code="video_transcribe",
        reason="视频转写完成",
        idempotency_key=f"material:video:{material_id}:knowledge",
        reference_type="material",
        reference_id=str(material_id),
    )
    credit_personal(
        int(user["id"]),
        "truth",
        1,
        reason_code="video_transcribe_reward",
        reason="视频转写完成奖励",
        idempotency_key=f"material:video:{material_id}:truth",
        reference_type="material",
        reference_id=str(material_id),
    )
    log_event(user["id"], "material", "video_extract", f"提取视频文本 {Path(file.filename or clean_name).name}")
    material = row("SELECT * FROM materials WHERE id=?", (material_id,))
    es_index_document("zhiyan_materials", str(material_id), {
        "id": material_id, "name": clean_name, "kind": "视频",
        "content": clean_content, "category": clean_category,
        "user_id": user["id"], "status": "ready",
    })
    _invalidate_user_cache(user["id"])
    _safe_graph_refresh(user["id"], [material_id])
    material["currency"] = {"charged": quota.get("charged", 0), "currency": "knowledge"}
    return material


@app.post("/api/materials/image/preview")
async def preview_image(user: CurrentUser, file: UploadFile = File(...)) -> dict:
    data, _ = await _read_ocr_image(file)
    try:
        result = await asyncio.to_thread(extract_image_text, data)
    except OcrError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not result["content"]:
        raise HTTPException(422, "未从图片中识别到可读取文字")
    return {
        **result,
        "filename": Path(file.filename or "image").name,
        "size": len(data),
        "characters": len(str(result["content"])),
        "recognized_at": utcnow(),
    }


@app.post("/api/materials/image", status_code=201)
async def create_image_material(
    user: CurrentUser,
    file: UploadFile = File(...),
    name: str = Form(...),
    category: str = Form("未分类"),
    content: str = Form(...),
) -> dict:
    data, extension = await _read_ocr_image(file)
    clean_name = name.strip()
    clean_content = content.strip()
    clean_category = category.strip() or "未分类"
    if not clean_name:
        raise HTTPException(422, "素材名称不能为空")
    if not clean_content:
        raise HTTPException(422, "识别文本不能为空")
    if len(clean_content) > settings.fetch_mcp_max_chars:
        raise HTTPException(413, "识别文本超过可入库的长度上限")

    quota = consume_personal_quota(
        int(user["id"]),
        "image_ocr",
        idempotency_key=f"image-ocr:{user['id']}:{uuid.uuid4().hex}",
        reference_type="material",
        reference_id=clean_name,
    )
    target = settings.upload_dir / f"{uuid.uuid4().hex}{extension}"
    target.write_bytes(data)
    material_id = execute(
        "INSERT INTO materials(user_id,name,source,kind,size,status,category,content,file_path,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user["id"], clean_name, "image", "图片", len(data), "ready", clean_category, clean_content, target.name, utcnow()),
    )
    credit_personal(
        int(user["id"]),
        "knowledge",
        6,
        reason_code="image_ocr",
        reason="图片 OCR 识别完成",
        idempotency_key=f"material:ocr:{material_id}",
        reference_type="material",
        reference_id=str(material_id),
    )
    log_event(user["id"], "material", "ocr", f"识别图片 {Path(file.filename or clean_name).name}")
    material = row("SELECT * FROM materials WHERE id=?", (material_id,))
    es_index_document("zhiyan_materials", str(material_id), {
        "id": material_id, "name": clean_name, "kind": "图片",
        "content": clean_content, "category": clean_category,
        "user_id": user["id"], "status": "ready",
    })
    _invalidate_user_cache(user["id"])
    _safe_graph_refresh(user["id"], [material_id])
    material["currency"] = {"charged": quota.get("charged", 0), "currency": "knowledge"}
    return material


@app.post("/api/materials/text", status_code=201)
def create_text(payload: TextMaterialRequest, user: CurrentUser) -> dict:
    clean_name = payload.name.strip()
    clean_content = payload.content.strip()
    clean_category = payload.category.strip() or "未分类"
    if not clean_name:
        raise HTTPException(422, "素材名称不能为空")
    if not clean_content:
        raise HTTPException(422, "知识内容不能为空")
    if len(clean_content) > settings.fetch_mcp_max_chars:
        raise HTTPException(413, "知识内容超过可入库的长度上限")

    material_id = execute(
        "INSERT INTO materials(user_id,name,source,kind,size,status,category,content,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (user["id"], clean_name, "manual", "文本", len(clean_content.encode("utf-8")), "ready", clean_category, clean_content, utcnow()),
    )
    credit_personal(
        int(user["id"]),
        "knowledge",
        3,
        reason_code="material_manual",
        reason="创建文本知识素材",
        idempotency_key=f"material:text:{material_id}",
        reference_type="material",
        reference_id=str(material_id),
    )
    log_event(user["id"], "material", "create", f"新建文本 {clean_name}")
    # Index in Elasticsearch for full-text search
    material = row("SELECT * FROM materials WHERE id=?", (material_id,))
    es_index_document("zhiyan_materials", str(material_id), {
        "id": material_id, "name": clean_name, "kind": "文本",
        "content": clean_content, "category": clean_category,
        "user_id": user["id"], "status": "ready",
    })
    _invalidate_user_cache(user["id"])
    _safe_graph_refresh(user["id"], [material_id])
    return material


async def _fetch_web_content(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise HTTPException(422, "请输入有效的 HTTP(S) 地址")
    try:
        content = await fetch_url_content(url)
    except FetchMcpNotConfigured as exc:
        raise HTTPException(503, "尚未配置 Fetch MCP，暂时无法抓取网页正文") from exc
    except FetchMcpError as exc:
        raise HTTPException(502, str(exc)) from exc
    if not content:
        raise HTTPException(502, "Fetch MCP 未返回网页正文")
    return content


def _suggest_web_title(content: str, url: str) -> str:
    first_line = next((line.strip("# ") for line in content.splitlines() if line.strip("# ")), "")
    if first_line and len(first_line) <= 200:
        return first_line
    return urlparse(url).hostname or "网页素材"


@app.post("/api/materials/url/preview")
async def preview_url(payload: UrlPreviewRequest, user: CurrentUser) -> dict:
    content = await _fetch_web_content(payload.url)
    encoded_size = len(content.encode("utf-8"))
    return {
        "url": payload.url,
        "host": urlparse(payload.url).hostname or "",
        "title": _suggest_web_title(content, payload.url),
        "content": content,
        "size": encoded_size,
        "characters": len(content),
        "fetched_at": utcnow(),
    }


@app.post("/api/materials/url", status_code=201)
async def create_url(payload: UrlMaterialRequest, user: CurrentUser) -> dict:
    if not payload.url.startswith(("http://", "https://")):
        raise HTTPException(422, "Only HTTP(S) page URLs can be saved")
    content = payload.content.strip() if payload.content else await _fetch_web_content(payload.url)
    if not content:
        raise HTTPException(422, "The collected page content cannot be empty")
    if len(content) > settings.fetch_mcp_max_chars:
        raise HTTPException(413, "网页正文超过可入库的长度上限")
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "The material name cannot be empty")
    category = payload.category.strip() or "未分类"
    material_id = execute(
        "INSERT INTO materials(user_id,name,source,kind,size,status,category,content,origin_url,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user["id"], name, "url", "网页", len(content.encode()), "ready", category, content, payload.url, utcnow()),
    )
    credit_personal(
        int(user["id"]),
        "knowledge",
        4,
        reason_code="material_url",
        reason="保存网页知识素材",
        idempotency_key=f"material:url:{material_id}",
        reference_type="material",
        reference_id=str(material_id),
    )
    log_event(user["id"], "material", "fetch", payload.url)
    material = row("SELECT * FROM materials WHERE id=?", (material_id,))
    es_index_document("zhiyan_materials", str(material_id), {
        "id": material_id, "name": name, "kind": "网页",
        "content": content, "category": category, "origin_url": payload.url,
        "user_id": user["id"], "status": "ready",
    })
    _invalidate_user_cache(user["id"])
    _safe_graph_refresh(user["id"], [material_id])
    return material


@app.post("/api/materials/{material_id}/process")
def process_material(material_id: int, user: CurrentUser) -> dict:
    material = row("SELECT * FROM materials WHERE id=? AND user_id=?", (material_id, user["id"]))
    if not material:
        raise HTTPException(404, "素材不存在")
    execute("UPDATE materials SET status='ready',error='' WHERE id=?", (material_id,))
    material = row("SELECT * FROM materials WHERE id=?", (material_id,))
    if material["kind"] == "图片":
        credit_personal(
            int(user["id"]),
            "knowledge",
            6,
            reason_code="image_ocr",
            reason="图片 OCR 处理完成",
            idempotency_key=f"material:process:{material_id}:image",
            reference_type="material",
            reference_id=str(material_id),
        )
    elif material["kind"] == "视频":
        credit_personal(
            int(user["id"]),
            "knowledge",
            8,
            reason_code="video_transcribe",
            reason="视频转写处理完成",
            idempotency_key=f"material:process:{material_id}:video:knowledge",
            reference_type="material",
            reference_id=str(material_id),
        )
        credit_personal(
            int(user["id"]),
            "truth",
            1,
            reason_code="video_transcribe_reward",
            reason="视频转写处理完成奖励",
            idempotency_key=f"material:process:{material_id}:video:truth",
            reference_type="material",
            reference_id=str(material_id),
        )
    es_index_document("zhiyan_materials", str(material_id), {
        "id": material_id, "name": material["name"], "kind": material["kind"],
        "content": material["content"], "category": material["category"],
        "user_id": user["id"], "status": "ready",
    })
    _invalidate_user_cache(user["id"])
    log_event(user["id"], "material", "process", material["name"])
    _safe_graph_refresh(user["id"], [material_id])
    return material


@app.post("/api/materials/{material_id}/ask")
async def ask_material(material_id: int, payload: MaterialAskRequest, user: CurrentUser) -> dict:
    question = payload.question.strip()
    if not question:
        raise HTTPException(422, "问题不能为空")
    material = row("SELECT * FROM materials WHERE id=? AND user_id=?", (material_id, user["id"]))
    if not material:
        raise HTTPException(404, "素材不存在")
    if str(material.get("status") or "") != "ready":
        raise HTTPException(409, "素材尚未完成入库处理，暂不能问答")
    quota_key = f"material-ask:{user['id']}:{material_id}:{uuid.uuid4().hex}"
    quota = consume_personal_quota(
        int(user["id"]),
        "material_ask",
        idempotency_key=quota_key,
        reference_type="material",
        reference_id=str(material_id),
    )
    try:
        result = await answer_material_question(
            material,
            question,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            proxy_url=settings.deepseek_proxy_url,
        )
    except MaterialQaAgentError as exc:
        if quota.get("charged"):
            credit_personal(
                int(user["id"]),
                "knowledge",
                int(quota["charged"]),
                reason_code="quota_refund",
                reason="素材问答服务失败，退回已扣学识币",
                idempotency_key=f"{quota_key}:refund",
                reference_type="material",
                reference_id=str(material_id),
            )
        raise HTTPException(422, str(exc)) from exc
    log_event(user["id"], "ai", "material_ask", f"{material['name']} | {question[:80]}")
    return {
        "material": {
            "id": material["id"],
            "name": material["name"],
            "kind": material["kind"],
            "category": material["category"],
        },
        "question": question,
        **result,
    }


def _stored_material_path(filename: str) -> Path | None:
    if not filename:
        return None
    upload_root = settings.upload_dir.resolve()
    target = (upload_root / Path(filename).name).resolve()
    return target if target.parent == upload_root else None


@app.get("/api/materials/{material_id}/file")
def get_material_file(material_id: int, user: CurrentUser) -> FileResponse:
    material = row("SELECT file_path FROM materials WHERE id=? AND user_id=?", (material_id, user["id"]))
    if not material:
        raise HTTPException(404, "素材不存在")
    target = _stored_material_path(material.get("file_path", ""))
    if target is None or not target.is_file():
        raise HTTPException(404, "素材原文件不存在")
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type)


@app.delete("/api/materials/{material_id}", status_code=204, response_class=Response)
def delete_material(material_id: int, user: CurrentUser):
    with connection() as conn:
        material_row = conn.execute(
            "SELECT name,file_path FROM materials WHERE id=? AND user_id=?",
            (material_id, user["id"]),
        ).fetchone()
        if not material_row:
            raise HTTPException(404, "素材不存在")
        material = dict(material_row)
        task_ids = [item[0] for item in conn.execute(
            "SELECT DISTINCT r.task_id FROM evolution_reviews r JOIN evolution_tasks t ON t.id=r.task_id "
            "WHERE r.material_id=? AND r.decision='pending' AND t.user_id=?",
            (material_id, user["id"]),
        ).fetchall()]
        conn.execute(
            "UPDATE evolution_reviews SET decision='rejected' WHERE material_id=? AND decision='pending'",
            (material_id,),
        )
        conn.execute("DELETE FROM materials WHERE id=? AND user_id=?", (material_id, user["id"]))
        for task_id in task_ids:
            remaining = int(conn.execute(
                "SELECT COUNT(*) FROM evolution_reviews WHERE task_id=? AND decision='pending'",
                (task_id,),
            ).fetchone()[0])
            if remaining == 0:
                conn.execute(
                    "UPDATE evolution_tasks SET status='completed',progress=100,finished_at=? WHERE id=?",
                    (utcnow(), task_id),
                )
    target = _stored_material_path(material.get("file_path", ""))
    if target is not None:
        target.unlink(missing_ok=True)
    log_event(user["id"], "material", "delete", material["name"])
    es_delete_document("zhiyan_materials", str(material_id))
    _invalidate_user_cache(user["id"])
    _safe_graph_refresh(user["id"])
    return Response(status_code=204)


@app.get("/api/customer-service/knowledge")
def customer_service_knowledge_endpoint(user: CurrentUser) -> dict:
    del user
    return customer_service_knowledge()


@app.post("/api/customer-service/ask")
async def customer_service_ask(payload: CustomerServiceAskRequest, user: CurrentUser) -> dict:
    question = payload.question.strip()
    if not question:
        raise HTTPException(422, "问题不能为空")
    try:
        result = await answer_customer_service_agent(
            question,
            [item.model_dump() for item in payload.history],
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            proxy_url=settings.deepseek_proxy_url,
        )
    except CustomerServiceAgentError as exc:
        raise HTTPException(503, str(exc)) from exc
    log_event(user["id"], "customer_service", "ask", question[:160])
    return result


@app.post("/api/customer-service/ask/stream")
async def customer_service_ask_stream(payload: CustomerServiceAskRequest, user: CurrentUser) -> StreamingResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(422, "问题不能为空")

    async def event_stream():
        try:
            async for event in stream_customer_service_agent(
                question,
                [item.model_dump() for item in payload.history],
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
                proxy_url=settings.deepseek_proxy_url,
            ):
                if event.get("type") == "done":
                    log_event(user["id"], "customer_service", "ask", question[:160])
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except CustomerServiceAgentError as exc:
            error_event = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            error_event = {"type": "error", "message": f"客服 Agent 调用失败：{str(exc)[:180]}"}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/ai/chat")
async def ai_chat(payload: ChatRequest, user: CurrentUser) -> dict:
    question = payload.question.strip()
    if not question:
        raise HTTPException(422, "问题不能为空")
    if not settings.deepseek_api_key:
        raise HTTPException(503, "标准 AI 问答缺少 DEEPSEEK_API_KEY")
    try:
        retrieved = hybrid_search(question, user["id"], top_k=5)
    except Exception as exc:
        raise HTTPException(503, f"标准 hybrid retrieval 不可用：{str(exc)[:180]}") from exc
    if not retrieved:
        raise HTTPException(404, "标准知识检索未找到相关素材")
    quota_key = f"ai-chat:{user['id']}:{uuid.uuid4().hex}"
    quota = consume_personal_quota(
        int(user["id"]),
        "ai_chat",
        idempotency_key=quota_key,
        reference_type="ai",
        reference_id=question[:80],
    )
    context = "\n\n".join(
        f"[{item.get('name', '知识片段')}]\n{item.get('content', '')}"
        for item in retrieved
    )
    try:
        client_options = {"timeout": 60}
        if settings.deepseek_proxy_url:
            client_options["proxy"] = settings.deepseek_proxy_url
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.post(
                f"{settings.deepseek_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                json={
                    "model": settings.deepseek_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是知识库问答 Agent，只能依据给定 context 回答，并在答案中保留来源名称；没有依据时明确说不知道。",
                        },
                        {"role": "user", "content": f"context:\n{context}\n\nquestion:\n{question}"},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1200,
                },
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        if quota.get("charged"):
            credit_personal(
                int(user["id"]),
                "knowledge",
                int(quota["charged"]),
                reason_code="quota_refund",
                reason="标准 AI 问答调用失败，退回已扣学识币",
                idempotency_key=f"{quota_key}:refund",
                reference_type="ai",
                reference_id=question[:80],
            )
        raise HTTPException(502, f"DeepSeek 标准问答调用失败：{str(exc)[:180]}") from exc
    citations = [
        {"id": item.get("id"), "name": item.get("name"), "excerpt": str(item.get("content", ""))[:160]}
        for item in retrieved
    ]
    log_event(user["id"], "ai", "chat", question[:80])
    return {"answer": str(answer).strip(), "citations": citations, "mode": "hybrid-rag-deepseek"}

    # Legacy demo-only implementation below is intentionally unreachable.
    return {"answer": "", "citations": [], "mode": "unreachable"}
    terms = [term for term in re.split(r"\W+", question) if len(term) > 1]

    # Try Elasticsearch full-text search first
    es_results = es_search("zhiyan_materials", question, fields=["content", "name"], size=5, user_id=user["id"])
    if es_results:
        # Use ES results as context
        context_parts = [f"[{r.get('name', 'ES结果')}] {r.get('content', '')}" for r in es_results]
        context = "\n".join(context_parts)
        citations = [{"id": r.get("id", ""), "name": r.get("name", "ES结果"), "excerpt": r.get("content", "")[:120]} for r in es_results]
    else:
        # Fallback to local keyword matching on SQLite materials
        materials = rows("SELECT id,name,content FROM materials WHERE user_id=? AND status='ready'", (user["id"],))
        if materials:
            ranked = sorted(materials, key=lambda item: sum(item["content"].lower().count(t.lower()) for t in terms), reverse=True)[:3]
        else:
            ranked = []
        citations = [{"id": item["id"], "name": item["name"], "excerpt": item["content"][:120]} for item in ranked]
        context = "\n".join(f"[{item['name']}] {item['content']}" for item in ranked)

    # Try DeepSeek API if configured
    mode = "unreachable-legacy"
    if settings.deepseek_api_key and context:
        try:
            client_options = {"timeout": 30}
            if settings.deepseek_proxy_url:
                client_options["proxy"] = settings.deepseek_proxy_url
            async with httpx.AsyncClient(**client_options) as client:
                resp = await client.post(
                    f"{settings.deepseek_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                    json={
                        "model": "deepseek-chat",
                        "messages": [
                            {"role": "system", "content": "你是一个知识库助手。仅依据提供的知识库内容回答问题，并在回答中引用来源。如果知识库中没有相关信息，请诚实说明。"},
                            {"role": "user", "content": f"知识库内容：\n{context}\n\n用户问题：{question}"}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1024,
                    },
                )
                resp.raise_for_status()
                answer = resp.json()["choices"][0]["message"]["content"]
                mode = "deepseek"
        except Exception as exc:
            # Fallback to keyword-based local answer
            answer = f"⚠️ AI 服务暂时不可用（{str(exc)[:80]}）。根据本地知识库关键词匹配：\n\n" + (
                context[:500] if context else "暂无可引用知识，请先导入素材。"
            )
    elif not context:
        answer = "目前知识库中还没有已入库的素材。请先在「知识库」中上传或创建内容，然后再次提问。"
    else:
        answer = f"💡 演示模式（未配置 DeepSeek API Key）：\n\n根据你的知识库关键词匹配，相关内容如下：\n\n{context[:600]}"

    log_event(user["id"], "ai", "chat", question[:80])
    return {"answer": answer, "citations": citations, "mode": mode}


async def _generate_evolution_proposal(material: dict) -> tuple[str, str]:
    return await run_evolution_agents(
        material,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        proxy_url=settings.deepseek_proxy_url,
    )


def _review_with_material(review_id: int, user_id: int) -> dict | None:
    return row(
        "SELECT r.*,m.name material_name,m.kind material_kind,m.category material_category,"
        "(SELECT MAX(v.version) FROM evolution_versions v WHERE v.review_id=r.id) version "
        "FROM evolution_reviews r JOIN evolution_tasks t ON t.id=r.task_id "
        "LEFT JOIN materials m ON m.id=r.material_id "
        "WHERE r.id=? AND t.user_id=?",
        (review_id, user_id),
    )


def _evolution_task_with_counts(task_id: int, user_id: int) -> dict | None:
    return row(
        "SELECT t.*,COUNT(r.id) review_count,"
        "COALESCE(SUM(CASE WHEN r.decision='accepted' THEN 1 ELSE 0 END),0) accepted_count,"
        "COALESCE(SUM(CASE WHEN r.decision='rejected' THEN 1 ELSE 0 END),0) rejected_count,"
        "COALESCE(SUM(CASE WHEN r.decision='rolled_back' THEN 1 ELSE 0 END),0) rolled_back_count "
        "FROM evolution_tasks t LEFT JOIN evolution_reviews r ON r.task_id=t.id "
        "WHERE t.id=? AND t.user_id=? GROUP BY t.id",
        (task_id, user_id),
    )


def _evolution_task_reviews(task_id: int, user_id: int) -> list[dict]:
    return rows(
        "SELECT r.*,m.name material_name,m.kind material_kind,m.category material_category,"
        "LENGTH(r.original_text) original_chars,LENGTH(r.proposed_text) proposed_chars,"
        "(SELECT MAX(v.version) FROM evolution_versions v WHERE v.review_id=r.id) version "
        "FROM evolution_reviews r JOIN evolution_tasks t ON t.id=r.task_id "
        "LEFT JOIN materials m ON m.id=r.material_id "
        "WHERE r.task_id=? AND t.user_id=? ORDER BY r.id",
        (task_id, user_id),
    )


def _mark_evolution_task_failed(task_id: int, user_id: int, message: str) -> None:
    execute(
        "UPDATE evolution_tasks SET status='failed',error=?,summary=?,finished_at=? WHERE id=? AND user_id=?",
        (message[:500], "知识进化未完成，原素材未发生变更。", utcnow(), task_id, user_id),
    )


def _store_manual_evolution(
    task_id: int,
    user_id: int,
    materials: list[dict],
    proposals: list[tuple[str, str]],
) -> list[int]:
    review_ids: list[int] = []
    with connection() as conn:
        for material, (proposed, reason) in zip(materials, proposals):
            review_ids.append(int(conn.execute(
                "INSERT INTO evolution_reviews(task_id,material_id,title,original_text,proposed_text,reason) VALUES(?,?,?,?,?,?)",
                (task_id, material["id"], f"进化：{material['name'][:80]}", material["content"], proposed, reason),
            ).lastrowid))
        conn.execute(
            "UPDATE evolution_tasks SET status='review',progress=70,summary=?,error='' WHERE id=? AND user_id=?",
            (f"已生成 {len(materials)} 篇进化文档，等待逐条预览确认。", task_id, user_id),
        )
    return review_ids


def _apply_auto_evolution(
    task_id: int,
    user_id: int,
    materials: list[dict],
    proposals: list[tuple[str, str]],
) -> list[int]:
    for proposed, _ in proposals:
        if not proposed.strip():
            raise HTTPException(422, "Agent 生成的进化正文为空，自动模式未写入任何素材")
        if len(proposed) > settings.fetch_mcp_max_chars:
            raise HTTPException(413, "Agent 生成的进化正文超过入库上限，自动模式未写入任何素材")

    review_ids: list[int] = []
    indexed_materials: list[dict] = []
    applied_at = utcnow()
    with connection() as conn:
        task = conn.execute(
            "SELECT id FROM evolution_tasks WHERE id=? AND user_id=? AND status='processing'",
            (task_id, user_id),
        ).fetchone()
        if not task:
            raise HTTPException(409, "自动进化任务状态已变化，请刷新后重试")

        for material, (proposed, reason) in zip(materials, proposals):
            material_row = conn.execute(
                "SELECT * FROM materials WHERE id=? AND user_id=?",
                (material["id"], user_id),
            ).fetchone()
            if not material_row:
                raise HTTPException(404, f"自动应用失败：素材「{material['name']}」已不存在")
            current = dict(material_row)
            if current["content"] != material["content"]:
                raise HTTPException(409, f"素材「{material['name']}」在进化期间已被修改，自动模式未写入任何素材")

            review_id = int(conn.execute(
                "INSERT INTO evolution_reviews(task_id,material_id,title,original_text,proposed_text,reason,decision,applied_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (task_id, material["id"], f"进化：{material['name'][:80]}", material["content"], proposed, reason, "accepted", applied_at),
            ).lastrowid)
            review_ids.append(review_id)
            version = int(conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM evolution_versions WHERE material_id=?",
                (material["id"],),
            ).fetchone()[0])
            conn.execute(
                "INSERT INTO evolution_versions(material_id,user_id,task_id,review_id,version,previous_content,new_content,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (material["id"], user_id, task_id, review_id, version, material["content"], proposed, applied_at),
            )
            encoded_size = len(proposed.encode("utf-8"))
            conn.execute(
                "UPDATE materials SET content=?,size=?,status='ready',error='' WHERE id=? AND user_id=?",
                (proposed, encoded_size, material["id"], user_id),
            )
            indexed_materials.append({**current, "content": proposed, "size": encoded_size, "version": version})

        conn.execute(
            "UPDATE evolution_tasks SET status='completed',progress=100,summary=?,error='',finished_at=? WHERE id=? AND user_id=?",
            (f"自动进化已完成：{len(materials)} 个素材全部通过质量审核、写回知识库并保存版本。", applied_at, task_id, user_id),
        )

    for material in indexed_materials:
        es_index_document("zhiyan_materials", str(material["id"]), {
            "id": material["id"], "name": material["name"], "kind": material["kind"],
            "content": material["content"], "category": material["category"],
            "user_id": user_id, "status": "ready",
        })
        log_event(user_id, "evolution", "auto_apply", f"自动应用知识进化：{material['name']} v{material['version']}")
    _invalidate_user_cache(user_id)
    try:
        _safe_graph_refresh(user_id)
    except Exception as exc:
        # Graph refresh must not invalidate a successfully applied evolution.
        log_event(user_id, "graph", "rebuild_failed", str(exc)[:160])
    return review_ids


def _apply_evolution_review(review_id: int, decision: str, proposed_text: str | None, user_id: int) -> dict:
    indexed_material: dict | None = None
    version: int | None = None
    with connection() as conn:
        review_row = conn.execute(
            "SELECT r.* FROM evolution_reviews r JOIN evolution_tasks t ON t.id=r.task_id "
            "WHERE r.id=? AND t.user_id=?",
            (review_id, user_id),
        ).fetchone()
        if not review_row:
            raise HTTPException(404, "审核项不存在")
        review = dict(review_row)
        if review["decision"] != "pending":
            raise HTTPException(409, "该进化建议已经处理")

        final_text = (proposed_text if proposed_text is not None else review["proposed_text"]).strip()
        applied_at = None
        if decision == "accepted":
            if not review.get("material_id"):
                raise HTTPException(422, "审核项未关联可更新的素材")
            if not final_text:
                raise HTTPException(422, "进化后的正文不能为空")
            if len(final_text) > settings.fetch_mcp_max_chars:
                raise HTTPException(413, "进化后的正文超过可入库长度上限")
            material_row = conn.execute(
                "SELECT * FROM materials WHERE id=? AND user_id=?",
                (review["material_id"], user_id),
            ).fetchone()
            if not material_row:
                raise HTTPException(404, "目标素材不存在")
            material = dict(material_row)
            version = int(conn.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM evolution_versions WHERE material_id=?",
                (material["id"],),
            ).fetchone()[0])
            applied_at = utcnow()
            conn.execute(
                "INSERT INTO evolution_versions(material_id,user_id,task_id,review_id,version,previous_content,new_content,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (material["id"], user_id, review["task_id"], review_id, version, material["content"], final_text, applied_at),
            )
            conn.execute(
                "UPDATE materials SET content=?,size=?,status='ready',error='' WHERE id=? AND user_id=?",
                (final_text, len(final_text.encode("utf-8")), material["id"], user_id),
            )
            indexed_material = {**material, "content": final_text, "size": len(final_text.encode("utf-8"))}

        conn.execute(
            "UPDATE evolution_reviews SET decision=?,proposed_text=?,applied_at=? WHERE id=?",
            (decision, final_text, applied_at, review_id),
        )
        remaining = int(conn.execute(
            "SELECT COUNT(*) FROM evolution_reviews WHERE task_id=? AND decision='pending'",
            (review["task_id"],),
        ).fetchone()[0])
        if remaining == 0:
            conn.execute(
                "UPDATE evolution_tasks SET status='completed',progress=100,finished_at=? WHERE id=?",
                (utcnow(), review["task_id"]),
            )

    if indexed_material:
        es_index_document("zhiyan_materials", str(indexed_material["id"]), {
            "id": indexed_material["id"], "name": indexed_material["name"],
            "kind": indexed_material["kind"], "content": indexed_material["content"],
            "category": indexed_material["category"], "user_id": user_id, "status": "ready",
        })
        _invalidate_user_cache(user_id)
        log_event(user_id, "evolution", "apply", f"应用知识进化：{indexed_material['name']} v{version}")
        try:
            _safe_graph_refresh(user_id)
        except Exception as exc:
            log_event(user_id, "graph", "rebuild_failed", str(exc)[:160])
    else:
        log_event(user_id, "evolution", "reject", f"拒绝知识进化建议 #{review_id}")

    result = _review_with_material(review_id, user_id)
    if result is None:
        raise HTTPException(404, "审核项不存在")
    result["version"] = version
    return result


@app.get("/api/evolution")
def evolution_overview(user: CurrentUser) -> dict:
    latest_id = row("SELECT id FROM evolution_tasks WHERE user_id=? ORDER BY id DESC LIMIT 1", (user["id"],))
    latest = _evolution_task_with_counts(latest_id["id"], user["id"]) if latest_id else None
    pending = rows(
        "SELECT r.*,m.name material_name,m.kind material_kind,m.category material_category "
        "FROM evolution_reviews r JOIN evolution_tasks t ON t.id=r.task_id "
        "LEFT JOIN materials m ON m.id=r.material_id "
        "WHERE t.user_id=? AND r.decision='pending' ORDER BY r.id",
        (user["id"],),
    )
    materials = rows(
        "SELECT id,name,kind,size,status,category,SUBSTR(content,1,240) content,created_at FROM materials "
        "WHERE user_id=? AND status='ready' AND TRIM(content)<>'' ORDER BY id DESC",
        (user["id"],),
    )
    latest_reviews = _evolution_task_reviews(latest["id"], user["id"]) if latest else []

    if latest and latest["status"] == "failed":
        timeline = [{
            "agent": "系统核心", "time": "失败", "text": latest.get("error") or "知识进化任务执行失败，原素材未发生变更。", "tone": "red",
        }]
    elif latest:
        target_names = [item["material_name"] for item in latest_reviews if item.get("material_name")]
        target_text = "、".join(target_names[:3]) or "指定素材"
        phases = [
            ("知识分析 Agent", f"已扫描 {target_text} 并提取主要知识点。", "blue"),
            ("知识拓展 Agent", "已识别知识缺口并补充定义、机制、示例和边界。", "mint"),
            ("知识编辑 Agent", f"已重构生成 {latest['review_count']} 篇完整知识文档。", "cyan"),
            ("质量审核 Agent", "进化结果已写回素材并保留版本记录。" if latest["status"] == "completed" else "质量门槛已通过，等待逐条预览确认。", "cyan"),
        ]
        base_time = datetime.fromisoformat(latest["created_at"]) if latest.get("created_at") else datetime.now(timezone.utc)
        timeline = []
        for index, (agent, text, tone) in enumerate(phases):
            finished = latest["status"] == "completed"
            phase_time = base_time + timedelta(seconds=index * 8) if finished else None
            timeline.append({
                "agent": agent,
                "time": phase_time.strftime("%H:%M:%S") if phase_time else (
                    "进行中" if latest["status"] == "processing" else ("完成" if index < 3 else "等待审核")
                ),
                "text": text,
                "tone": tone,
            })
    else:
        timeline = [{"agent": "系统核心", "time": "就绪", "text": "选择知识素材后启动首次进化。", "tone": "cyan"}]

    return {
        "latest": latest,
        "pending": pending,
        "materials": materials,
        "latest_reviews": latest_reviews,
        "timeline": timeline,
        "settings": serialize_settings(row("SELECT * FROM user_settings WHERE user_id=?", (user["id"],))),
    }


@app.post("/api/evolution/start", status_code=201)
async def start_evolution(payload: EvolutionRequest, user: CurrentUser) -> dict:
    current_settings = row("SELECT auto_evolution FROM user_settings WHERE user_id=?", (user["id"],))
    if payload.mode == "auto" and (not current_settings or not bool(current_settings["auto_evolution"])):
        raise HTTPException(409, "自动进化已在系统设置中关闭，请先启用后再运行")
    existing_active = row(
        "SELECT t.id FROM evolution_tasks t WHERE t.user_id=? AND "
        "(t.status='processing' OR EXISTS(SELECT 1 FROM evolution_reviews r WHERE r.task_id=t.id AND r.decision='pending')) "
        "ORDER BY t.id DESC LIMIT 1",
        (user["id"],),
    )
    if existing_active:
        raise HTTPException(409, "已有正在执行或等待审核的进化任务，请先完成当前任务")

    material_ids = list(dict.fromkeys(payload.material_ids))
    placeholders = ",".join("?" for _ in material_ids)
    selected = rows(
        f"SELECT * FROM materials WHERE user_id=? AND id IN ({placeholders})",
        (user["id"], *material_ids),
    )
    selected_by_id = {item["id"]: item for item in selected}
    if len(selected_by_id) != len(material_ids):
        raise HTTPException(404, "部分目标素材不存在或无权访问")
    materials = [selected_by_id[material_id] for material_id in material_ids]
    invalid = [item["name"] for item in materials if item["status"] != "ready" or not str(item["content"]).strip()]
    if invalid:
        raise HTTPException(422, f"以下素材尚未就绪或没有正文：{'、'.join(invalid)}")

    evolution_charge = 0
    evolution_charge_key = ""
    if payload.mode == "auto" or len(materials) > 1:
        evolution_charge = max(1, (len(materials) + 2) // 3)
        evolution_charge_key = f"evolution:charge:{user['id']}:{uuid.uuid4().hex}"
        debit_personal(
            int(user["id"]),
            "truth",
            evolution_charge,
            reason_code="evolution_charge",
            reason=f"启动{('自动' if payload.mode == 'auto' else '批量')}知识进化",
            idempotency_key=evolution_charge_key,
            reference_type="evolution",
            reference_id="pending",
            metadata={"material_count": len(materials), "mode": payload.mode},
        )

    task_id = execute(
        "INSERT INTO evolution_tasks(user_id,mode,status,progress,improvements,corrections,expansions,summary,error,created_at,finished_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (user["id"], payload.mode, "processing", 10, 0, 0, 0,
         f"正在通过四阶段 Agent 处理 {len(materials)} 个指定素材。", "", utcnow(), None),
    )

    try:
        execute("UPDATE evolution_tasks SET progress=25 WHERE id=? AND user_id=?", (task_id, user["id"]))
        proposals = await asyncio.gather(*(_generate_evolution_proposal(material) for material in materials))
    except EvolutionAgentError as exc:
        if evolution_charge:
            credit_personal(
                int(user["id"]),
                "truth",
                evolution_charge,
                reason_code="evolution_refund",
                reason="知识进化服务失败，退回已扣真知晶",
                idempotency_key=f"{evolution_charge_key}:refund",
                reference_type="evolution",
                reference_id=str(task_id),
            )
        _mark_evolution_task_failed(task_id, user["id"], str(exc))
        log_event(user["id"], "evolution", "failed", f"任务 #{task_id}：{str(exc)[:160]}")
        raise HTTPException(502, str(exc)) from exc

    execute(
        "UPDATE evolution_tasks SET progress=70,improvements=?,corrections=?,expansions=? WHERE id=? AND user_id=?",
        (len(materials) * 3, len(materials), len(materials) * 2, task_id, user["id"]),
    )
    try:
        if payload.mode == "auto":
            review_ids = _apply_auto_evolution(task_id, user["id"], materials, proposals)
            status = "completed"
        else:
            review_ids = _store_manual_evolution(task_id, user["id"], materials, proposals)
            status = "review"
    except HTTPException as exc:
        if evolution_charge:
            credit_personal(
                int(user["id"]),
                "truth",
                evolution_charge,
                reason_code="evolution_refund",
                reason="知识进化结果未能写入，退回已扣真知晶",
                idempotency_key=f"{evolution_charge_key}:refund",
                reference_type="evolution",
                reference_id=str(task_id),
            )
        _mark_evolution_task_failed(task_id, user["id"], str(exc.detail))
        log_event(user["id"], "evolution", "failed", f"任务 #{task_id}：{str(exc.detail)[:160]}")
        raise
    except Exception as exc:
        message = f"知识进化结果写入失败：{str(exc)[:160]}"
        if evolution_charge:
            credit_personal(
                int(user["id"]),
                "truth",
                evolution_charge,
                reason_code="evolution_refund",
                reason="知识进化结果写入失败，退回已扣真知晶",
                idempotency_key=f"{evolution_charge_key}:refund",
                reference_type="evolution",
                reference_id=str(task_id),
            )
        _mark_evolution_task_failed(task_id, user["id"], message)
        log_event(user["id"], "evolution", "failed", f"任务 #{task_id}：{message}")
        raise HTTPException(500, message) from exc

    log_event(user["id"], "evolution", "start", f"{payload.mode} 模式，指定 {len(materials)} 个素材")
    rabbitmq_publish("zhiyan.evolution.tasks", {
        "task_id": task_id, "user_id": user["id"], "mode": payload.mode,
        "material_ids": material_ids, "timestamp": utcnow(),
    })
    reviews = _evolution_task_reviews(task_id, user["id"])
    task = _evolution_task_with_counts(task_id, user["id"])
    return {"task_id": task_id, "status": status, "task": task, "reviews": reviews}


@app.patch("/api/evolution/reviews/{review_id}")
def review_evolution(review_id: int, payload: ReviewRequest, user: CurrentUser) -> dict:
    result = _apply_evolution_review(review_id, payload.decision, payload.proposed_text, user["id"])
    if payload.decision == "accepted":
        credit_personal(
            int(user["id"]),
            "knowledge",
            3,
            reason_code="evolution_review",
            reason="手动审核并采纳知识修改",
            idempotency_key=f"evolution:review:{review_id}:accepted",
            reference_type="evolution_review",
            reference_id=str(review_id),
        )
    return result


@app.post("/api/evolution/reviews/{review_id}/rollback")
def rollback_auto_evolution(review_id: int, user: CurrentUser) -> dict:
    indexed_material: dict | None = None
    version: int | None = None
    with connection() as conn:
        review_row = conn.execute(
            "SELECT r.*,t.mode FROM evolution_reviews r JOIN evolution_tasks t ON t.id=r.task_id "
            "WHERE r.id=? AND t.user_id=?",
            (review_id, user["id"]),
        ).fetchone()
        if not review_row:
            raise HTTPException(404, "自动进化记录不存在")
        review = dict(review_row)
        if review["mode"] != "auto":
            raise HTTPException(422, "只有自动模式产生的版本可以在此撤销")
        if review["decision"] == "rolled_back":
            raise HTTPException(409, "该自动进化版本已经撤销")
        if review["decision"] != "accepted" or not review.get("material_id"):
            raise HTTPException(409, "该记录当前不可撤销")

        material_row = conn.execute(
            "SELECT * FROM materials WHERE id=? AND user_id=?",
            (review["material_id"], user["id"]),
        ).fetchone()
        if not material_row:
            raise HTTPException(404, "目标素材不存在")
        material = dict(material_row)
        if material["content"] != review["proposed_text"]:
            raise HTTPException(409, "素材已产生后续修改，为避免覆盖新内容，不能直接撤销此版本")

        version = int(conn.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM evolution_versions WHERE material_id=?",
            (material["id"],),
        ).fetchone()[0])
        restored = review["original_text"]
        restored_at = utcnow()
        conn.execute(
            "INSERT INTO evolution_versions(material_id,user_id,task_id,review_id,version,previous_content,new_content,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (material["id"], user["id"], review["task_id"], review_id, version, material["content"], restored, restored_at),
        )
        conn.execute(
            "UPDATE materials SET content=?,size=?,status='ready',error='' WHERE id=? AND user_id=?",
            (restored, len(restored.encode("utf-8")), material["id"], user["id"]),
        )
        conn.execute(
            "UPDATE evolution_reviews SET decision='rolled_back',applied_at=? WHERE id=?",
            (restored_at, review_id),
        )
        indexed_material = {**material, "content": restored, "size": len(restored.encode("utf-8"))}

    if indexed_material:
        es_index_document("zhiyan_materials", str(indexed_material["id"]), {
            "id": indexed_material["id"], "name": indexed_material["name"],
            "kind": indexed_material["kind"], "content": indexed_material["content"],
            "category": indexed_material["category"], "user_id": user["id"], "status": "ready",
        })
        log_event(user["id"], "evolution", "rollback", f"撤销自动知识进化：{indexed_material['name']} v{version}")
    _invalidate_user_cache(user["id"])
    result = _review_with_material(review_id, user["id"])
    if result is None:
        raise HTTPException(404, "自动进化记录不存在")
    result["version"] = version
    return result


@app.get("/api/materials/{material_id}/evolution-versions")
def material_evolution_versions(material_id: int, user: CurrentUser) -> list[dict]:
    material = row("SELECT id FROM materials WHERE id=? AND user_id=?", (material_id, user["id"]))
    if not material:
        raise HTTPException(404, "素材不存在")
    return rows(
        "SELECT id,material_id,task_id,review_id,version,previous_content,new_content,created_at "
        "FROM evolution_versions WHERE material_id=? AND user_id=? ORDER BY version DESC",
        (material_id, user["id"]),
    )


@app.websocket("/api/ws/evolution/{task_id}")
async def evolution_stream(websocket: WebSocket, task_id: int):
    await websocket.accept()
    try:
        phases = [
            (20, "知识分析 Agent", "正在扫描文本并提取主要知识点"),
            (45, "知识拓展 Agent", "正在识别缺口并补充知识"),
            (70, "知识编辑 Agent", "正在重构完整知识文档"),
            (90, "质量审核 Agent", "正在检查覆盖度、增量和事实边界"),
            (100, "系统核心", "知识进化流程已完成"),
        ]
        for progress, agent, text in phases:
            await websocket.send_json({"task_id": task_id, "progress": progress, "agent": agent, "text": text})
            await asyncio.sleep(.5)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()


@app.get("/api/games")
def game_overview(user: CurrentUser) -> dict:
    user_settings = serialize_settings(row("SELECT * FROM user_settings WHERE user_id=?", (user["id"],)))
    # Dynamic stats from actual game sessions
    total_xp = row("SELECT COALESCE(SUM(CASE WHEN correct THEN 100 ELSE 10 END), 0) xp FROM game_sessions WHERE user_id=?", (user["id"],))["xp"]
    level = calculate_level(total_xp)
    coins = wallet_snapshot("personal", int(user["id"]))["knowledge_balance"]
    props = row("SELECT COUNT(*) count FROM game_sessions WHERE user_id=? AND correct=1", (user["id"],))["count"] % 20 + 3

    # Best scores per game, plus real play statistics for the game panel.
    best = rows(
        "SELECT game, MAX(score) score, COUNT(*) attempts, COALESCE(SUM(correct),0) correct, "
        "ROUND(AVG(duration), 1) avg_duration, MAX(created_at) latest_at "
        "FROM game_sessions WHERE user_id=? GROUP BY game ORDER BY latest_at DESC",
        (user["id"],),
    )
    game_stats = rows(
        "SELECT game, COUNT(*) attempts, COALESCE(SUM(score),0) total_score, COALESCE(SUM(correct),0) correct, "
        "MAX(score) best_score, ROUND(AVG(duration), 1) avg_duration, MAX(created_at) latest_at "
        "FROM game_sessions WHERE user_id=? GROUP BY game",
        (user["id"],),
    )

    # Dynamic rank (compare against all users)
    rank_data = row("SELECT COUNT(DISTINCT user_id) total_users FROM game_sessions", ())
    total_users = rank_data["total_users"] if rank_data else 0
    user_score = row(
        "SELECT COALESCE(SUM(score),0) total FROM game_sessions WHERE user_id=?",
        (user["id"],),
    )["total"]
    better_users = row(
        "SELECT COUNT(*) count FROM (SELECT user_id, SUM(score) total FROM game_sessions GROUP BY user_id HAVING SUM(score) > ?)",
        (user_score,))["count"]
    rank = better_users + 1 if total_users > 0 else 1

    # Leaderboard (top players)
    leaderboard_data = rows(
        "SELECT u.nickname, COALESCE(SUM(gs.score),0) total_score, COALESCE(SUM(gs.correct),0) correct_count "
        "FROM users u LEFT JOIN game_sessions gs ON u.id=gs.user_id "
        "GROUP BY u.id ORDER BY total_score DESC LIMIT 5",
        ())
    leaderboard = [
        {"nickname": entry["nickname"], "score": entry["total_score"], "correct": entry["correct_count"]}
        for entry in leaderboard_data
    ]

    # User's best per game
    user_bests = {}
    for b in best:
        user_bests[b["game"]] = b["score"]

    game_materials = rows(
        "SELECT id,name,kind,category,size,SUBSTR(content,1,180) content FROM materials "
        "WHERE user_id=? AND status='ready' AND TRIM(content)<>'' ORDER BY id DESC",
        (user["id"],),
    )
    recent_packs = rows(
        "SELECT p.id,p.game,p.difficulty,p.title,p.source_mode,p.created_at,COUNT(q.id) question_count "
        "FROM game_packs p LEFT JOIN game_questions q ON q.pack_id=p.id "
        "WHERE p.user_id=? GROUP BY p.id ORDER BY p.id DESC LIMIT 6",
        (user["id"],),
    )
    session_summary = row(
        "SELECT COUNT(*) attempts, COALESCE(SUM(correct),0) correct, COALESCE(SUM(score),0) total_score, "
        "COUNT(DISTINCT game) game_count, ROUND(AVG(duration), 1) avg_duration, MAX(created_at) latest_at "
        "FROM game_sessions WHERE user_id=?",
        (user["id"],),
    ) or {}
    pack_summary = row(
        "SELECT COUNT(*) pack_count, COALESCE(SUM(CASE WHEN source_mode='deepseek-agent' THEN 1 ELSE 0 END),0) ai_pack_count "
        "FROM game_packs WHERE user_id=?",
        (user["id"],),
    ) or {}
    generated_question_count = row(
        "SELECT COUNT(*) count FROM game_questions WHERE user_id=?",
        (user["id"],),
    )["count"]
    best_score = max([int(item["score"] or 0) for item in best], default=0)
    correct_count = int(session_summary.get("correct") or 0)
    attempts = int(session_summary.get("attempts") or 0)
    pack_count = int(pack_summary.get("pack_count") or 0)
    ai_pack_count = int(pack_summary.get("ai_pack_count") or 0)
    game_count = int(session_summary.get("game_count") or 0)
    milestones = [
        {
            "id": "first_pack",
            "title": "首个题包",
            "description": "完成 1 次 Agent 游戏题包生成",
            "progress": min(pack_count, 1),
            "target": 1,
            "unlocked": pack_count >= 1,
            "tone": "cyan",
        },
        {
            "id": "ai_builder",
            "title": "AI 出题官",
            "description": "使用 DeepSeek Agent 生成 3 个题包",
            "progress": min(ai_pack_count, 3),
            "target": 3,
            "unlocked": ai_pack_count >= 3,
            "tone": "mint",
        },
        {
            "id": "first_correct",
            "title": "第一次命中",
            "description": "在任意游戏中答对 1 次",
            "progress": min(correct_count, 1),
            "target": 1,
            "unlocked": correct_count >= 1,
            "tone": "amber",
        },
        {
            "id": "accuracy_drill",
            "title": "十连训练",
            "description": "累计答对 10 次知识挑战",
            "progress": min(correct_count, 10),
            "target": 10,
            "unlocked": correct_count >= 10,
            "tone": "violet",
        },
        {
            "id": "game_explorer",
            "title": "全模式探索",
            "description": "体验 3 种知识游戏模式",
            "progress": min(game_count, 3),
            "target": 3,
            "unlocked": game_count >= 3,
            "tone": "cyan",
        },
        {
            "id": "score_hunter",
            "title": "高分猎手",
            "description": "单局得分达到 1000 分",
            "progress": min(best_score, 1000),
            "target": 1000,
            "unlocked": best_score >= 1000,
            "tone": "amber",
        },
        {
            "id": "knowledge_foundry",
            "title": "知识熔炉",
            "description": "累计生成 30 道游戏题目",
            "progress": min(int(generated_question_count or 0), 30),
            "target": 30,
            "unlocked": int(generated_question_count or 0) >= 30,
            "tone": "mint",
        },
        {
            "id": "ranked_player",
            "title": "榜上有名",
            "description": "进入游戏排行榜前 3 名",
            "progress": min(1, max(0, 4 - int(rank or 4))) if total_users else 0,
            "target": 1,
            "unlocked": total_users > 0 and rank <= 3,
            "tone": "violet",
        },
    ]

    return {
        "level": level,
        "xp": total_xp,
        "next_level_xp": calculate_xp_for_next_level(level),
        "coins": coins,
        "props": props,
        "rank": rank,
        "total_players": total_users,
        "best": best,
        "user_bests": user_bests,
        "game_stats": game_stats,
        "summary": {
            "attempts": attempts,
            "correct": correct_count,
            "total_score": int(session_summary.get("total_score") or 0),
            "game_count": game_count,
            "avg_duration": session_summary.get("avg_duration") or 0,
            "latest_at": session_summary.get("latest_at") or "",
            "pack_count": pack_count,
            "ai_pack_count": ai_pack_count,
            "generated_question_count": int(generated_question_count or 0),
        },
        "milestones": milestones,
        "leaderboard": leaderboard,
        "materials": game_materials,
        "recent_packs": recent_packs,
        "settings": user_settings,
        "games": [
            {"id": "flashcard", "title": "知识点卡片对对碰", "description": "由 Agent 提取所选文件的知识点，通过翻牌完成记忆配对。", "difficulty": "easy"},
            {"id": "monopoly", "title": "知识大富翁", "description": "2-4 名玩家轮流掷骰、问答、购买地产并争夺最终胜利。", "difficulty": "easy"},
            {"id": "matching", "title": "智识对弈 · 全自动版", "description": "Agent 自动映射知识字段，判断条目在随机维度上是相似还是不同。", "difficulty": "hard"},
        ],
    }


def _game_pack_response(pack_id: int, user_id: int) -> dict:
    pack = row("SELECT * FROM game_packs WHERE id=? AND user_id=?", (pack_id, user_id))
    if not pack:
        raise HTTPException(404, "游戏题包不存在")
    questions = rows(
        "SELECT id,game,difficulty,prompt,options,answer,topic,question_type,sequence,source_material_id "
        "FROM game_questions WHERE pack_id=? AND user_id=? ORDER BY sequence,id",
        (pack_id, user_id),
    )
    matching_terms: list[str] = []
    for question in questions:
        question["options"] = json.loads(question["options"])
        if pack["game"] == "matching":
            matching_terms.append(question["answer"])
            question["topic"] = "概念配对"
        question.pop("answer", None)
    pack["material_ids"] = json.loads(pack["material_ids"])
    pack["knowledge_points"] = json.loads(pack["knowledge_points"])
    pack["questions"] = questions
    if matching_terms:
        secrets.SystemRandom().shuffle(matching_terms)
        pack["terms"] = matching_terms
    return pack


@app.post("/api/games/generate", status_code=201)
async def generate_game_pack(payload: GameGenerateRequest, user: CurrentUser) -> dict:
    game_settings = row("SELECT gamified_review FROM user_settings WHERE user_id=?", (user["id"],))
    if game_settings and not bool(game_settings["gamified_review"]):
        raise HTTPException(409, "游戏化复习已在系统设置中关闭，请先启用后再生成题包")
    material_ids = list(dict.fromkeys(payload.material_ids))
    placeholders = ",".join("?" for _ in material_ids)
    selected = rows(
        f"SELECT id,name,kind,category,content FROM materials WHERE user_id=? AND id IN ({placeholders})",
        (user["id"], *material_ids),
    )
    selected_by_id = {item["id"]: item for item in selected}
    if len(selected_by_id) != len(material_ids):
        raise HTTPException(404, "部分知识库文件不存在或无权访问")
    materials = [selected_by_id[material_id] for material_id in material_ids]
    invalid = [item["name"] for item in materials if not str(item["content"]).strip()]
    if invalid:
        raise HTTPException(422, f"以下文件没有可生成题目的正文：{'、'.join(invalid)}")

    try:
        points, source_mode, agent_note = await agent_extract_knowledge(
            materials,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            proxy_url=settings.deepseek_proxy_url,
            requested_count=18 if payload.game == "flashcard" else 10,
        )
        generated = build_game_questions(payload.game, payload.difficulty, points)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    title = f"{GAME_TITLES[payload.game]} · {' / '.join(item['name'] for item in materials[:2])}"
    with connection() as conn:
        pack_id = int(conn.execute(
            "INSERT INTO game_packs(user_id,game,difficulty,title,material_ids,knowledge_points,source_mode,agent_note,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                user["id"], payload.game, payload.difficulty, title[:200],
                json.dumps(material_ids), json.dumps(points, ensure_ascii=False),
                source_mode, agent_note, utcnow(),
            ),
        ).lastrowid)
        if payload.game == "matching":
            vector_engine = index_matching_points(points, pack_id, user["id"])
            conn.execute(
                "UPDATE game_packs SET knowledge_points=?, agent_note=? WHERE id=?",
                (
                    json.dumps(points, ensure_ascii=False),
                    f"{agent_note} 比对引擎：{vector_engine}。",
                    pack_id,
                ),
            )
        for question in generated:
            conn.execute(
                "INSERT INTO game_questions(user_id,pack_id,source_material_id,game,difficulty,prompt,options,answer,"
                "explanation,topic,question_type,sequence,verified) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (
                    user["id"], pack_id, question["source_material_id"], question["game"],
                    question["difficulty"], question["prompt"], json.dumps(question["options"], ensure_ascii=False),
                    question["answer"], question["explanation"], question["topic"],
                    question["question_type"], question["sequence"],
                ),
            )
    log_event(user["id"], "game", "generate", f"{payload.game}：从 {len(materials)} 个素材生成题包 #{pack_id}")
    return _game_pack_response(pack_id, user["id"])


@app.post("/api/games/matching/round")
def generate_matching_round(payload: MatchingRoundRequest, user: CurrentUser) -> dict:
    pack = row("SELECT id,game,knowledge_points FROM game_packs WHERE id=? AND user_id=?", (payload.pack_id, user["id"]))
    if not pack or pack["game"] != "matching":
        raise HTTPException(404, "智识对弈题包不存在或无权访问")
    points = json.loads(pack["knowledge_points"])
    try:
        result = matching_round(points, payload.pack_id, user["id"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result["round"] = payload.round
    return result


@app.get("/api/games/packs/{pack_id}")
def get_game_pack(pack_id: int, user: CurrentUser) -> dict:
    return _game_pack_response(pack_id, user["id"])


@app.get("/api/games/{game}/question")
def game_question(game: str, user: CurrentUser, difficulty: str = "medium") -> dict:
    question = row(
        "SELECT id,game,difficulty,prompt,options,topic,verified FROM game_questions WHERE game=? ORDER BY CASE WHEN difficulty=? THEN 0 ELSE 1 END,RANDOM() LIMIT 1",
        (game, difficulty))
    if not question:
        raise HTTPException(404, "暂无可用题目")
    question["options"] = json.loads(question["options"])
    return question


@app.post("/api/games/flashcard/complete")
def complete_memory_game(payload: MemoryGameCompleteRequest, user: CurrentUser) -> dict:
    pair_count = 8 if payload.difficulty == "easy" else 18
    minimum_moves = pair_count
    if payload.moves < minimum_moves:
        raise HTTPException(422, "完成步数小于理论最少步数")
    if payload.pack_id is not None:
        pack = row(
            "SELECT id FROM game_packs WHERE id=? AND user_id=? AND game='flashcard'",
            (payload.pack_id, user["id"]),
        )
        if not pack:
            raise HTTPException(404, "知识点题包不存在或无权访问")
    base_score = 8_000 if payload.difficulty == "easy" else 20_000
    score = max(500, base_score - (payload.moves - minimum_moves) * 90 - payload.duration * 8)
    xp = 180 if payload.difficulty == "easy" else 360
    session_id = execute(
        "INSERT INTO game_sessions(user_id,game,pack_id,question_id,score,correct,duration,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (user["id"], "flashcard", payload.pack_id, None, score, 1, payload.duration, utcnow()),
    )
    credit_personal(
        int(user["id"]),
        "knowledge",
        8 if payload.difficulty == "hard" else 5,
        reason_code="game_complete",
        reason="完成记忆游戏",
        idempotency_key=f"game:complete:{session_id}:knowledge",
        reference_type="game_session",
        reference_id=str(session_id),
    )
    if payload.difficulty == "hard":
        credit_personal(
            int(user["id"]),
            "truth",
            1,
            reason_code="game_boss_reward",
            reason="完成困难记忆挑战奖励",
            idempotency_key=f"game:complete:{session_id}:truth",
            reference_type="game_session",
            reference_id=str(session_id),
        )
    _sync_graph_mastery(user["id"])
    redis_cache_delete(f"dashboard:{user['id']}")
    log_event(user["id"], "game", "memory_complete", f"{payload.difficulty}：{payload.moves} 步，{payload.duration} 秒")
    rabbitmq_publish("zhiyan.game.scores", {
        "user_id": user["id"], "game": "flashcard", "score": score,
        "correct": True, "timestamp": utcnow(),
    })
    return {"score": score, "xp": xp, "moves": payload.moves, "duration": payload.duration}


@app.post("/api/games/{game}/submit")
def game_submit(game: str, payload: GameSubmitRequest, user: CurrentUser) -> dict:
    question = row("SELECT * FROM game_questions WHERE id=? AND game=?", (payload.question_id, game))
    if not question or (question.get("user_id") is not None and question["user_id"] != user["id"]):
        raise HTTPException(404, "题目不存在")
    if payload.pack_id is not None and question.get("pack_id") != payload.pack_id:
        raise HTTPException(422, "题目不属于当前游戏题包")
    correct = payload.answer == question["answer"]
    multiplier = {"easy": 1.0, "medium": 1.25, "hard": 1.5}.get(question["difficulty"], 1.0)
    score = round(max(100, 1000 - payload.duration * 12) * multiplier) if correct else 0
    session_id = execute(
        "INSERT INTO game_sessions(user_id,game,pack_id,question_id,score,correct,duration,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (user["id"], game, question.get("pack_id"), question["id"], score, int(correct), payload.duration, utcnow()),
    )
    if correct:
        knowledge_reward = min(20, max(1, round(score / 250)))
        credit_personal(
            int(user["id"]),
            "knowledge",
            knowledge_reward,
            reason_code="game_answer",
            reason="答题正确奖励",
            idempotency_key=f"game:answer:{session_id}:knowledge",
            reference_type="game_session",
            reference_id=str(session_id),
        )
        if question["difficulty"] == "hard" and score >= 1200:
            credit_personal(
                int(user["id"]),
                "truth",
                1,
                reason_code="game_boss_reward",
                reason="困难题高分奖励真知晶",
                idempotency_key=f"game:answer:{session_id}:truth",
                reference_type="game_session",
                reference_id=str(session_id),
            )
    # Recalculate mastery from the complete persisted attempt history so the
    # displayed value reflects accuracy and exposure instead of a fixed delta.
    _sync_graph_mastery(user["id"])
    log_event(user["id"], "game", "answer", f"{game}: {'正确' if correct else '错误'}")

    # Invalidate dashboard cache in Redis
    redis_cache_delete(f"dashboard:{user['id']}")

    # Publish score to RabbitMQ for leaderboard updates
    rabbitmq_publish("zhiyan.game.scores", {
        "user_id": user["id"],
        "game": game,
        "score": score,
        "correct": correct,
        "timestamp": utcnow(),
    })

    return {
        "correct": correct, "answer": question["answer"], "explanation": question["explanation"],
        "score": score, "xp": 100 if correct else 10, "topic": question["topic"],
    }


def _graph_term_key(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").lower())


_GRAPH_GENERIC_TERMS = frozenset({
    "例如", "比如", "如", "包括", "包含", "相关", "相关内容", "知识点", "概念", "说明", "信息", "内容",
    "其他", "其中", "一种", "一个", "这一点", "以上", "如下", "定义", "介绍", "应用", "方法",
    "安装", "下载", "点击", "进入", "运行", "配置", "创建", "步骤", "命令", "示例", "注意",
})
_GRAPH_FUNCTION_WORDS = ("在于", "由于", "因为", "所以", "因此", "能够", "可以", "用于", "通过", "以及", "或者", "与", "和", "及", "的", "地", "得")
_GRAPH_RELATION_STOPWORDS = frozenset({
    "通过", "可以", "用于", "知识", "内容", "关联", "联要", "要点", "角度", "扩展", "理解", "相关",
    "以及", "例如", "比如", "描述", "决定", "能力", "其中", "主要", "核心", "说明", "定义", "介绍",
})


def _graph_display_length(value: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", str(value or "")))


def _graph_is_noise_term_legacy(value: str) -> bool:
    """Reject document artifacts and instruction fragments as graph labels."""
    term = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n，。；：:、-_.!?！？")
    key = _graph_term_key(term)
    generic_keys = {_graph_term_key(item) for item in _GRAPH_GENERIC_TERMS}
    if not term or len(key) < 2 or key in generic_keys:
        return True
    if _graph_display_length(term) > 5:
        return True
    if any(word in term for word in _GRAPH_FUNCTION_WORDS):
        return True
    if re.search(r"(?:在于|由于|因为|所以|因此|能够|可以|用于|通过|以及|或者)(?:$|[，。；：:])", term):
        return True
    if re.search(r"(?:的|地|得|呢|吗|吧|啊|了)$", term):
        return True
    if any(key.startswith(item) and len(key) <= len(item) + 8 for item in generic_keys):
        return True
    # Screenshot/file labels and generated timestamps (QQ20260729-163303,
    # IMG_20260729_163303, UUID-like values) have no semantic value.
    if re.fullmatch(r"(?:qq|img|image|screenshot|截图|照片|录音|录像)?\d{6,}(?:[-_]\d{3,})?", key):
        return True
    if re.search(r"(?:png|jpg|jpeg|gif|webp|mp4|mov|pdf|docx?)$", key):
        return True
    if re.fullmatch(r"[0-9a-f]{16,}", key):
        return True
    digit_count = sum(char.isdigit() for char in term)
    if digit_count >= 6 and digit_count >= len(re.sub(r"\s+", "", term)) * 0.35:
        return True
    return False


def _graph_clean_term_legacy(raw_term: str, definition: str = "") -> str:
    """Return a concrete graph label, replacing generic Agent labels when possible."""
    raw_value = re.sub(r"\s+", " ", str(raw_term or "")).strip()
    if re.match(r"^(安装|下载|点击|进入|运行|配置|创建|执行|打开|选择)\s*", raw_value):
        return ""
    term = raw_value.strip(" \t\r\n，。；：:、-_.!?！？")[:80]
    key = _graph_term_key(term)
    generic = key in {_graph_term_key(item) for item in _GRAPH_GENERIC_TERMS}
    generic_prefix = any(key.startswith(_graph_term_key(item)) and len(key) <= len(_graph_term_key(item)) + 8 for item in _GRAPH_GENERIC_TERMS)
    if not term or generic or generic_prefix or len(key) < 2 or _graph_is_noise_term(term):
        text = re.sub(r"\s+", " ", str(definition or "")).strip()
        candidate = re.split(r"是指|是一种|是|通过|用于|可以|能够|包括|包含|在于|由于|因为|所以|因此|决定|提升|优化|描述|支持|形成|：|:|，|。|；|·|\.|与|和|及|以及|或者", text, maxsplit=1)[0]
        candidate = re.sub(r"^(例如|比如|如|其中|关于|对于|所谓的|安装|下载|点击|配置)", "", candidate).strip(" \t，。；、")
        candidate_key = _graph_term_key(candidate)
        if candidate and len(candidate_key) >= 2 and not _graph_is_noise_term(candidate):
            term = candidate[:80]
    if _graph_is_noise_term(term):
        return ""
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", term):
        return ""
    return term


_GRAPH_CANONICAL_REWRITES = (
    ("TypeScript", "TS"),
    ("JavaScript", "JS"),
    ("Javascript", "JS"),
    ("Node.js", "Node"),
    ("NodeJS", "Node"),
    ("tsconfig.json", "配置"),
    ("静态类型校验", "静态类型"),
    ("类型校验", "类型安全"),
    ("类型推断机制", "类型推断"),
    ("面向对象语法", "面向对象"),
    ("变量定义示例", "变量定义"),
    ("变量定义方式", "变量定义"),
    ("特有类型应用", "特有类型"),
    ("渐进式迁移", "渐进迁移"),
    ("类型安全层级", "类型安全"),
    ("运行环境搭建", "运行环境"),
)
_GRAPH_DISALLOWED_LABELS = frozenset({
    "例如", "比如", "此外", "另外", "同时", "其中", "其", "该", "这", "此", "本文",
    "核心", "主要", "价值", "特性", "特点", "概念", "知识点", "说明", "信息", "内容", "介绍", "应用",
})


def _graph_is_noise_term(value: str) -> bool:
    """Apply the final graph-label contract: short nouns only."""
    term = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n-—:：,，。;；、.!?！？_ ")
    key = _graph_term_key(term)
    if not term or key in {_graph_term_key(item) for item in _GRAPH_DISALLOWED_LABELS} or term.startswith(("其", "该", "这", "此", "本文")):
        return True
    if _graph_display_length(term) > 5:
        return True
    if any(word in term for word in ("在于", "由于", "因为", "所以", "因此", "能够", "可以", "用于", "通过", "以及", "或者", "与", "和", "及", "的", "地", "得")):
        return True
    if re.fullmatch(r"(?:qq|img|image|screenshot)?\d{6,}(?:[-_]\d{3,})?", key) or re.fullmatch(r"[0-9a-f]{16,}", key):
        return True
    if re.search(r"(?:png|jpg|jpeg|gif|webp|mp4|mov|pdf|docx?)$", key):
        return True
    return False


def _graph_clean_term(raw_term: str, definition: str = "") -> str:
    """Canonicalize Agent labels before they become graph nodes."""
    term = re.sub(r"[*_`>#\[\](){}]", "", str(raw_term or ""))
    term = re.sub(r"\s+", " ", term).strip(" \t\r\n-—:：,，。;；、.!?！？")
    for source, target in _GRAPH_CANONICAL_REWRITES:
        if term.lower().startswith(source.lower()):
            term = target + term[len(source):]
            break
    term = re.sub(r"(?:基础知识与特点|基础知识|的核心定位|核心定位|的局限性|局限性|语法的完善|的完善|的特点|的必要性|的重要性|层级|策略|搭建|应用)$", "", term)
    term = re.split(r"(?:与|和|及|以及|或者|是指|包括|包含|通过|用于|能够|可以|决定|提升|优化|描述|支持|形成|在于|由于|因为|所以|因此|：|:|、|·|\.)", term, maxsplit=1)[0]
    term = term.strip(" \t\r\n-—:：,，。;；、.!?！？")
    if not _graph_is_noise_term(term):
        return term
    # Recover a short concept from a verbose Agent label/definition.
    text = re.sub(r"\s+", " ", str(definition or "")).strip()
    candidate = re.split(r"(?:是指|包括|包含|通过|用于|能够|可以|在于|由于|因为|所以|因此|：|:|、|\.)", text, maxsplit=1)[0]
    for source, target in _GRAPH_CANONICAL_REWRITES:
        if candidate.lower().startswith(source.lower()):
            candidate = target + candidate[len(source):]
            break
    candidate = candidate.strip(" \t\r\n-—:：,，。;；、.!?！？")
    return candidate if not _graph_is_noise_term(candidate) else ""


def _graph_relation_tokens(label: str, summary: str) -> set[str]:
    text = f"{label} {summary}".lower()
    tokens = set(re.findall(r"[a-z0-9]{2,}", text))
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        tokens.update(segment[index:index + 2] for index in range(len(segment) - 1))
    return {token for token in tokens if token not in _GRAPH_RELATION_STOPWORDS and len(token) >= 2}


def _graph_relation_weight(left: dict, right: dict) -> float:
    shared = _graph_relation_tokens(left.get("label", ""), left.get("summary", "")) & _graph_relation_tokens(right.get("label", ""), right.get("summary", ""))
    if not shared:
        return 0.0
    weight = 0.42 + min(0.36, len(shared) * 0.08)
    if left.get("source_material_id") == right.get("source_material_id"):
        weight += 0.08
    if left.get("category") == right.get("category"):
        weight += 0.06
    return round(min(1.0, weight), 3)


def _graph_filter_points(points: list[dict], materials: list[dict]) -> list[dict]:
    material_ids = {int(item["id"]) for item in materials}
    filtered: list[dict] = []
    seen: set[str] = set()
    for point in points:
        if not isinstance(point, dict):
            continue
        term = _graph_clean_term(str(point.get("term", "")), str(point.get("definition", "")))
        try:
            source_id = int(point.get("source_material_id"))
        except (TypeError, ValueError):
            source_id = int(materials[0]["id"])
        if source_id not in material_ids or not term:
            continue
        key = _graph_term_key(term)
        if key in seen:
            continue
        seen.add(key)
        filtered.append({**point, "term": term, "source_material_id": source_id})
    return filtered


def _graph_materials(user_id: int, material_ids: list[int] | None = None) -> list[dict]:
    params: tuple = (user_id,)
    query = "SELECT id,name,category,content FROM materials WHERE user_id=? AND status='ready' AND TRIM(content)<>''"
    if material_ids:
        placeholders = ",".join("?" for _ in material_ids)
        query += f" AND id IN ({placeholders})"
        params = (user_id, *material_ids)
    return rows(query, params)


def _graph_learning_sessions(user_id: int) -> list[dict]:
    """Return learning events that can be attributed to graph concepts."""
    return rows(
        "SELECT gs.game,gs.correct,gs.created_at,gs.pack_id,"
        "q.topic,q.prompt,q.answer,q.explanation,q.source_material_id,"
        "p.material_ids "
        "FROM game_sessions gs "
        "LEFT JOIN game_questions q ON q.id=gs.question_id "
        "LEFT JOIN game_packs p ON p.id=gs.pack_id "
        "WHERE gs.user_id=? ORDER BY gs.created_at DESC",
        (user_id,),
    )


def _graph_review_events(user_id: int) -> list[dict]:
    """Return active-recall events recorded inside the knowledge graph."""
    return rows(
        "SELECT node_id,result,created_at FROM graph_reviews WHERE user_id=? ORDER BY created_at DESC",
        (user_id,),
    )


def _graph_session_matches(node: dict, session: dict) -> bool:
    """Match a learning event conservatively to one graph node."""
    label = str(node.get("label") or "").strip().lower()
    if not label:
        return False
    searchable = " ".join(
        str(session.get(field) or "")
        for field in ("topic", "prompt", "answer", "explanation")
    ).lower()
    aliases = {"ts": "typescript", "js": "javascript", "node": "node.js nodejs"}
    search_terms = [label, *aliases.get(label, "").split()]
    if any(term and term in searchable for term in search_terms):
        return True
    # Flashcard completion has no question_id. Its pack still identifies the
    # source materials, so attribute the event to nodes from those materials.
    if session.get("game") == "flashcard" and node.get("source_material_id"):
        try:
            material_ids = json.loads(session.get("material_ids") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            material_ids = []
        return int(node["source_material_id"]) in {int(item) for item in material_ids if str(item).isdigit()}
    return False


def _graph_node_activity(node: dict, sessions: list[dict]) -> list[dict]:
    return [session for session in sessions if _graph_session_matches(node, session)]


def _graph_mastery_value(correct: int, total: int) -> int:
    """Convert observed attempts into a bounded, non-static mastery score."""
    if total <= 0:
        return 0
    accuracy = max(0.0, min(1.0, correct / total))
    exposure = min(30.0, total * 5.0)
    return max(0, min(100, round(accuracy * 70.0 + exposure)))


def _sync_graph_mastery(user_id: int) -> None:
    """Recalculate every node from persisted learning events."""
    nodes = rows(
        "SELECT id,label,category,summary,source_material_id FROM graph_nodes WHERE user_id=?",
        (user_id,),
    )
    if not nodes:
        return
    sessions = _graph_learning_sessions(user_id)
    review_events: dict[int, list[dict]] = {}
    for event in _graph_review_events(user_id):
        review_events.setdefault(int(event["node_id"]), []).append(event)
    updates: list[tuple[int, int]] = []
    for node in nodes:
        matched = _graph_node_activity(node, sessions)
        reviews = review_events.get(int(node["id"]), [])
        correct = sum(int(session.get("correct") or 0) for session in matched)
        correct += sum(1 for event in reviews if event.get("result") == "known")
        total = len(matched) + len(reviews)
        mastery = _graph_mastery_value(correct, total)
        updates.append((mastery, int(node["id"])))
    with connection() as conn:
        conn.executemany("UPDATE graph_nodes SET mastery=? WHERE id=? AND user_id=?", [(mastery, node_id, user_id) for mastery, node_id in updates])


async def _agent_graph_points(materials: list[dict], node_limit: int) -> tuple[list[dict], str, str]:
    requested_count = max(8, int(node_limit or 80))
    points, source_mode, note = await agent_extract_knowledge(
        materials,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        proxy_url=settings.deepseek_proxy_url,
        requested_count=requested_count,
        purpose="graph",
    )
    filtered = _graph_filter_points(points, materials)
    if len(filtered) < 2:
        raise HTTPException(422, "标准知识图谱 Agent 提取的有效节点不足 2 个，未启用本地降级")
    return filtered, source_mode, note


def _graph_rebuild(user_id: int, material_ids: list[int] | None = None, points: list[dict] | None = None, node_limit: int | None = None) -> dict:
    """Rebuild a user's graph from ready materials and keep learning progress."""
    materials = _graph_materials(user_id, material_ids)
    if not materials:
        raise HTTPException(422, "没有可用于构建知识图谱的已入库素材")

    existing = {
        _graph_term_key(item["label"]): int(item["mastery"])
        for item in rows("SELECT label,mastery FROM graph_nodes WHERE user_id=?", (user_id,))
    }
    if points is None:
        raise HTTPException(409, "标准知识图谱必须先通过 Agent 提取节点，再执行图谱写入")
    node_limit = max(8, int(node_limit or len(points or [])))
    if points is None:
        raise HTTPException(409, "标准知识图谱必须先通过 Agent 提取节点，再执行图谱写入")
    if not points:
        raise HTTPException(422, "标准知识图谱 Agent 没有返回有效节点")
    if False:
        # Very short notes may not contain a sentence boundary. Keep them in
        # the graph as material-level concepts instead of silently dropping
        # the source from the user's network.
        points = _graph_filter_points([{
            "term": str(material["name"]).rsplit(".", 1)[0][:80] or "未命名知识点",
            "definition": str(material.get("content") or material["name"])[:500],
            "expanded_text": str(material.get("content") or material["name"])[:900],
            "source_material_id": int(material["id"]),
        } for material in materials], materials)
    material_by_id = {int(item["id"]): item for item in materials}
    nodes: list[dict] = []
    seen: set[str] = set()
    for point in points:
        if len(nodes) >= node_limit:
            break
        label = str(point.get("term", "")).strip()[:120]
        key = _graph_term_key(label)
        if not key or key in seen:
            continue
        seen.add(key)
        material = material_by_id.get(int(point.get("source_material_id") or 0), materials[0])
        # Existing progress is retained; new concepts start at a visible baseline.
        mastery = max(0, min(100, existing.get(key, 35)))
        nodes.append({
            "label": label,
            "category": str(material.get("category") or "未分类")[:80],
            "mastery": mastery,
            "summary": str(point.get("expanded_text") or point.get("definition") or "").strip()[:1000],
            "source_material_id": int(material["id"]),
        })

    with connection() as conn:
        conn.execute("DELETE FROM graph_edges WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM graph_nodes WHERE user_id=?", (user_id,))
        node_ids: list[int] = []
        for item in nodes:
            node_ids.append(int(conn.execute(
                "INSERT INTO graph_nodes(user_id,label,category,mastery,summary,source_material_id) VALUES(?,?,?,?,?,?)",
                (user_id, item["label"], item["category"], item["mastery"], item["summary"], item["source_material_id"]),
            ).lastrowid))
        for left_index, left in enumerate(nodes):
            for right_index in range(left_index + 1, len(nodes)):
                right = nodes[right_index]
                # A shared source/category alone is not a relationship. Require
                # at least one meaningful semantic token in both nodes.
                weight = _graph_relation_weight(left, right)
                if weight > 0:
                    conn.execute(
                        "INSERT INTO graph_edges(user_id,source,target,weight) VALUES(?,?,?,?)",
                        (user_id, node_ids[left_index], node_ids[right_index], weight),
                    )

    log_event(user_id, "graph", "rebuild", f"从 {len(materials)} 个素材重建 {len(nodes)} 个知识节点")
    return {"material_count": len(materials), "node_count": len(nodes)}


def _graph_payload(user_id: int, category: str | None = None) -> dict:
    _sync_graph_mastery(user_id)
    raw_nodes = rows("SELECT id,label,summary FROM graph_nodes WHERE user_id=?", (user_id,))
    raw_node_map = {int(item["id"]): item for item in raw_nodes}
    raw_edges = rows("SELECT source,target FROM graph_edges WHERE user_id=?", (user_id,))
    invalid_edge = False
    for edge in raw_edges:
        source = raw_node_map.get(int(edge["source"]))
        target = raw_node_map.get(int(edge["target"]))
        if source and target and _graph_relation_weight(source, target) <= 0:
            invalid_edge = True
            break
    if any(_graph_is_noise_term(str(item.get("label", ""))) for item in raw_nodes) or invalid_edge:
        # Clean graph databases created before the stricter core-term rules.
        # This keeps old users from having to manually regenerate their graph.
        _safe_graph_refresh(user_id)
        _sync_graph_mastery(user_id)
    nodes_data = rows(
        "SELECT n.*,m.name source_material_name,m.kind source_material_kind "
        "FROM graph_nodes n LEFT JOIN materials m ON m.id=n.source_material_id "
        "WHERE n.user_id=?" + (" AND n.category=?" if category else ""),
        (user_id, category) if category else (user_id,),
    )
    activity_sessions = _graph_learning_sessions(user_id)
    review_events: dict[int, list[dict]] = {}
    for event in _graph_review_events(user_id):
        review_events.setdefault(int(event["node_id"]), []).append(event)
    for item in nodes_data:
        matched = _graph_node_activity(item, activity_sessions)
        reviews = review_events.get(int(item["id"]), [])
        item["learning_attempts"] = len(matched) + len(reviews)
        item["correct_attempts"] = sum(int(session.get("correct") or 0) for session in matched)
        item["correct_attempts"] += sum(1 for event in reviews if event.get("result") == "known")
        item["accuracy"] = round(item["correct_attempts"] / item["learning_attempts"] * 100) if item["learning_attempts"] else 0
    ids = {item["id"] for item in nodes_data}
    edges_data = [edge for edge in rows("SELECT source,target,weight FROM graph_edges WHERE user_id=?", (user_id,)) if edge["source"] in ids and edge["target"] in ids]
    cat_rows = rows("SELECT DISTINCT category FROM graph_nodes WHERE user_id=? ORDER BY category", (user_id,))
    categories = [item["category"] for item in cat_rows]
    total = len(nodes_data)
    mastered = sum(1 for item in nodes_data if int(item.get("mastery") or 0) >= 80)
    return {
        "nodes": nodes_data,
        "edges": edges_data,
        "categories": categories,
        "stats": {
            "nodes": total,
            "edges": len(edges_data),
            "mastered": mastered,
            "average_mastery": round(sum(int(item.get("mastery") or 0) for item in nodes_data) / max(1, total)),
        },
    }


def _safe_graph_refresh(user_id: int, material_ids: list[int] | None = None) -> None:
    """Refresh graph data as a best-effort side effect of material changes."""
    log_event(user_id, "graph", "rebuild_required", "素材已变更，请通过标准 /api/graph/rebuild Agent 工作流刷新知识图谱")
    return
    try:
        # Always rebuild from the full ready library. The optional IDs are
        # retained for API compatibility but must not hide unrelated nodes.
        _graph_rebuild(user_id)
    except Exception as exc:
        log_event(user_id, "graph", "rebuild_failed", str(exc)[:160])


@app.get("/api/graph")
def graph(user: CurrentUser, category: str | None = None) -> dict:
    return _graph_payload(user["id"], category)


@app.post("/api/graph/export-authorize")
def authorize_graph_export(user: CurrentUser) -> dict:
    if not row("SELECT id FROM graph_nodes WHERE user_id=? LIMIT 1", (user["id"],)):
        raise HTTPException(422, "当前还没有可导出的知识图谱")
    debit_personal(
        int(user["id"]),
        "truth",
        2,
        reason_code="hd_graph_export",
        reason="导出高清知识图谱",
        idempotency_key=f"graph:export:{user['id']}:{uuid.uuid4().hex}",
        reference_type="graph",
        reference_id=str(user["id"]),
    )
    return {"authorized": True, "cost": 2, "currency": "truth", "wallet": wallet_snapshot("personal", int(user["id"]))}


@app.post("/api/graph/rebuild")
async def rebuild_graph(payload: GraphRebuildRequest, user: CurrentUser) -> dict:
    material_ids = list(dict.fromkeys(payload.material_ids)) or None
    materials = _graph_materials(user["id"], material_ids)
    if not materials:
        raise HTTPException(422, "没有可用于构建知识图谱的已入库素材")
    points, source_mode, agent_note = await _agent_graph_points(materials, payload.node_limit)
    result = _graph_rebuild(user["id"], material_ids, points, payload.node_limit)
    return {**result, "source_mode": source_mode, "agent_note": agent_note, **_graph_payload(user["id"])}


@app.post("/api/graph/nodes/{node_id}/review")
def graph_node_review(node_id: int, payload: GraphReviewRequest, user: CurrentUser) -> dict:
    node = row("SELECT id,label FROM graph_nodes WHERE id=? AND user_id=?", (node_id, user["id"]))
    if not node:
        raise HTTPException(404, "Graph node not found")
    execute(
        "INSERT INTO graph_reviews(user_id,node_id,result,created_at) VALUES(?,?,?,?)",
        (user["id"], node_id, payload.result, utcnow()),
    )
    _sync_graph_mastery(user["id"])
    log_event(user["id"], "graph", "review", f"{node['label']}: {payload.result}")
    return graph_node_detail(node_id, user)


@app.get("/api/graph/nodes/{node_id}")
def graph_node_detail(node_id: int, user: CurrentUser) -> dict:
    node = row(
        "SELECT n.*,m.name source_material_name,m.kind source_material_kind,m.category source_material_category "
        "FROM graph_nodes n LEFT JOIN materials m ON m.id=n.source_material_id "
        "WHERE n.id=? AND n.user_id=?",
        (node_id, user["id"]),
    )
    if not node:
        raise HTTPException(404, "知识节点不存在")
    related = rows(
        "SELECT n.id,n.label,n.category,n.mastery,n.summary,e.weight FROM graph_edges e "
        "JOIN graph_nodes n ON n.id=CASE WHEN e.source=? THEN e.target ELSE e.source END "
        "WHERE e.user_id=? AND (e.source=? OR e.target=?) ORDER BY e.weight DESC LIMIT 12",
        (node_id, user["id"], node_id, node_id),
    )
    materials = rows(
        "SELECT id,name,kind,category,status,SUBSTR(content,1,280) excerpt FROM materials "
        "WHERE user_id=? AND (id=? OR category=? OR content LIKE ? OR name LIKE ?) ORDER BY id DESC LIMIT 8",
        (user["id"], node.get("source_material_id") or 0, node.get("category") or "", f"%{node['label']}%", f"%{node['label']}%"),
    )
    activity = rows(
        "SELECT gs.game,gs.correct,gs.score,gs.duration,gs.created_at FROM game_sessions gs "
        "LEFT JOIN game_questions q ON q.id=gs.question_id WHERE gs.user_id=? AND "
        "(q.topic=? OR q.prompt LIKE ?) ORDER BY gs.created_at DESC LIMIT 8",
        (user["id"], node.get("label") or "", f"%{node.get('label') or ''}%"),
    )
    reviews = rows(
        "SELECT result,created_at FROM graph_reviews WHERE user_id=? AND node_id=? ORDER BY created_at DESC LIMIT 8",
        (user["id"], node_id),
    )
    all_activity = _graph_node_activity(node, _graph_learning_sessions(user["id"]))
    review_correct = sum(1 for item in reviews if item.get("result") == "known")
    node["learning_attempts"] = len(all_activity) + len(reviews)
    node["correct_attempts"] = sum(int(item.get("correct") or 0) for item in all_activity) + review_correct
    node["accuracy"] = round(node["correct_attempts"] / node["learning_attempts"] * 100) if node["learning_attempts"] else 0
    return {"node": node, "related": related, "materials": materials, "activity": activity, "reviews": reviews}


@app.get("/api/profile")
def profile(user: CurrentUser) -> dict:
    metrics = _user_metrics(user["id"])
    count = metrics["material_count"]
    total_xp = row("SELECT COALESCE(SUM(CASE WHEN correct THEN 100 ELSE 10 END), 0) xp FROM game_sessions WHERE user_id=?", (user["id"],))["xp"]
    level = calculate_level(total_xp)
    achievement_items = _achievement_items(metrics)
    achievements = sum(1 for item in achievement_items if item["unlocked"])

    # Dynamic titles based on level
    if level >= 40:
        title = "知识宗师"
        level_name = f"大宗师 III"
    elif level >= 25:
        title = "知识架构师"
        level_name = f"大宗师 II"
    elif level >= 15:
        title = "知识探索者"
        level_name = "大宗师 I"
    elif level >= 5:
        title = "知识学徒"
        level_name = "修行者"
    else:
        title = "知识新手"
        level_name = "初学者"

    shares_data = rows("SELECT id,name,description,scope,expires_at,visits,status,created_at FROM shares WHERE user_id=? ORDER BY created_at DESC", (user["id"],))

    return {
        **user,
        "title": title,
        "location": "知识工坊",
        "bio": f"在知衍 AI 工作坊中已积累 {count} 条知识素材，完成 {metrics['game_sessions']} 次学习挑战。",
        "level": level_name,
        "xp": total_xp,
        "next_xp": calculate_xp_for_next_level(level),
        "knowledge_total": count,
        "achievements": achievements,
        "total_achievements": len(achievement_items),
        "achievement_items": achievement_items,
        "shares": shares_data,
    }


@app.post("/api/shares", status_code=201)
def create_share(payload: ShareRequest, user: CurrentUser) -> dict:
    share_id = uuid.uuid4().hex[:12]
    expires_at = (datetime.now(timezone.utc) + timedelta(days=payload.expires_days)).isoformat() if payload.expires_days else None
    password_hash = bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode() if payload.password else None
    charge_key = ""
    if payload.expires_days is None:
        charge_key = f"share:permanent:{user['id']}:{uuid.uuid4().hex}"
        debit_personal(
            int(user["id"]),
            "truth",
            1,
            reason_code="permanent_share",
            reason="创建永久个人分享链接",
            idempotency_key=charge_key,
            reference_type="share",
            reference_id=share_id,
        )
    try:
        execute("INSERT INTO shares(id,user_id,name,description,scope,expires_at,password_hash,created_at) VALUES(?,?,?,?,?,?,?,?)", (share_id, user["id"], payload.name, payload.description, payload.scope, expires_at, password_hash, utcnow()))
    except Exception:
        if charge_key:
            credit_personal(
                int(user["id"]),
                "truth",
                1,
                reason_code="share_refund",
                reason="永久分享创建失败，退回真知晶",
                idempotency_key=f"{charge_key}:refund",
                reference_type="share",
                reference_id=share_id,
            )
        raise
    log_event(user["id"], "share", "create", payload.name)
    return row("SELECT id,name,description,scope,expires_at,visits,status,created_at FROM shares WHERE id=?", (share_id,))


@app.delete("/api/shares/{share_id}", status_code=204, response_class=Response)
def revoke_share(share_id: str, user: CurrentUser):
    if not row("SELECT id FROM shares WHERE id=? AND user_id=?", (share_id, user["id"])):
        raise HTTPException(404, "分享不存在")
    execute("UPDATE shares SET status='revoked' WHERE id=?", (share_id,))
    return Response(status_code=204)


@app.get("/api/share/{share_id}")
def public_share(share_id: str, request: Request, password: str | None = None) -> dict:
    share = row("SELECT * FROM shares WHERE id=?", (share_id,))
    if not share or share["status"] != "active":
        raise HTTPException(404, "该分享已关闭")
    if share["expires_at"] and datetime.fromisoformat(share["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(410, "该分享已过期")
    if share["password_hash"] and (not password or not bcrypt.checkpw(password.encode(), share["password_hash"].encode())):
        raise HTTPException(401, "需要访问密码")
    execute("UPDATE shares SET visits=visits+1 WHERE id=?", (share_id,))
    visitor_ip = (request.client.host if request.client else "anonymous").strip()
    visitor_fingerprint = hashlib.sha256(visitor_ip.encode("utf-8")).hexdigest()[:24]
    credit_personal(
        int(share["user_id"]),
        "knowledge",
        2,
        reason_code="share_visit_reward",
        reason="访客访问个人分享并完成一次有效打开",
        idempotency_key=f"share:visit:{share_id}:{datetime.now(timezone.utc).date().isoformat()}:{visitor_fingerprint}",
        reference_type="share",
        reference_id=share_id,
        metadata={"visitor_fingerprint": visitor_fingerprint},
    )
    owner = row("SELECT nickname,avatar FROM users WHERE id=?", (share["user_id"],))
    materials = rows("SELECT id,name,kind,category,content FROM materials WHERE user_id=? AND status='ready' ORDER BY id DESC", (share["user_id"],))
    return {"name": share["name"], "description": share["description"], "owner": owner, "materials": materials}


@app.get("/api/settings")
def get_settings(user: CurrentUser) -> dict:
    return serialize_settings(row("SELECT * FROM user_settings WHERE user_id=?", (user["id"],)))


@app.put("/api/settings")
def update_settings(payload: SettingsRequest, user: CurrentUser) -> dict:
    evolution_mode = payload.evolution_mode if payload.auto_evolution else "manual"
    execute("UPDATE user_settings SET auto_evolution=?,trigger_time=?,evolution_mode=?,monopoly_difficulty=?,flashcard_difficulty=?,matching_difficulty=?,gamified_review=? WHERE user_id=?", (int(payload.auto_evolution), payload.trigger_time, evolution_mode, payload.monopoly_difficulty, payload.flashcard_difficulty, payload.matching_difficulty, int(payload.gamified_review), user["id"]))
    log_event(user["id"], "settings", "update", "更新个人工作坊设置")
    return get_settings(user)


@app.get("/api/logs")
def list_logs(user: CurrentUser, module: str | None = None, limit: int = Query(50, le=200)) -> list[dict]:
    return rows("SELECT * FROM system_logs WHERE user_id=?" + (" AND module=?" if module else "") + " ORDER BY id DESC LIMIT ?", (user["id"], module, limit) if module else (user["id"], limit))


@app.get("/api/logs/export")
def export_logs(user: CurrentUser):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["时间", "模块", "操作", "详情"])
    for item in rows("SELECT created_at,module,action,detail FROM system_logs WHERE user_id=? ORDER BY id DESC", (user["id"],)):
        writer.writerow([item["created_at"], item["module"], item["action"], item["detail"]])
    return StreamingResponse(iter(["﻿" + output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=zhiyan-logs.csv"})
