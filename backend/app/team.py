from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import secrets
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import jwt
import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response

from .auth import CurrentUser, hash_password, issue_tokens, verify_password
from .config import settings
from .currency import (
    TEAM_DAILY_QUOTAS,
    consume_team_quota,
    credit_team,
    debit_team,
    ensure_team_wallet,
    list_transactions,
    quota_status,
    wallet_snapshot,
)
from .database import connection, execute, row, rows, utcnow
from .schemas import (
    TeamActivityRequest,
    TeamActivityUpdateRequest,
    TeamCreateRequest,
    TeamEvolutionReviewRequest,
    TeamEvolutionTaskRequest,
    TeamEvolutionTaskUpdateRequest,
    TeamGameScoreRequest,
    TeamInviteRequest,
    TeamJoinApplyRequest,
    TeamJoinRequest,
    TeamJoinRequestReview,
    TeamLibraryMemberRequest,
    TeamLibraryRequest,
    TeamLibraryUpdateRequest,
    TeamMaterialCommentRequest,
    TeamMaterialCommentResolveRequest,
    TeamMaterialRequest,
    TeamMaterialTagRequest,
    TeamMaterialTransferRequest,
    TeamMaterialUpdateRequest,
    TeamMaterialUrlRequest,
    TeamPersonalMaterialImportRequest,
    TeamMemberRoleRequest,
    TeamQuestionRequest,
    TeamSettingsRequest,
    TeamShareRequest,
    TeamUpdateRequest,
)
from .services import rabbitmq_publish


router = APIRouter(prefix="/api/teams", tags=["teams"])
public_router = APIRouter(tags=["team-shares"])

TEAM_ROLES = {"owner": 4, "admin": 3, "editor": 2, "viewer": 1}
ROLE_LABELS = {
    "owner": "负责人",
    "admin": "管理员",
    "editor": "编辑成员",
    "viewer": "只读成员",
}
DEFAULT_TEAM_SETTINGS = {
    "allow_editor_external_share": False,
    "review_strategy": "owner_final",
    "watermark_enabled": True,
    "auto_evolution_enabled": False,
    "auto_evolution_time": "02:00",
    "daily_deepseek_quota": 1000,
    "media_concurrency": 2,
    "evolution_concurrency": 1,
    "sandbox_concurrency": 1,
    "game_multiplayer_enabled": True,
    "log_retention_days": 180,
    "queue_prefix": "team",
}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".xml"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
TEAM_GAME_ROOMS: dict[int, set[WebSocket]] = {}


def _json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _future(days: int | None) -> str | None:
    if days is None:
        return None
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _team(team_id: int, *, allow_inactive: bool = False) -> dict:
    team = row("SELECT * FROM teams WHERE id=?", (team_id,))
    if not team:
        raise HTTPException(404, "团队不存在")
    if not allow_inactive and team["status"] != "active":
        raise HTTPException(409, f"团队当前状态为{team['status']}，暂不可访问")
    team["settings"] = {**DEFAULT_TEAM_SETTINGS, **_json(team.get("settings"), {})}
    return team


def _membership(team_id: int, user_id: int, *, allow_inactive: bool = False) -> dict:
    member = row(
        "SELECT tm.*,t.status team_status,u.nickname,u.username,u.avatar "
        "FROM team_members tm JOIN teams t ON t.id=tm.team_id "
        "JOIN users u ON u.id=tm.user_id "
        "WHERE tm.team_id=? AND tm.user_id=?",
        (team_id, user_id),
    )
    if not member or member["status"] != "active":
        raise HTTPException(403, "无权访问该团队空间")
    if not allow_inactive and member["team_status"] != "active":
        raise HTTPException(409, f"团队当前状态为{member['team_status']}，暂不可访问")
    return member


def _require_role(team_id: int, user: dict, minimum_role: str, *, allow_inactive: bool = False) -> dict:
    member = _membership(team_id, int(user["id"]), allow_inactive=allow_inactive)
    if TEAM_ROLES.get(member["role"], 0) < TEAM_ROLES[minimum_role]:
        raise HTTPException(403, "当前团队角色无权执行该操作")
    return member


def _log(team_id: int, user_id: int | None, module: str, action: str, detail: str) -> None:
    execute(
        "INSERT INTO team_system_logs(team_id,user_id,module,action,detail,created_at) VALUES(?,?,?,?,?,?)",
        (team_id, user_id, module, action, detail, utcnow()),
    )


def _member_log(
    team_id: int,
    actor_id: int | None,
    target_user_id: int | None,
    action: str,
    detail: str,
) -> None:
    execute(
        "INSERT INTO team_member_operation_logs(team_id,actor_id,target_user_id,action,detail,created_at) VALUES(?,?,?,?,?,?)",
        (team_id, actor_id, target_user_id, action, detail, utcnow()),
    )


def _team_name(team_id: int | None) -> str:
    if team_id is None:
        return "团队空间"
    item = row("SELECT name FROM teams WHERE id=?", (team_id,))
    return item["name"] if item else "团队空间"


def _notify_team_member(
    *,
    team_id: int | None,
    user_id: int,
    actor_id: int | None,
    module: str,
    action: str,
    title: str,
    detail: str,
    target_type: str = "",
    target_id: str | int = "",
    action_url: str = "",
    status: str = "pending",
    metadata: dict[str, Any] | None = None,
) -> int:
    return execute(
        "INSERT INTO team_member_notifications("
        "team_id,user_id,actor_id,module,action,title,detail,target_type,target_id,action_url,status,metadata,created_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            team_id,
            int(user_id),
            actor_id,
            module,
            action,
            title,
            detail,
            target_type,
            str(target_id) if target_id != "" else "",
            action_url,
            status,
            json.dumps(metadata or {}, ensure_ascii=False),
            utcnow(),
        ),
    )


def _team_recipient_ids(
    team_id: int,
    *,
    minimum_role: str = "viewer",
    include_disabled: bool = False,
    exclude_user_id: int | None = None,
) -> list[int]:
    params: list[Any] = [team_id]
    where = "team_id=?"
    if not include_disabled:
        where += " AND status='active'"
    members = rows(f"SELECT user_id,role FROM team_members WHERE {where}", tuple(params))
    minimum = TEAM_ROLES.get(minimum_role, 1)
    result = []
    for member in members:
        member_user_id = int(member["user_id"])
        if exclude_user_id is not None and member_user_id == int(exclude_user_id):
            continue
        if TEAM_ROLES.get(member["role"], 0) >= minimum:
            result.append(member_user_id)
    return list(dict.fromkeys(result))


def _notify_team_members(
    team_id: int,
    *,
    actor_id: int | None,
    module: str,
    action: str,
    title: str,
    detail: str,
    recipient_ids: list[int] | None = None,
    minimum_role: str = "viewer",
    exclude_user_id: int | None = None,
    target_type: str = "",
    target_id: str | int = "",
    action_url: str = "",
    status: str = "pending",
    metadata: dict[str, Any] | None = None,
) -> int:
    ids = recipient_ids
    if ids is None:
        ids = _team_recipient_ids(team_id, minimum_role=minimum_role, exclude_user_id=exclude_user_id)
    created = 0
    for recipient_id in list(dict.fromkeys(int(item) for item in ids)):
        if exclude_user_id is not None and recipient_id == int(exclude_user_id):
            continue
        _notify_team_member(
            team_id=team_id,
            user_id=recipient_id,
            actor_id=actor_id,
            module=module,
            action=action,
            title=title,
            detail=detail,
            target_type=target_type,
            target_id=target_id,
            action_url=action_url,
            status=status,
            metadata=metadata,
        )
        created += 1
    return created


def _serialize_team_notification(item: dict) -> dict:
    return {
        **item,
        "metadata": _json(item.get("metadata"), {}),
        "read": bool(item.get("read_at")),
        "handled": bool(item.get("handled_at") or item.get("status") == "done"),
    }


def _team_counts(team_id: int) -> dict:
    counts = {
        "members": "SELECT COUNT(*) value FROM team_members WHERE team_id=? AND status='active'",
        "libraries": "SELECT COUNT(*) value FROM team_knowledge_libs WHERE team_id=?",
        "materials": "SELECT COUNT(*) value FROM team_materials WHERE team_id=?",
        "processing_materials": "SELECT COUNT(*) value FROM team_materials WHERE team_id=? AND status='processing'",
        "shares": "SELECT COUNT(*) value FROM team_shares WHERE team_id=? AND status='active'",
        "pending_reviews": "SELECT COUNT(*) value FROM team_evolution_tasks WHERE team_id=? AND status='pending_review'",
        "qa_archives": "SELECT COUNT(*) value FROM team_qa_archives WHERE team_id=?",
        "activities": "SELECT COUNT(*) value FROM team_activity WHERE team_id=? AND status NOT IN ('ended','cancelled')",
    }
    payload = {key: row(query, (team_id,))["value"] for key, query in counts.items()}
    payload["storage_used"] = row(
        "SELECT COALESCE(SUM(size),0) value FROM team_materials WHERE team_id=?",
        (team_id,),
    )["value"]
    return payload


def _serialize_member(member: dict) -> dict:
    return {
        **member,
        "role_label": ROLE_LABELS.get(member["role"], member["role"]),
        "can_manage": TEAM_ROLES.get(member["role"], 0) >= TEAM_ROLES["admin"],
    }


def _serialize_material(item: dict) -> dict:
    return {
        **item,
        "tags": _json(item.get("tags"), []),
        "uploader": {
            "id": item.get("uploader_id"),
            "nickname": item.get("nickname") or item.get("username") or "团队成员",
            "avatar": item.get("avatar") or "",
        },
    }


def _library(team_id: int, lib_id: int) -> dict:
    item = row("SELECT * FROM team_knowledge_libs WHERE team_id=? AND id=?", (team_id, lib_id))
    if not item:
        raise HTTPException(404, "团队知识库不存在")
    return item


def _library_access(team_id: int, lib_id: int, user_id: int, *, write: bool = False) -> dict:
    member = _membership(team_id, user_id)
    library = _library(team_id, lib_id)
    role = member["role"]
    if role in {"owner", "admin"}:
        return library
    custom = row(
        "SELECT access FROM team_library_members WHERE lib_id=? AND user_id=?",
        (lib_id, user_id),
    )
    if library["permission_mode"] == "custom":
        if not custom:
            raise HTTPException(403, "你没有该知识库的访问权限")
        if write and custom["access"] != "write":
            raise HTTPException(403, "你没有该知识库的写入权限")
        return library
    if library["visibility"] == "private" and library["created_by"] != user_id:
        raise HTTPException(403, "该知识库仅创建者和管理员可访问")
    if library["permission_mode"] == "admins_only":
        raise HTTPException(403, "该知识库仅管理员可访问")
    if write and TEAM_ROLES.get(role, 0) < TEAM_ROLES["editor"]:
        raise HTTPException(403, "当前角色没有该知识库的写入权限")
    return library


def _visible_library_ids(team_id: int, user_id: int) -> list[int]:
    member = _membership(team_id, user_id)
    libraries = rows("SELECT * FROM team_knowledge_libs WHERE team_id=?", (team_id,))
    if member["role"] in {"owner", "admin"}:
        return [int(item["id"]) for item in libraries]
    result: list[int] = []
    for library in libraries:
        try:
            _library_access(team_id, int(library["id"]), user_id)
        except HTTPException:
            continue
        result.append(int(library["id"]))
    return result


def _material(team_id: int, material_id: int, user_id: int, *, write: bool = False) -> dict:
    item = row("SELECT * FROM team_materials WHERE team_id=? AND id=?", (team_id, material_id))
    if not item:
        raise HTTPException(404, "团队素材不存在")
    if item.get("lib_id"):
        _library_access(team_id, int(item["lib_id"]), user_id, write=write)
    elif write:
        _require_role(team_id, {"id": user_id}, "editor")
    return item


def _material_scope_sql(team_id: int, user_id: int, lib_id: int | None = None) -> tuple[str, list[Any]]:
    visible_ids = _visible_library_ids(team_id, user_id)
    if lib_id is not None:
        if lib_id not in visible_ids:
            raise HTTPException(403, "你没有该知识库的访问权限")
        return "m.team_id=? AND m.lib_id=?", [team_id, lib_id]
    if not visible_ids:
        return "m.team_id=? AND m.lib_id IS NULL", [team_id]
    placeholders = ",".join("?" for _ in visible_ids)
    return f"(m.team_id=? AND (m.lib_id IS NULL OR m.lib_id IN ({placeholders})))", [team_id, *visible_ids]


def _team_question_terms(question: str) -> list[str]:
    normalized = question.strip().lower()
    terms = [item for item in re.findall(r"[\w\u4e00-\u9fff]+", normalized) if len(item) > 1]
    han_text = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    if len(han_text) >= 4:
        terms.extend(han_text[index:index + 2] for index in range(0, len(han_text) - 1, 2))
    if normalized and len(normalized) <= 80:
        terms.append(normalized)
    return list(dict.fromkeys(terms))[:16]


def _team_source_snippet(content: str, terms: list[str], *, size: int = 420) -> str:
    text = " ".join((content or "").split())
    if len(text) <= size:
        return text
    lowered = text.lower()
    first_index = -1
    for term in terms:
        index = lowered.find(term.lower())
        if index >= 0 and (first_index < 0 or index < first_index):
            first_index = index
    if first_index < 0:
        return text[:size].strip()
    start = max(0, first_index - size // 4)
    end = min(len(text), start + size)
    prefix = "..." if start else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def _team_material_score(material: dict, terms: list[str]) -> int:
    name = str(material.get("name") or "").lower()
    content = str(material.get("content") or "").lower()
    tags = " ".join(str(item) for item in _json(material.get("tags"), [])).lower()
    score = 0
    for term in terms:
        value = term.lower()
        if not value:
            continue
        if value in name:
            score += 8
        if value in tags:
            score += 5
        score += min(content.count(value), 6)
    return score


def _search_team_sources(team_id: int, user_id: int, selected_lib_ids: list[int], question: str) -> list[dict]:
    terms = _team_question_terms(question)
    visible_ids = _visible_library_ids(team_id, user_id)
    params: list[Any] = [team_id]
    where = "m.team_id=? AND m.status='ready'"
    if selected_lib_ids:
        where += f" AND (m.lib_id IS NULL OR m.lib_id IN ({','.join('?' for _ in selected_lib_ids)}))"
        params.extend(selected_lib_ids)
    elif visible_ids:
        where += f" AND (m.lib_id IS NULL OR m.lib_id IN ({','.join('?' for _ in visible_ids)}))"
        params.extend(visible_ids)
    else:
        where += " AND m.lib_id IS NULL"
    candidates = rows(
        f"SELECT m.id,m.name,m.content,m.lib_id,m.tags,m.updated_at,l.name lib_name,u.nickname uploader_name "
        f"FROM team_materials m LEFT JOIN team_knowledge_libs l ON l.id=m.lib_id "
        f"JOIN users u ON u.id=m.uploader_id WHERE {where} ORDER BY m.updated_at DESC LIMIT 160",
        tuple(params),
    )
    ranked = []
    for item in candidates:
        score = _team_material_score(item, terms)
        if score > 0:
            ranked.append((score, item))
    if not ranked and candidates:
        ranked = [(1, item) for item in candidates[:6]]
    ranked.sort(key=lambda pair: (pair[0], pair[1].get("updated_at") or ""), reverse=True)
    sources = []
    for score, item in ranked[:6]:
        sources.append({
            "material_id": item["id"],
            "name": item["name"],
            "lib_id": item["lib_id"],
            "library": item["lib_name"] or "未归属知识库",
            "uploader": item["uploader_name"],
            "snippet": _team_source_snippet(item.get("content") or "", terms),
            "score": score,
        })
    return sources


def _local_team_answer(question: str, sources: list[dict], library_names: list[str]) -> str:
    if not sources:
        scope = "、".join(library_names) if library_names else "当前成员可访问范围"
        return f"未在{scope}内检索到可引用素材。建议先上传团队素材、调整知识库权限，或换一个更具体的问题。"
    lines = [
        f"针对「{question}」，已在团队授权知识库中找到 {len(sources)} 条可引用素材。",
        "",
    ]
    for index, source in enumerate(sources, start=1):
        lines.append(f"{index}. {source['name']}（{source['library']}，上传人：{source['uploader']}）")
        lines.append(f"   {source['snippet'][:260]}")
    lines.append("")
    lines.append("结论：请优先参考上述素材片段；若需要正式输出，可继续补充团队素材后再次发起问答。")
    return "\n".join(lines)


def _deepseek_team_answer(question: str, sources: list[dict]) -> tuple[str, str]:
    if not settings.deepseek_api_key or not sources:
        return "", ""
    context = "\n\n".join(
        f"[来源{index}｜{source['name']}｜{source['library']}｜上传人：{source['uploader']}]\n{source['snippet']}"
        for index, source in enumerate(sources, start=1)
    )
    client_options: dict[str, Any] = {"timeout": 60}
    if settings.deepseek_proxy_url:
        client_options["proxy"] = settings.deepseek_proxy_url
    with httpx.Client(**client_options) as client:
        response = client.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json={
                "model": settings.deepseek_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是团队知识库问答 Agent。只能依据给定团队素材回答；必须保留来源名称、知识库和上传人；没有依据时明确说明不足。",
                    },
                    {"role": "user", "content": f"context:\n{context}\n\nquestion:\n{question}"},
                ],
                "temperature": 0.2,
                "max_tokens": 1400,
            },
        )
        response.raise_for_status()
    answer = response.json()["choices"][0]["message"]["content"]
    return str(answer).strip(), "deepseek-team-rag"


def _serialize_qa_archive(item: dict, *, current_user_id: int | None = None, role: str = "viewer") -> dict:
    sources = _json(item.get("sources"), [])
    lib_ids = _json(item.get("lib_ids"), [])
    return {
        **item,
        "sources": sources,
        "lib_ids": lib_ids,
        "source_count": len(sources),
        "library_count": len(lib_ids),
        "can_delete": bool(current_user_id and (int(item.get("user_id") or 0) == current_user_id or role in {"owner", "admin"})),
    }


def _create_team_qa_archive(team_id: int, payload: TeamQuestionRequest, user: CurrentUser) -> dict:
    member = _membership(team_id, int(user["id"]))
    allowed = set(_visible_library_ids(team_id, int(user["id"])))
    requested_ids = list(dict.fromkeys(int(lib_id) for lib_id in payload.lib_ids))
    if any(lib_id not in allowed for lib_id in requested_ids):
        raise HTTPException(403, "问答范围包含你无权访问的知识库")
    lib_ids = requested_ids or sorted(allowed)
    quota_state = quota_status("team", team_id, "team_qa")
    if quota_state["free_remaining"] <= 0 and member["role"] not in {"owner", "admin"}:
        raise HTTPException(403, "团队免费问答额度已用尽，只有管理员或负责人可以消耗团队公共资金")
    question = payload.question.strip()
    quota = consume_team_quota(
        team_id,
        "team_qa",
        user_id=int(user["id"]),
        idempotency_key=f"team:qa:{team_id}:{secrets.token_hex(12)}",
        reference_type="team_qa",
        reference_id=question[:80],
    )
    sources = _search_team_sources(team_id, int(user["id"]), requested_ids, question)
    library_rows = []
    if lib_ids:
        library_rows = rows(
            f"SELECT id,name FROM team_knowledge_libs WHERE team_id=? AND id IN ({','.join('?' for _ in lib_ids)})",
            (team_id, *lib_ids),
        )
    library_names = [item["name"] for item in library_rows]
    mode = "team-local-rag"
    agent_note = "已使用团队本地检索生成回答。"
    try:
        ai_answer, ai_mode = _deepseek_team_answer(question, sources)
        if ai_answer:
            answer = ai_answer
            mode = ai_mode
            agent_note = "已使用 DeepSeek 团队 RAG 问答生成回答。"
        else:
            answer = _local_team_answer(question, sources, library_names)
    except Exception as exc:
        answer = _local_team_answer(question, sources, library_names)
        mode = "team-local-rag-fallback"
        agent_note = f"DeepSeek 团队问答调用失败，已使用本地检索回答：{str(exc)[:160]}"
    archive_id = execute(
        "INSERT INTO team_qa_archives(team_id,user_id,question,answer,sources,lib_ids,created_at) VALUES(?,?,?,?,?,?,?)",
        (team_id, int(user["id"]), question, answer, json.dumps(sources, ensure_ascii=False), json.dumps(lib_ids), utcnow()),
    )
    _log(team_id, int(user["id"]), "qa", "ask", f"团队问答 #{archive_id}，来源 {len(sources)} 条，模式 {mode}")
    created = row(
        "SELECT q.*,u.nickname FROM team_qa_archives q JOIN users u ON u.id=q.user_id WHERE q.id=? AND q.team_id=?",
        (archive_id, team_id),
    )
    result = _serialize_qa_archive(created, current_user_id=int(user["id"]), role=member["role"])
    result.update({
        "mode": mode,
        "agent_note": agent_note,
        "scope": {
            "requested_lib_ids": requested_ids,
            "effective_lib_ids": lib_ids,
            "library_names": library_names,
            "uses_all_visible": not bool(requested_ids),
        },
        "currency": {
            "charged": quota.get("charged", 0),
            "currency": "knowledge",
            "quota": quota_status("team", team_id, "team_qa"),
            "wallet": wallet_snapshot("team", team_id, user_id=int(user["id"])),
        },
    })
    return result


def _serialize_task(task: dict, review_map: dict[int, list[dict]] | None = None) -> dict:
    payload = {
        **task,
        "reviews": (review_map or {}).get(int(task["id"]), []),
    }
    return payload


def _clean_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(tag.strip() for tag in tags if tag and tag.strip()))[:20]


def _upload_storage_path(file_path: str | None) -> Path | None:
    if not file_path:
        return None
    source = Path(str(file_path))
    if source.is_absolute():
        return None
    try:
        upload_root = settings.upload_dir.resolve()
        target = (upload_root / source).resolve()
        target.relative_to(upload_root)
    except (OSError, ValueError):
        return None
    return target


def _insert_material(
    *,
    team_id: int,
    lib_id: int | None,
    user_id: int,
    name: str,
    source: str,
    kind: str,
    content: str,
    tags: list[str],
    status: str = "ready",
    file_path: str = "",
    origin_url: str = "",
    size: int | None = None,
) -> int:
    with connection() as conn:
        material_id = conn.execute(
            "INSERT INTO team_materials(team_id,lib_id,uploader_id,name,source,kind,size,status,tags,content,file_path,origin_url,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                team_id,
                lib_id,
                user_id,
                name,
                source,
                kind,
                size if size is not None else len(content.encode("utf-8")),
                status,
                json.dumps(_clean_tags(tags), ensure_ascii=False),
                content,
                file_path,
                origin_url,
                utcnow(),
                utcnow(),
            ),
        ).lastrowid
        if status == "ready":
            conn.execute(
                "INSERT INTO team_material_versions(material_id,team_id,user_id,version,content,note,created_at) VALUES(?,?,?,?,?,?,?)",
                (material_id, team_id, user_id, 1, content, "初始版本", utcnow()),
            )
    return int(material_id)


def _finish_media_ingest(
    team_id: int,
    material_id: int,
    task_id: int,
    user_id: int,
    kind: str,
    initial_content: str,
) -> None:
    content = initial_content or f"已完成{kind}素材入库。当前环境未配置外部 OCR/转写服务，已保留原文件和处理记录，可在服务接入后重新处理。"
    with connection() as conn:
        conn.execute(
            "UPDATE team_materials SET status='ready',content=?,size=?,updated_at=? WHERE team_id=? AND id=?",
            (content, len(content.encode("utf-8")), utcnow(), team_id, material_id),
        )
        conn.execute(
            "INSERT INTO team_material_versions(material_id,team_id,user_id,version,content,note,created_at) VALUES(?,?,?,?,?,?,?)",
            (material_id, team_id, user_id, 1, content, "本地降级处理完成", utcnow()),
        )
        conn.execute(
            "UPDATE team_sandbox_tasks SET status='completed',detail=?,finished_at=? WHERE id=?",
            (f"素材{material_id}处理完成，外部服务未配置时采用本地降级结果", utcnow(), task_id),
        )
    credit_team(
        team_id,
        "knowledge",
        5,
        reason_code="team_material_ingest",
        reason="团队素材处理完成奖励",
        idempotency_key=f"team:material:{material_id}:processed",
        reference_type="team_material",
        reference_id=str(material_id),
        user_id=user_id,
    )
    _log(team_id, user_id, "material", "processed", f"素材 #{material_id} 已完成入库")


def _export_csv(filename: str, headers: list[str], data: list[list[Any]]) -> Response:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(data)
    content = "\ufeff" + output.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _xlsx_column(index: int) -> str:
    result = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _export_xlsx(filename: str, headers: list[str], data: list[list[Any]]) -> Response:
    all_rows = [headers, *data]
    sheet_rows: list[str] = []
    for row_index, values in enumerate(all_rows, start=1):
        cells = []
        for column_index, value in enumerate(values):
            cell_ref = f"{_xlsx_column(column_index)}{row_index}"
            text = escape("" if value is None else str(value))
            cells.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="团队报表" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return Response(
        content=stream.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _now_cutoff(period: str) -> str | None:
    if period == "day":
        return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    if period == "week":
        return (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    return None


@router.get("")
def list_teams(user: CurrentUser) -> dict:
    memberships = rows(
        "SELECT t.*,tm.role,tm.status member_status,tm.joined_at "
        "FROM team_members tm JOIN teams t ON t.id=tm.team_id "
        "WHERE tm.user_id=? AND tm.status='active' ORDER BY t.created_at DESC",
        (int(user["id"]),),
    )
    teams = []
    archived = []
    for item in memberships:
        item["settings"] = {**DEFAULT_TEAM_SETTINGS, **_json(item.get("settings"), {})}
        item["role_label"] = ROLE_LABELS.get(item["role"], item["role"])
        item["counts"] = _team_counts(int(item["id"]))
        item["currency"] = wallet_snapshot("team", int(item["id"]), user_id=int(user["id"]))
        (teams if item["status"] == "active" else archived).append(item)
    return {
        "personal": {"id": "personal", "name": "我的个人空间", "description": "个人端数据与团队端数据完全隔离"},
        "teams": teams,
        "archived_teams": archived,
    }


@router.get("/personal/notifications")
def list_personal_team_notifications(
    user: CurrentUser,
    status: str = Query("all", pattern="^(all|pending|done|unread)$"),
    limit: int = Query(40, ge=1, le=120),
) -> dict:
    params: list[Any] = [int(user["id"])]
    where = "n.user_id=?"
    if status == "pending":
        where += " AND n.status='pending'"
    elif status == "done":
        where += " AND n.status='done'"
    elif status == "unread":
        where += " AND n.read_at IS NULL"
    params.append(limit)
    items = rows(
        "SELECT n.*,t.name team_name,t.status team_status,a.nickname actor_name "
        "FROM team_member_notifications n "
        "LEFT JOIN teams t ON t.id=n.team_id "
        "LEFT JOIN users a ON a.id=n.actor_id "
        f"WHERE {where} ORDER BY n.id DESC LIMIT ?",
        tuple(params),
    )
    unread = row(
        "SELECT COUNT(*) value FROM team_member_notifications WHERE user_id=? AND read_at IS NULL",
        (int(user["id"]),),
    )["value"]
    pending = row(
        "SELECT COUNT(*) value FROM team_member_notifications WHERE user_id=? AND status='pending'",
        (int(user["id"]),),
    )["value"]
    return {
        "items": [_serialize_team_notification(item) for item in items],
        "unread": unread,
        "pending": pending,
    }


@router.post("/personal/notifications/{notification_id}/read")
def read_personal_team_notification(notification_id: int, user: CurrentUser) -> dict:
    item = row("SELECT * FROM team_member_notifications WHERE id=? AND user_id=?", (notification_id, int(user["id"])))
    if not item:
        raise HTTPException(404, "团队通知不存在")
    execute(
        "UPDATE team_member_notifications SET read_at=COALESCE(read_at,?) WHERE id=? AND user_id=?",
        (utcnow(), notification_id, int(user["id"])),
    )
    return _serialize_team_notification(row("SELECT * FROM team_member_notifications WHERE id=?", (notification_id,)))


@router.post("/personal/notifications/{notification_id}/handle")
def handle_personal_team_notification(notification_id: int, user: CurrentUser) -> dict:
    item = row("SELECT * FROM team_member_notifications WHERE id=? AND user_id=?", (notification_id, int(user["id"])))
    if not item:
        raise HTTPException(404, "团队通知不存在")
    now = utcnow()
    execute(
        "UPDATE team_member_notifications SET status='done',read_at=COALESCE(read_at,?),handled_at=COALESCE(handled_at,?) "
        "WHERE id=? AND user_id=?",
        (now, now, notification_id, int(user["id"])),
    )
    return _serialize_team_notification(row("SELECT * FROM team_member_notifications WHERE id=?", (notification_id,)))


@router.get("/{team_id}/currency")
def team_currency(team_id: int, user: CurrentUser) -> dict:
    _membership(team_id, int(user["id"]))
    return wallet_snapshot("team", team_id, user_id=int(user["id"]))


@router.get("/{team_id}/currency/transactions")
def team_currency_transactions(
    team_id: int,
    user: CurrentUser,
    limit: int = Query(100, ge=1, le=200),
    currency: str | None = Query(None),
) -> dict:
    _membership(team_id, int(user["id"]))
    return {
        "scope": "team",
        "team_id": team_id,
        "items": list_transactions("team", team_id, limit=limit, currency=currency),
    }


@router.get("/discover")
def discover_teams(user: CurrentUser, q: str = Query("", min_length=2, max_length=80)) -> dict:
    keyword = q.strip()
    if len(keyword) < 2:
        return {"items": []}
    pattern = f"%{keyword}%"
    items = rows(
        "SELECT t.id,t.name,t.avatar,t.description,t.team_type,t.status,t.created_at "
        "FROM teams t WHERE t.status='active' AND (t.name LIKE ? OR t.description LIKE ?) "
        "AND NOT EXISTS (SELECT 1 FROM team_members tm WHERE tm.team_id=t.id AND tm.user_id=?) "
        "ORDER BY t.created_at DESC LIMIT 20",
        (pattern, pattern, int(user["id"])),
    )
    for item in items:
        item["counts"] = _team_counts(int(item["id"]))
        pending = row(
            "SELECT id,status FROM team_join_requests WHERE team_id=? AND user_id=? AND status='pending'",
            (item["id"], int(user["id"])),
        )
        item["join_request_status"] = pending["status"] if pending else None
    return {"items": items}


@router.post("", status_code=201)
def create_team(payload: TeamCreateRequest, user: CurrentUser) -> dict:
    settings_json = json.dumps(DEFAULT_TEAM_SETTINGS, ensure_ascii=False)
    with connection() as conn:
        team_id = conn.execute(
            "INSERT INTO teams(owner_id,name,avatar,description,team_type,settings,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                int(user["id"]),
                payload.name.strip(),
                payload.avatar,
                payload.description.strip(),
                payload.team_type,
                settings_json,
                utcnow(),
            ),
        ).lastrowid
        conn.execute(
            "INSERT INTO team_members(team_id,user_id,role,status,joined_at,last_active_at) VALUES(?,?,?,?,?,?)",
            (team_id, int(user["id"]), "owner", "active", utcnow(), utcnow()),
        )
        lib_id = conn.execute(
            "INSERT INTO team_knowledge_libs(team_id,name,description,category,dataset_key,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
            (team_id, "默认团队知识库", "团队创建时自动生成的协作知识库。", "通用", f"team_{team_id}_default", int(user["id"]), utcnow()),
        ).lastrowid
        conn.execute(
            "INSERT INTO team_system_logs(team_id,user_id,module,action,detail,created_at) VALUES(?,?,?,?,?,?)",
            (team_id, int(user["id"]), "team", "create", f"创建团队 {payload.name}", utcnow()),
        )
    wallet = ensure_team_wallet(int(team_id), user_id=int(user["id"]))
    return {"id": int(team_id), "default_lib_id": int(lib_id), **_team(int(team_id)), "role": "owner", "currency": wallet}


@router.post("/join")
def join_team(payload: TeamJoinRequest, user: CurrentUser) -> dict:
    invite = row("SELECT * FROM team_invites WHERE code=? AND status='active'", (payload.code.strip().upper(),))
    if not invite:
        raise HTTPException(404, "邀请码无效")
    if invite["expires_at"] and datetime.fromisoformat(invite["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(410, "邀请码已过期")
    team = row("SELECT id,name,status FROM teams WHERE id=?", (invite["team_id"],))
    if not team or team["status"] != "active":
        raise HTTPException(410, "团队当前不可加入")
    if row("SELECT id FROM team_members WHERE team_id=? AND user_id=?", (invite["team_id"], int(user["id"]))):
        raise HTTPException(409, "你已经在该团队中")
    if row(
        "SELECT id FROM team_join_requests WHERE team_id=? AND user_id=? AND status='pending'",
        (invite["team_id"], int(user["id"])),
    ):
        raise HTTPException(409, "你已经提交过加入申请，请等待负责人审核")
    request_id = execute(
        "INSERT INTO team_join_requests(team_id,user_id,message,status,requested_role,invite_id,created_at) VALUES(?,?,?,?,?,?,?)",
        (invite["team_id"], int(user["id"]), "通过邀请码申请加入", "pending", invite["role"], invite["id"], utcnow()),
    )
    _log(invite["team_id"], int(user["id"]), "member", "join_request", f"提交加入申请 #{request_id}")
    _notify_team_members(
        int(invite["team_id"]),
        actor_id=int(user["id"]),
        module="member",
        action="join_request",
        title=f"{user['nickname']} 申请加入「{team['name']}」",
        detail=f"成员通过邀请码提交加入申请，期望角色为 {ROLE_LABELS.get(invite['role'], invite['role'])}，请在团队端成员管理中审核。",
        minimum_role="admin",
        target_type="join_request",
        target_id=request_id,
        metadata={"requested_role": invite["role"], "request_user_id": int(user["id"])},
    )
    return {
        "request_id": request_id,
        "team_id": invite["team_id"],
        "team_name": team["name"],
        "role": invite["role"],
        "status": "pending",
    }


@router.post("/{team_id}/join-requests", status_code=201)
def create_join_request(team_id: int, payload: TeamJoinApplyRequest, user: CurrentUser) -> dict:
    team = _team(team_id)
    if row("SELECT id FROM team_members WHERE team_id=? AND user_id=?", (team_id, int(user["id"]))):
        raise HTTPException(409, "你已经在该团队中")
    if row(
        "SELECT id FROM team_join_requests WHERE team_id=? AND user_id=? AND status='pending'",
        (team_id, int(user["id"])),
    ):
        raise HTTPException(409, "你已经提交过加入申请")
    request_id = execute(
        "INSERT INTO team_join_requests(team_id,user_id,message,status,requested_role,created_at) VALUES(?,?,?,?,?,?)",
        (team_id, int(user["id"]), payload.message.strip(), "pending", "viewer", utcnow()),
    )
    _log(team_id, int(user["id"]), "member", "join_request", f"向团队{team['name']}提交加入申请")
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="member",
        action="join_request",
        title=f"{user['nickname']} 申请加入「{team['name']}」",
        detail=payload.message.strip() or "成员通过个人端搜索提交加入申请，请在团队端成员管理中审核。",
        minimum_role="admin",
        target_type="join_request",
        target_id=request_id,
        metadata={"requested_role": "viewer", "request_user_id": int(user["id"])},
    )
    return {"id": request_id, "team_id": team_id, "team_name": team["name"], "status": "pending"}


@router.get("/{team_id}")
def team_detail(team_id: int, user: CurrentUser) -> dict:
    member = _membership(team_id, int(user["id"]))
    team = _team(team_id)
    execute("UPDATE team_members SET last_active_at=? WHERE team_id=? AND user_id=?", (utcnow(), team_id, int(user["id"])))
    return {
        **team,
        "role": member["role"],
        "role_label": ROLE_LABELS.get(member["role"], member["role"]),
        "counts": _team_counts(team_id),
        "currency": wallet_snapshot("team", team_id, user_id=int(user["id"])),
    }


@router.patch("/{team_id}")
def update_team(team_id: int, payload: TeamUpdateRequest, user: CurrentUser) -> dict:
    member = _require_role(team_id, user, "admin", allow_inactive=True)
    team = _team(team_id, allow_inactive=True)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("status") in {"archived", "frozen"} and member["role"] != "owner":
        raise HTTPException(403, "只有负责人可以归档或冻结团队")
    if updates.get("status") == "active" and member["role"] != "owner":
        raise HTTPException(403, "只有负责人可以恢复团队")
    if not updates:
        return team
    assignments = ",".join(f"{key}=?" for key in updates)
    params = tuple(updates.values()) + (team_id,)
    archived_at = utcnow() if updates.get("status") == "archived" else team.get("archived_at")
    execute(f"UPDATE teams SET {assignments},archived_at=? WHERE id=?", (*tuple(updates.values()), archived_at, team_id))
    _log(team_id, int(user["id"]), "team", "update", "更新团队基础信息或生命周期状态")
    if "status" in updates:
        status_label = {"active": "恢复启用", "archived": "归档", "frozen": "冻结"}.get(updates["status"], updates["status"])
        _notify_team_members(
            team_id,
            actor_id=int(user["id"]),
            module="team",
            action="lifecycle",
            title=f"「{team['name']}」已{status_label}",
            detail=f"团队负责人将团队状态调整为 {status_label}，个人端可继续查看可用团队状态与历史通知。",
            exclude_user_id=int(user["id"]),
            target_type="team",
            target_id=team_id,
            metadata={"status": updates["status"]},
        )
    elif any(key in updates for key in ("name", "description", "team_type", "avatar")):
        _notify_team_members(
            team_id,
            actor_id=int(user["id"]),
            module="team",
            action="profile_update",
            title=f"「{team['name']}」基础信息已更新",
            detail="团队管理员更新了团队名称、简介或类型，个人端团队基础数据已同步。",
            exclude_user_id=int(user["id"]),
            target_type="team",
            target_id=team_id,
        )
    return _team(team_id, allow_inactive=True)


@router.post("/{team_id}/restore")
def restore_team(team_id: int, user: CurrentUser) -> dict:
    _require_role(team_id, user, "owner", allow_inactive=True)
    team = _team(team_id, allow_inactive=True)
    execute("UPDATE teams SET status='active',archived_at=NULL WHERE id=?", (team_id,))
    _log(team_id, int(user["id"]), "team", "restore", "恢复团队空间")
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="team",
        action="restore",
        title=f"「{team['name']}」已恢复启用",
        detail="团队空间已恢复为 active 状态，成员可以在个人端继续查看基础数据并按角色参与协作。",
        exclude_user_id=int(user["id"]),
        target_type="team",
        target_id=team_id,
    )
    return _team(team_id)


@router.delete("/{team_id}")
def dissolve_team(team_id: int, user: CurrentUser, confirm: bool = Query(False)) -> dict:
    _require_role(team_id, user, "owner", allow_inactive=True)
    if not confirm:
        raise HTTPException(400, "解散团队需要传入 confirm=true")
    team = _team(team_id, allow_inactive=True)
    recipient_ids = _team_recipient_ids(team_id, include_disabled=True, exclude_user_id=int(user["id"]))
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="team",
        action="dissolve",
        title=f"「{team['name']}」已解散",
        detail="团队负责人已解散该团队，团队空间、知识库和协作记录将从团队列表中移除。",
        recipient_ids=recipient_ids,
        target_type="team",
        target_id=team_id,
        status="done",
        metadata={"team_name": team["name"]},
    )
    execute("DELETE FROM teams WHERE id=?", (team_id,))
    return {"ok": True, "team_id": team_id, "status": "dissolved"}


@router.post("/{team_id}/leave")
def leave_team(team_id: int, user: CurrentUser) -> dict:
    member = _require_role(team_id, user, "viewer")
    if member["role"] == "owner":
        raise HTTPException(409, "负责人不能直接退出，请先转让负责人或解散团队")
    execute("DELETE FROM team_members WHERE team_id=? AND user_id=?", (team_id, int(user["id"])))
    _member_log(team_id, int(user["id"]), int(user["id"]), "leave", "成员主动退出团队")
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="member",
        action="leave",
        title=f"{user['nickname']} 已退出「{_team_name(team_id)}」",
        detail="成员在个人端或团队端主动退出，团队成员列表和权限已同步更新。",
        minimum_role="admin",
        target_type="member",
        target_id=int(user["id"]),
    )
    return {"ok": True}


@router.post("/{team_id}/switch-token")
def switch_team_token(team_id: int, user: CurrentUser) -> dict:
    _membership(team_id, int(user["id"]))
    return issue_tokens(int(user["id"]), team_id=team_id)


@router.get("/{team_id}/workspace")
def team_workspace(team_id: int, user: CurrentUser) -> dict:
    member = _membership(team_id, int(user["id"]))
    team = _team(team_id)
    visible_ids = _visible_library_ids(team_id, int(user["id"]))
    libraries = rows("SELECT l.*,u.nickname creator_name FROM team_knowledge_libs l JOIN users u ON u.id=l.created_by WHERE l.team_id=? ORDER BY l.id DESC", (team_id,))
    libraries = [item for item in libraries if int(item["id"]) in visible_ids or member["role"] in {"owner", "admin"}]
    params: list[Any] = [team_id]
    material_where = "m.team_id=?"
    if member["role"] not in {"owner", "admin"}:
        if visible_ids:
            material_where += f" AND (m.lib_id IS NULL OR m.lib_id IN ({','.join('?' for _ in visible_ids)}))"
            params.extend(visible_ids)
        else:
            material_where += " AND m.lib_id IS NULL"
    materials = rows(
        f"SELECT m.*,u.nickname,u.username,u.avatar,l.name lib_name FROM team_materials m "
        f"JOIN users u ON u.id=m.uploader_id LEFT JOIN team_knowledge_libs l ON l.id=m.lib_id "
        f"WHERE {material_where} ORDER BY m.id DESC LIMIT 12",
        tuple(params),
    )
    tasks = rows(
        "SELECT t.*,l.name lib_name,u.nickname creator_name FROM team_evolution_tasks t "
        "LEFT JOIN team_knowledge_libs l ON l.id=t.lib_id JOIN users u ON u.id=t.created_by "
        "WHERE t.team_id=? AND (t.visibility='team' OR t.created_by=?) ORDER BY t.id DESC LIMIT 8",
        (team_id, int(user["id"])),
    )
    ranks = rows(
        "SELECT r.user_id,u.nickname,SUM(r.score) score,SUM(r.correct) correct,SUM(r.total) total "
        "FROM team_game_rank r JOIN users u ON u.id=r.user_id WHERE r.team_id=? "
        "GROUP BY r.user_id,u.nickname ORDER BY score DESC LIMIT 8",
        (team_id,),
    )
    activities = rows("SELECT * FROM team_activity WHERE team_id=? ORDER BY id DESC LIMIT 8", (team_id,))
    achievements = rows(
        "SELECT a.*,u.nickname FROM team_game_achievements a JOIN users u ON u.id=a.user_id WHERE a.team_id=? ORDER BY a.awarded_at DESC LIMIT 12",
        (team_id,),
    )
    return {
        "team": {**team, "role": member["role"], "role_label": ROLE_LABELS.get(member["role"], member["role"])},
        "counts": _team_counts(team_id),
        "currency": wallet_snapshot("team", team_id, user_id=int(user["id"])),
        "libraries": libraries,
        "materials": [_serialize_material(item) for item in materials],
        "evolution_tasks": tasks,
        "leaderboard": ranks,
        "activities": activities,
        "achievements": achievements,
        "queues": {
            "media": f"{team['settings'].get('queue_prefix', 'team')}.media.{team_id}",
            "evolution": f"{team['settings'].get('queue_prefix', 'team')}.evolution.{team_id}",
            "sandbox": f"game.sandbox.team.{team_id}",
        },
    }


@router.get("/{team_id}/members")
def list_members(team_id: int, user: CurrentUser) -> dict:
    _membership(team_id, int(user["id"]))
    members = rows(
        "SELECT tm.*,u.nickname,u.username,u.avatar FROM team_members tm JOIN users u ON u.id=tm.user_id "
        "WHERE tm.team_id=? ORDER BY CASE tm.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'editor' THEN 2 ELSE 3 END, tm.joined_at",
        (team_id,),
    )
    return {"items": [_serialize_member(item) for item in members]}


@router.get("/{team_id}/join-requests")
def list_join_requests(team_id: int, user: CurrentUser, status: str = "pending") -> dict:
    _require_role(team_id, user, "admin")
    params: list[Any] = [team_id]
    where = "jr.team_id=?"
    if status != "all":
        where += " AND jr.status=?"
        params.append(status)
    items = rows(
        f"SELECT jr.*,u.nickname,u.username,u.avatar,r.nickname reviewer_name "
        f"FROM team_join_requests jr JOIN users u ON u.id=jr.user_id "
        f"LEFT JOIN users r ON r.id=jr.reviewer_id WHERE {where} ORDER BY jr.id DESC",
        tuple(params),
    )
    return {"items": items}


@router.patch("/{team_id}/join-requests/{request_id}")
def review_join_request(
    team_id: int,
    request_id: int,
    payload: TeamJoinRequestReview,
    user: CurrentUser,
) -> dict:
    actor = _require_role(team_id, user, "admin")
    request = row("SELECT * FROM team_join_requests WHERE team_id=? AND id=?", (team_id, request_id))
    if not request:
        raise HTTPException(404, "加入申请不存在")
    if request["status"] != "pending":
        raise HTTPException(409, "该申请已经处理")
    if payload.decision == "approved":
        role = payload.role
        if role == "admin" and actor["role"] != "owner":
            raise HTTPException(403, "只有负责人可以授予管理员角色")
        with connection() as conn:
            existing = conn.execute(
                "SELECT id FROM team_members WHERE team_id=? AND user_id=?",
                (team_id, request["user_id"]),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE team_members SET role=?,status='active',joined_at=?,last_active_at=? WHERE id=?",
                    (role, utcnow(), utcnow(), existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO team_members(team_id,user_id,role,status,joined_at,last_active_at) VALUES(?,?,?,?,?,?)",
                    (team_id, request["user_id"], role, "active", utcnow(), utcnow()),
                )
            conn.execute(
                "UPDATE team_join_requests SET status='approved',reviewer_id=?,review_note=?,reviewed_at=?,requested_role=? WHERE id=?",
                (int(user["id"]), payload.note, utcnow(), role, request_id),
            )
            if request.get("invite_id"):
                conn.execute("UPDATE team_invites SET uses=uses+1 WHERE id=?", (request["invite_id"],))
        _member_log(team_id, int(user["id"]), request["user_id"], "join_approve", f"审核通过，角色为{ROLE_LABELS[role]}")
        _notify_team_member(
            team_id=team_id,
            user_id=int(request["user_id"]),
            actor_id=int(user["id"]),
            module="member",
            action="join_approved",
            title=f"你已加入「{_team_name(team_id)}」",
            detail=f"团队管理员已通过你的加入申请，当前角色为 {ROLE_LABELS.get(role, role)}。你可以在个人端“我的团队”查看基础数据并按权限操作。",
            target_type="team",
            target_id=team_id,
            status="done",
            metadata={"role": role, "request_id": request_id},
        )
    else:
        execute(
            "UPDATE team_join_requests SET status='rejected',reviewer_id=?,review_note=?,reviewed_at=? WHERE id=?",
            (int(user["id"]), payload.note, utcnow(), request_id),
        )
        _member_log(team_id, int(user["id"]), request["user_id"], "join_reject", "拒绝加入申请")
        _notify_team_member(
            team_id=team_id,
            user_id=int(request["user_id"]),
            actor_id=int(user["id"]),
            module="member",
            action="join_rejected",
            title=f"「{_team_name(team_id)}」未通过你的加入申请",
            detail=payload.note.strip() or "团队管理员暂未通过你的加入申请，可补充信息后重新申请或联系团队负责人。",
            target_type="join_request",
            target_id=request_id,
            status="done",
            metadata={"request_id": request_id},
        )
    return row("SELECT * FROM team_join_requests WHERE id=?", (request_id,))


@router.patch("/{team_id}/members/{member_user_id}")
def update_member(team_id: int, member_user_id: int, payload: TeamMemberRoleRequest, user: CurrentUser) -> dict:
    actor = _require_role(team_id, user, "admin")
    target = row("SELECT * FROM team_members WHERE team_id=? AND user_id=?", (team_id, member_user_id))
    if not target:
        raise HTTPException(404, "成员不存在")
    if target["role"] == "owner" and actor["role"] != "owner":
        raise HTTPException(403, "不能修改负责人")
    if payload.role == "owner":
        if actor["role"] != "owner":
            raise HTTPException(403, "只有负责人可以转让负责人角色")
        if payload.status != "active":
            raise HTTPException(400, "负责人必须保持启用状态")
        with connection() as conn:
            conn.execute(
                "UPDATE team_members SET role='admin' WHERE team_id=? AND role='owner' AND user_id<>?",
                (team_id, member_user_id),
            )
            conn.execute(
                "UPDATE team_members SET role='owner',status='active' WHERE team_id=? AND user_id=?",
                (team_id, member_user_id),
            )
            conn.execute("UPDATE teams SET owner_id=? WHERE id=?", (member_user_id, team_id))
        _member_log(team_id, int(user["id"]), member_user_id, "owner_transfer", "转让团队负责人")
        _notify_team_members(
            team_id,
            actor_id=int(user["id"]),
            module="member",
            action="owner_transfer",
            title=f"「{_team_name(team_id)}」负责人已转让",
            detail=f"{user['nickname']} 已将团队负责人转让给用户 {member_user_id}，团队管理权限已同步。",
            target_type="member",
            target_id=member_user_id,
            metadata={"new_owner_id": member_user_id},
        )
        return {"ok": True, "role": "owner"}
    if target["role"] == "owner":
        raise HTTPException(409, "请先把负责人转让给其他成员")
    if payload.role == "admin" and actor["role"] != "owner":
        raise HTTPException(403, "只有负责人可以授予管理员角色")
    execute(
        "UPDATE team_members SET role=?,status=? WHERE team_id=? AND user_id=?",
        (payload.role, payload.status, team_id, member_user_id),
    )
    _member_log(team_id, int(user["id"]), member_user_id, "member_update", f"角色改为{ROLE_LABELS[payload.role]}，状态为{payload.status}")
    _notify_team_member(
        team_id=team_id,
        user_id=member_user_id,
        actor_id=int(user["id"]),
        module="member",
        action="member_update",
        title=f"你在「{_team_name(team_id)}」的权限已调整",
        detail=f"当前角色为 {ROLE_LABELS.get(payload.role, payload.role)}，账号状态为 {payload.status}。个人端可用操作将按新权限刷新。",
        target_type="member",
        target_id=member_user_id,
        metadata={"role": payload.role, "status": payload.status},
    )
    return {"ok": True}


@router.delete("/{team_id}/members/{member_user_id}", status_code=204)
def remove_member(team_id: int, member_user_id: int, user: CurrentUser):
    actor = _require_role(team_id, user, "admin")
    target = row("SELECT * FROM team_members WHERE team_id=? AND user_id=?", (team_id, member_user_id))
    if not target:
        raise HTTPException(404, "成员不存在")
    if target["role"] == "owner" or (actor["role"] != "owner" and target["role"] == "admin"):
        raise HTTPException(403, "当前角色不能移出该成员")
    execute("DELETE FROM team_members WHERE team_id=? AND user_id=?", (team_id, member_user_id))
    _member_log(team_id, int(user["id"]), member_user_id, "member_remove", "移出团队")
    _notify_team_member(
        team_id=team_id,
        user_id=member_user_id,
        actor_id=int(user["id"]),
        module="member",
        action="member_remove",
        title=f"你已被移出「{_team_name(team_id)}」",
        detail="团队管理员已回收你的团队访问权限，个人端将不再展示该团队的可操作空间。",
        target_type="member",
        target_id=member_user_id,
        status="done",
    )


@router.post("/{team_id}/members/{member_user_id}/transfer")
def transfer_member_materials(
    team_id: int,
    member_user_id: int,
    payload: TeamMaterialTransferRequest,
    user: CurrentUser,
) -> dict:
    _require_role(team_id, user, "admin")
    source = row("SELECT * FROM team_members WHERE team_id=? AND user_id=?", (team_id, member_user_id))
    if not source:
        raise HTTPException(404, "源成员不存在")
    target_user_id = payload.target_user_id or int(_team(team_id)["owner_id"])
    target = row("SELECT * FROM team_members WHERE team_id=? AND user_id=? AND status='active'", (team_id, target_user_id))
    if not target:
        raise HTTPException(404, "移交目标成员不存在")
    changed = execute(
        "UPDATE team_materials SET uploader_id=?,updated_at=? WHERE team_id=? AND uploader_id=?",
        (target_user_id, utcnow(), team_id, member_user_id),
    )
    _member_log(team_id, int(user["id"]), member_user_id, "material_transfer", f"素材批量移交给用户{target_user_id}")
    _notify_team_member(
        team_id=team_id,
        user_id=member_user_id,
        actor_id=int(user["id"]),
        module="member",
        action="material_transfer_out",
        title=f"你在「{_team_name(team_id)}」的素材已移交",
        detail=f"管理员已将你名下团队素材批量移交给用户 {target_user_id}。",
        target_type="member",
        target_id=member_user_id,
        status="done",
        metadata={"target_user_id": target_user_id, "transferred": changed},
    )
    if target_user_id != member_user_id:
        _notify_team_member(
            team_id=team_id,
            user_id=target_user_id,
            actor_id=int(user["id"]),
            module="member",
            action="material_transfer_in",
            title=f"「{_team_name(team_id)}」素材已移交给你",
            detail=f"管理员已将用户 {member_user_id} 名下团队素材批量移交给你，请在个人端或团队端确认团队素材状态。",
            target_type="member",
            target_id=member_user_id,
            status="pending",
            metadata={"source_user_id": member_user_id, "transferred": changed},
        )
    return {"ok": True, "transferred": changed, "target_user_id": target_user_id}


@router.get("/{team_id}/invites")
def list_invites(team_id: int, user: CurrentUser) -> dict:
    _require_role(team_id, user, "admin")
    invites = rows(
        "SELECT i.*,u.nickname creator_name FROM team_invites i JOIN users u ON u.id=i.created_by WHERE i.team_id=? ORDER BY i.id DESC",
        (team_id,),
    )
    return {"items": invites}


@router.post("/{team_id}/invites", status_code=201)
def create_invite(team_id: int, payload: TeamInviteRequest, user: CurrentUser) -> dict:
    _require_role(team_id, user, "admin")
    if payload.role == "admin" and _membership(team_id, int(user["id"]))["role"] != "owner":
        raise HTTPException(403, "只有负责人可以生成管理员邀请码")
    code = secrets.token_hex(3).upper()
    while row("SELECT id FROM team_invites WHERE code=?", (code,)):
        code = secrets.token_hex(3).upper()
    invite_id = execute(
        "INSERT INTO team_invites(team_id,created_by,code,role,expires_at,created_at) VALUES(?,?,?,?,?,?)",
        (team_id, int(user["id"]), code, payload.role, _future(payload.expires_days), utcnow()),
    )
    _member_log(team_id, int(user["id"]), None, "invite_create", f"创建{ROLE_LABELS[payload.role]}邀请码")
    return row("SELECT * FROM team_invites WHERE id=?", (invite_id,))


@router.delete("/{team_id}/invites/{invite_id}", status_code=204, response_class=Response)
def revoke_invite(team_id: int, invite_id: int, user: CurrentUser):
    _require_role(team_id, user, "admin")
    invite = row("SELECT * FROM team_invites WHERE team_id=? AND id=?", (team_id, invite_id))
    if not invite:
        raise HTTPException(404, "邀请码不存在")
    execute("UPDATE team_invites SET status='revoked' WHERE team_id=? AND id=?", (team_id, invite_id))
    _member_log(team_id, int(user["id"]), None, "invite_revoke", f"停用邀请码 {invite['code']}")
    return Response(status_code=204)


@router.get("/{team_id}/libraries")
def list_libraries(team_id: int, user: CurrentUser) -> dict:
    member = _membership(team_id, int(user["id"]))
    items = rows("SELECT * FROM team_knowledge_libs WHERE team_id=? ORDER BY id DESC", (team_id,))
    if member["role"] not in {"owner", "admin"}:
        items = [item for item in items if item["id"] in _visible_library_ids(team_id, int(user["id"]))]
    for item in items:
        item["member_permissions"] = rows(
            "SELECT lm.user_id,lm.access,u.nickname FROM team_library_members lm JOIN users u ON u.id=lm.user_id WHERE lm.lib_id=?",
            (item["id"],),
        )
    return {"items": items}


@router.post("/{team_id}/libraries", status_code=201)
def create_library(team_id: int, payload: TeamLibraryRequest, user: CurrentUser) -> dict:
    _require_role(team_id, user, "admin")
    dataset_key = f"team_{team_id}_{secrets.token_hex(5)}"
    lib_id = execute(
        "INSERT INTO team_knowledge_libs(team_id,name,description,category,dataset_key,visibility,permission_mode,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (team_id, payload.name.strip(), payload.description.strip(), payload.category, dataset_key, payload.visibility, payload.permission_mode, int(user["id"]), utcnow()),
    )
    _log(team_id, int(user["id"]), "library", "create", f"创建团队知识库 {payload.name}")
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="library",
        action="create",
        title=f"「{_team_name(team_id)}」新增知识库",
        detail=f"团队管理员创建了知识库「{payload.name.strip()}」，可见成员可以在个人端查看基础信息。",
        exclude_user_id=int(user["id"]),
        target_type="library",
        target_id=lib_id,
    )
    return row("SELECT * FROM team_knowledge_libs WHERE id=?", (lib_id,))


@router.patch("/{team_id}/libraries/{lib_id}")
def update_library(team_id: int, lib_id: int, payload: TeamLibraryUpdateRequest, user: CurrentUser) -> dict:
    _require_role(team_id, user, "admin")
    _library(team_id, lib_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return _library(team_id, lib_id)
    assignments = ",".join(f"{key}=?" for key in updates)
    execute(
        f"UPDATE team_knowledge_libs SET {assignments} WHERE team_id=? AND id=?",
        (*tuple(updates.values()), team_id, lib_id),
    )
    _log(team_id, int(user["id"]), "library", "update", f"更新团队知识库 #{lib_id}")
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="library",
        action="update",
        title=f"「{_team_name(team_id)}」知识库已更新",
        detail=f"团队管理员更新了知识库 #{lib_id} 的名称、可见范围或权限策略。",
        exclude_user_id=int(user["id"]),
        target_type="library",
        target_id=lib_id,
    )
    return _library(team_id, lib_id)


@router.delete("/{team_id}/libraries/{lib_id}", status_code=204, response_class=Response)
def delete_library(team_id: int, lib_id: int, user: CurrentUser):
    _require_role(team_id, user, "admin")
    _library(team_id, lib_id)
    with connection() as conn:
        conn.execute("UPDATE team_materials SET lib_id=NULL,updated_at=? WHERE team_id=? AND lib_id=?", (utcnow(), team_id, lib_id))
        conn.execute("DELETE FROM team_library_members WHERE team_id=? AND lib_id=?", (team_id, lib_id))
        conn.execute("DELETE FROM team_knowledge_libs WHERE team_id=? AND id=?", (team_id, lib_id))
    _log(team_id, int(user["id"]), "library", "delete", f"删除团队知识库 #{lib_id}，素材已保留为未归属")
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="library",
        action="delete",
        title=f"「{_team_name(team_id)}」知识库已删除",
        detail=f"团队管理员删除了知识库 #{lib_id}，原有素材已保留为未归属团队素材。",
        exclude_user_id=int(user["id"]),
        target_type="library",
        target_id=lib_id,
        status="done",
    )
    return Response(status_code=204)


@router.put("/{team_id}/libraries/{lib_id}/members/{member_user_id}")
def update_library_member(
    team_id: int,
    lib_id: int,
    member_user_id: int,
    payload: TeamLibraryMemberRequest,
    user: CurrentUser,
) -> dict:
    _require_role(team_id, user, "admin")
    _library(team_id, lib_id)
    if not row("SELECT id FROM team_members WHERE team_id=? AND user_id=? AND status='active'", (team_id, member_user_id)):
        raise HTTPException(404, "团队成员不存在")
    with connection() as conn:
        existing = conn.execute("SELECT id FROM team_library_members WHERE lib_id=? AND user_id=?", (lib_id, member_user_id)).fetchone()
        if existing:
            conn.execute("UPDATE team_library_members SET access=? WHERE id=?", (payload.access, existing["id"]))
        else:
            conn.execute(
                "INSERT INTO team_library_members(team_id,lib_id,user_id,access,created_at) VALUES(?,?,?,?,?)",
                (team_id, lib_id, member_user_id, payload.access, utcnow()),
            )
    _log(team_id, int(user["id"]), "library", "permission", f"更新知识库{lib_id}成员权限")
    _notify_team_member(
        team_id=team_id,
        user_id=member_user_id,
        actor_id=int(user["id"]),
        module="library",
        action="permission",
        title=f"你在「{_team_name(team_id)}」的知识库权限已更新",
        detail=f"管理员已将知识库 #{lib_id} 对你的访问权限设置为 {payload.access}。",
        target_type="library",
        target_id=lib_id,
        metadata={"access": payload.access},
    )
    return {"ok": True, "lib_id": lib_id, "user_id": member_user_id, "access": payload.access}


@router.delete("/{team_id}/libraries/{lib_id}/members/{member_user_id}", status_code=204, response_class=Response)
def remove_library_member(team_id: int, lib_id: int, member_user_id: int, user: CurrentUser):
    _require_role(team_id, user, "admin")
    _library(team_id, lib_id)
    execute("DELETE FROM team_library_members WHERE team_id=? AND lib_id=? AND user_id=?", (team_id, lib_id, member_user_id))
    _log(team_id, int(user["id"]), "library", "permission_remove", f"移除知识库 #{lib_id} 成员 {member_user_id} 的自定义权限")
    _notify_team_member(
        team_id=team_id,
        user_id=member_user_id,
        actor_id=int(user["id"]),
        module="library",
        action="permission_remove",
        title=f"你在「{_team_name(team_id)}」的知识库自定义权限已移除",
        detail=f"管理员已移除知识库 #{lib_id} 对你的自定义权限，后续访问将按团队默认权限策略判定。",
        target_type="library",
        target_id=lib_id,
        status="done",
    )
    return Response(status_code=204)


@router.get("/{team_id}/materials")
def list_team_materials(team_id: int, user: CurrentUser, lib_id: int | None = None, q: str = "") -> dict:
    where, params = _material_scope_sql(team_id, int(user["id"]), lib_id)
    if q.strip():
        where += " AND (m.name LIKE ? OR m.content LIKE ?)"
        params.extend([f"%{q.strip()}%", f"%{q.strip()}%"])
    items = rows(
        f"SELECT m.*,u.nickname,u.username,u.avatar,l.name lib_name FROM team_materials m "
        f"JOIN users u ON u.id=m.uploader_id LEFT JOIN team_knowledge_libs l ON l.id=m.lib_id "
        f"WHERE {where} ORDER BY m.id DESC",
        tuple(params),
    )
    return {"items": [_serialize_material(item) for item in items]}


@router.post("/{team_id}/materials", status_code=201)
def create_team_material(team_id: int, payload: TeamMaterialRequest, user: CurrentUser) -> dict:
    _require_role(team_id, user, "editor")
    if payload.lib_id is not None:
        _library_access(team_id, payload.lib_id, int(user["id"]), write=True)
    material_id = _insert_material(
        team_id=team_id,
        lib_id=payload.lib_id,
        user_id=int(user["id"]),
        name=payload.name.strip(),
        source="manual",
        kind=payload.kind,
        content=payload.content,
        tags=payload.tags,
    )
    credit_team(
        team_id,
        "knowledge",
        5,
        reason_code="team_material_create",
        reason="成员创建团队知识素材奖励",
        idempotency_key=f"team:material:{material_id}:create",
        reference_type="team_material",
        reference_id=str(material_id),
        user_id=int(user["id"]),
    )
    _log(team_id, int(user["id"]), "material", "create", f"新增团队素材 {payload.name}")
    return row("SELECT * FROM team_materials WHERE id=?", (material_id,))


@router.post("/{team_id}/materials/upload", status_code=201)
async def upload_team_material(
    team_id: int,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    file: UploadFile = File(...),
    lib_id: int | None = Form(None),
    name: str = Form(""),
    tags: str = Form(""),
) -> dict:
    member = _require_role(team_id, user, "editor")
    if lib_id is not None:
        _library_access(team_id, lib_id, int(user["id"]), write=True)
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "团队素材超过大小限制")
    filename = Path(file.filename or "team-material").name
    extension = Path(filename).suffix.lower()
    if extension in TEXT_EXTENSIONS:
        kind = "文档"
        initial_content = data.decode("utf-8", errors="replace")
    elif extension in IMAGE_EXTENSIONS:
        kind = "图片"
        initial_content = ""
    elif extension in VIDEO_EXTENSIONS:
        kind = "视频"
        initial_content = ""
    else:
        kind = "文件"
        initial_content = ""
    media_quota = quota_status("team", team_id, "team_media")
    if media_quota["free_remaining"] <= 0 and member["role"] not in {"owner", "admin"}:
        raise HTTPException(403, "团队免费媒体处理额度已用尽，只有管理员或负责人可以继续消耗团队公共资金")
    quota = consume_team_quota(
        team_id,
        "team_media",
        user_id=int(user["id"]),
        idempotency_key=f"team:media:{team_id}:{secrets.token_hex(12)}",
        reference_type="team_material",
        reference_id=filename,
    )
    target_dir = settings.upload_dir / "teams" / str(team_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{secrets.token_hex(12)}{extension}"
    target.write_bytes(data)
    material_id = _insert_material(
        team_id=team_id,
        lib_id=lib_id,
        user_id=int(user["id"]),
        name=(name.strip() or filename),
        source="upload",
        kind=kind,
        content=initial_content,
        tags=[item.strip() for item in tags.replace("，", ",").split(",")],
        status="processing",
        file_path=str(target.relative_to(settings.upload_dir)),
    )
    task_id = execute(
        "INSERT INTO team_sandbox_tasks(team_id,task_type,routing_key,status,detail,created_at) VALUES(?,?,?,?,?,?)",
        (team_id, "media_ingest", f"team.media.{team_id}", "queued", f"素材{material_id}等待 RabbitMQ/MCP/OCR/转写处理", utcnow()),
    )
    published = False
    try:
        published = rabbitmq_publish(
            f"team.media.{team_id}",
            {"team_id": team_id, "material_id": material_id, "task_id": task_id, "kind": kind, "source": "upload"},
        )
    except Exception:
        published = False
    if published:
        execute(
            "UPDATE team_sandbox_tasks SET detail=? WHERE id=?",
            (f"素材{material_id}已投递团队 RabbitMQ 队列，等待 OCR/转写处理", task_id),
        )
    background_tasks.add_task(_finish_media_ingest, team_id, material_id, task_id, int(user["id"]), kind, initial_content)
    _log(team_id, int(user["id"]), "material", "upload", f"上传团队素材 {filename}，进入异步处理队列")
    return {
        **row("SELECT * FROM team_materials WHERE id=?", (material_id,)),
        "task_id": task_id,
        "status": "processing",
        "queue": f"team.media.{team_id}",
        "published": published,
        "currency": {"charged": quota.get("charged", 0), "currency": "knowledge"},
    }


@router.post("/{team_id}/materials/import-personal", status_code=201)
def import_personal_material(team_id: int, payload: TeamPersonalMaterialImportRequest, user: CurrentUser) -> dict:
    _require_role(team_id, user, "editor")
    if payload.lib_id is not None:
        _library_access(team_id, payload.lib_id, int(user["id"]), write=True)
    personal = row(
        "SELECT * FROM materials WHERE id=? AND user_id=?",
        (payload.material_id, int(user["id"])),
    )
    if not personal:
        raise HTTPException(404, "个人素材不存在或不属于当前用户")

    content = (personal.get("content") or "").strip()
    source_path = _upload_storage_path(personal.get("file_path"))
    copied_file_path = ""
    copied_size: int | None = None
    if source_path and source_path.is_file():
        target_dir = settings.upload_dir / "teams" / str(team_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        extension = source_path.suffix or Path(personal.get("name") or "").suffix
        target = target_dir / f"{secrets.token_hex(12)}{extension}"
        shutil.copy2(source_path, target)
        copied_file_path = str(target.relative_to(settings.upload_dir))
        copied_size = target.stat().st_size

    if not content:
        if copied_file_path:
            content = f"从个人素材「{personal['name']}」导入，原文件已复制到团队素材库。"
        else:
            raise HTTPException(409, "个人素材没有可导入内容或可复制文件")

    tags = _clean_tags([*payload.tags, personal.get("category") or ""])
    material_name = (payload.name or personal["name"]).strip()
    material_id = _insert_material(
        team_id=team_id,
        lib_id=payload.lib_id,
        user_id=int(user["id"]),
        name=material_name,
        source="personal_import",
        kind=personal.get("kind") or "File",
        content=content,
        tags=tags,
        status="ready",
        file_path=copied_file_path,
        origin_url=personal.get("origin_url") or "",
        size=copied_size if copied_size is not None else int(personal.get("size") or 0) or None,
    )
    credit_team(
        team_id,
        "knowledge",
        5,
        reason_code="team_personal_import",
        reason="从个人空间导入团队素材奖励",
        idempotency_key=f"team:material:{material_id}:personal-import",
        reference_type="team_material",
        reference_id=str(material_id),
        user_id=int(user["id"]),
    )
    _log(team_id, int(user["id"]), "material", "import_personal", f"从个人素材导入 {personal['name']}")
    return row("SELECT * FROM team_materials WHERE id=?", (material_id,))


@router.post("/{team_id}/materials/url", status_code=201)
async def create_team_url_material(team_id: int, payload: TeamMaterialUrlRequest, user: CurrentUser) -> dict:
    _require_role(team_id, user, "editor")
    if payload.lib_id is not None:
        _library_access(team_id, payload.lib_id, int(user["id"]), write=True)
    content = payload.content or f"网页链接：{payload.url}\n\n当前环境未配置网页抓取 MCP，已先保存链接，可在团队端重新触发处理。"
    material_id = _insert_material(
        team_id=team_id,
        lib_id=payload.lib_id,
        user_id=int(user["id"]),
        name=payload.name.strip(),
        source="url",
        kind="网页",
        content=content,
        tags=payload.tags,
        origin_url=payload.url,
    )
    credit_team(
        team_id,
        "knowledge",
        4,
        reason_code="team_url_ingest",
        reason="保存团队网页素材奖励",
        idempotency_key=f"team:material:{material_id}:url",
        reference_type="team_material",
        reference_id=str(material_id),
        user_id=int(user["id"]),
    )
    _log(team_id, int(user["id"]), "material", "url_ingest", f"保存团队网页素材 {payload.url}")
    return row("SELECT * FROM team_materials WHERE id=?", (material_id,))


@router.get("/{team_id}/materials/{material_id}/status")
def team_material_status(team_id: int, material_id: int, user: CurrentUser) -> dict:
    item = _material(team_id, material_id, int(user["id"]))
    task = row(
        "SELECT * FROM team_sandbox_tasks WHERE team_id=? AND task_type='media_ingest' AND detail LIKE ? ORDER BY id DESC LIMIT 1",
        (team_id, f"%{material_id}%"),
    )
    return {"id": material_id, "status": item["status"], "updated_at": item["updated_at"], "task": task}


@router.patch("/{team_id}/materials/{material_id}")
def update_team_material(
    team_id: int,
    material_id: int,
    payload: TeamMaterialUpdateRequest,
    user: CurrentUser,
) -> dict:
    item = _material(team_id, material_id, int(user["id"]), write=True)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return item
    content = updates.get("content", item["content"] or "")
    tags = updates.get("tags", _json(item.get("tags"), []))
    name = updates.get("name", item["name"])
    version = row("SELECT COALESCE(MAX(version),0)+1 value FROM team_material_versions WHERE material_id=?", (material_id,))["value"]
    with connection() as conn:
        conn.execute(
            "UPDATE team_materials SET name=?,content=?,tags=?,size=?,updated_at=? WHERE team_id=? AND id=?",
            (name, content, json.dumps(_clean_tags(tags), ensure_ascii=False), len(content.encode("utf-8")), utcnow(), team_id, material_id),
        )
        conn.execute(
            "INSERT INTO team_material_versions(material_id,team_id,user_id,version,content,note,created_at) VALUES(?,?,?,?,?,?,?)",
            (material_id, team_id, int(user["id"]), version, content, payload.note or "团队成员编辑", utcnow()),
        )
    _log(team_id, int(user["id"]), "material", "update", f"更新团队素材 #{material_id}，生成版本{version}")
    return row("SELECT * FROM team_materials WHERE id=?", (material_id,))


@router.delete("/{team_id}/materials/{material_id}", status_code=204, response_class=Response)
def delete_team_material(team_id: int, material_id: int, user: CurrentUser):
    item = _material(team_id, material_id, int(user["id"]), write=True)
    with connection() as conn:
        conn.execute("DELETE FROM team_material_comments WHERE team_id=? AND material_id=?", (team_id, material_id))
        conn.execute("DELETE FROM team_material_versions WHERE team_id=? AND material_id=?", (team_id, material_id))
        conn.execute("DELETE FROM team_materials WHERE team_id=? AND id=?", (team_id, material_id))
    _log(team_id, int(user["id"]), "material", "delete", f"删除团队素材 {item['name']}")
    return Response(status_code=204)


@router.get("/{team_id}/materials/{material_id}/comments")
def list_material_comments(team_id: int, material_id: int, user: CurrentUser) -> dict:
    _material(team_id, material_id, int(user["id"]))
    items = rows(
        "SELECT c.*,u.nickname,u.username,u.avatar FROM team_material_comments c JOIN users u ON u.id=c.user_id "
        "WHERE c.team_id=? AND c.material_id=? ORDER BY c.id ASC",
        (team_id, material_id),
    )
    return {"items": items}


@router.post("/{team_id}/materials/{material_id}/comments", status_code=201)
def create_material_comment(team_id: int, material_id: int, payload: TeamMaterialCommentRequest, user: CurrentUser) -> dict:
    _material(team_id, material_id, int(user["id"]))
    comment_id = execute(
        "INSERT INTO team_material_comments(material_id,team_id,user_id,body,created_at) VALUES(?,?,?,?,?)",
        (material_id, team_id, int(user["id"]), payload.body.strip(), utcnow()),
    )
    _log(team_id, int(user["id"]), "material", "comment", f"批注素材 #{material_id}")
    return row("SELECT * FROM team_material_comments WHERE id=?", (comment_id,))


@router.patch("/{team_id}/materials/{material_id}/comments/{comment_id}")
def resolve_material_comment(
    team_id: int,
    material_id: int,
    comment_id: int,
    payload: TeamMaterialCommentResolveRequest,
    user: CurrentUser,
) -> dict:
    _material(team_id, material_id, int(user["id"]))
    comment = row(
        "SELECT * FROM team_material_comments WHERE team_id=? AND material_id=? AND id=?",
        (team_id, material_id, comment_id),
    )
    if not comment:
        raise HTTPException(404, "批注不存在")
    member = _membership(team_id, int(user["id"]))
    if comment["user_id"] != int(user["id"]) and member["role"] not in {"owner", "admin", "editor"}:
        raise HTTPException(403, "当前角色不能处理该批注")
    execute("UPDATE team_material_comments SET resolved=? WHERE id=?", (int(payload.resolved), comment_id))
    return row("SELECT * FROM team_material_comments WHERE id=?", (comment_id,))


@router.get("/{team_id}/materials/{material_id}/versions")
def list_material_versions(team_id: int, material_id: int, user: CurrentUser) -> dict:
    _material(team_id, material_id, int(user["id"]))
    return {
        "items": rows(
            "SELECT v.*,u.nickname FROM team_material_versions v JOIN users u ON u.id=v.user_id "
            "WHERE v.team_id=? AND v.material_id=? ORDER BY v.version DESC",
            (team_id, material_id),
        )
    }


@router.post("/{team_id}/materials/batch-tags")
def batch_material_tags(team_id: int, payload: TeamMaterialTagRequest, user: CurrentUser) -> dict:
    _require_role(team_id, user, "editor")
    tags = _clean_tags(payload.tags)
    updated = 0
    for material_id in payload.material_ids:
        item = _material(team_id, material_id, int(user["id"]), write=True)
        current = _clean_tags([*(_json(item.get("tags"), [])), *tags])
        execute("UPDATE team_materials SET tags=?,updated_at=? WHERE team_id=? AND id=?", (json.dumps(current, ensure_ascii=False), utcnow(), team_id, material_id))
        updated += 1
    _log(team_id, int(user["id"]), "material", "batch_tags", f"批量更新{updated}条素材标签")
    return {"ok": True, "updated": updated, "tags": tags}


@router.get("/{team_id}/shares")
def list_team_shares(team_id: int, user: CurrentUser) -> dict:
    member = _membership(team_id, int(user["id"]))
    items = rows(
        "SELECT s.*,u.nickname creator_name,l.name lib_name FROM team_shares s "
        "JOIN users u ON u.id=s.created_by LEFT JOIN team_knowledge_libs l ON l.id=s.lib_id "
        "WHERE s.team_id=? ORDER BY s.id DESC",
        (team_id,),
    )
    result = []
    for item in items:
        audience = _json(item.get("audience_user_ids"), [])
        if audience and member["role"] not in {"owner", "admin"} and int(user["id"]) not in audience:
            continue
        item.pop("password_hash", None)
        item["audience_user_ids"] = audience
        result.append(item)
    return {"items": result}


@router.post("/{team_id}/shares", status_code=201)
def create_team_share(team_id: int, payload: TeamShareRequest, user: CurrentUser) -> dict:
    member = _require_role(team_id, user, "admin")
    team = _team(team_id)
    if payload.lib_id is not None:
        _library_access(team_id, payload.lib_id, int(user["id"]))
    audience = list(dict.fromkeys(payload.member_ids))
    for member_id in audience:
        if not row("SELECT id FROM team_members WHERE team_id=? AND user_id=? AND status='active'", (team_id, member_id)):
            raise HTTPException(404, f"指定成员{member_id}不存在")
    share_id = secrets.token_urlsafe(9)
    charge_key = f"team:share:{team_id}:{secrets.token_hex(12)}"
    debit_team(
        team_id,
        "knowledge",
        3,
        reason_code="team_share_create",
        reason="创建团队分享链接",
        idempotency_key=charge_key,
        reference_type="team_share",
        reference_id=share_id,
        user_id=int(user["id"]),
    )
    try:
        execute(
            "INSERT INTO team_shares(id,team_id,lib_id,created_by,name,description,scope,password_hash,expires_at,watermark,audience_user_ids,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                share_id,
                team_id,
                payload.lib_id,
                int(user["id"]),
                payload.name,
                payload.description,
                payload.scope,
                hash_password(payload.password) if payload.password else None,
                _future(payload.expires_days),
                int(payload.watermark),
                json.dumps(audience),
                utcnow(),
            ),
        )
    except Exception:
        credit_team(
            team_id,
            "knowledge",
            3,
            reason_code="team_share_refund",
            reason="团队分享创建失败，退回学识币",
            idempotency_key=f"{charge_key}:refund",
            reference_type="team_share",
            reference_id=share_id,
            user_id=int(user["id"]),
        )
        raise
    _log(team_id, int(user["id"]), "share", "create", f"创建团队分享 {payload.name}")
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="share",
        action="create",
        title=f"「{_team_name(team_id)}」新增团队分享",
        detail=f"团队管理员创建了分享「{payload.name}」，外部访问收益会进入团队公共资金池。",
        recipient_ids=audience or None,
        exclude_user_id=int(user["id"]),
        target_type="share",
        target_id=share_id,
        metadata={"scope": payload.scope, "audience_user_ids": audience},
    )
    result = row("SELECT * FROM team_shares WHERE id=?", (share_id,))
    result.pop("password_hash", None)
    result["audience_user_ids"] = audience
    return result


@router.delete("/{team_id}/shares/{share_id}", status_code=204, response_class=Response)
def revoke_team_share(team_id: int, share_id: str, user: CurrentUser):
    _require_role(team_id, user, "admin")
    share = row("SELECT * FROM team_shares WHERE team_id=? AND id=?", (team_id, share_id))
    if not share:
        raise HTTPException(404, "团队分享不存在")
    execute("UPDATE team_shares SET status='revoked' WHERE team_id=? AND id=?", (team_id, share_id))
    _log(team_id, int(user["id"]), "share", "revoke", f"撤销团队分享 {share['name']}")
    audience = _json(share.get("audience_user_ids"), [])
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="share",
        action="revoke",
        title=f"「{_team_name(team_id)}」团队分享已撤销",
        detail=f"团队管理员撤销了分享「{share['name']}」，成员侧引用状态已同步。",
        recipient_ids=audience or None,
        exclude_user_id=int(user["id"]),
        target_type="share",
        target_id=share_id,
        status="done",
    )
    return Response(status_code=204)


@router.get("/{team_id}/qa/archive")
def list_team_qa_archive(
    team_id: int,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    q: str | None = Query(None, max_length=120),
    mine: bool = Query(False),
    lib_id: int | None = Query(None, gt=0),
) -> dict:
    member = _membership(team_id, int(user["id"]))
    params: list[Any] = [team_id]
    where = "q.team_id=?"
    if mine:
        where += " AND q.user_id=?"
        params.append(int(user["id"]))
    if q and q.strip():
        where += " AND (q.question LIKE ? OR q.answer LIKE ?)"
        pattern = f"%{q.strip()}%"
        params.extend([pattern, pattern])
    params.append(limit)
    items = rows(
        "SELECT q.*,u.nickname FROM team_qa_archives q JOIN users u ON u.id=q.user_id "
        f"WHERE {where} ORDER BY q.id DESC LIMIT ?",
        tuple(params),
    )
    serialized = [
        _serialize_qa_archive(item, current_user_id=int(user["id"]), role=member["role"])
        for item in items
    ]
    if lib_id is not None:
        if lib_id not in _visible_library_ids(team_id, int(user["id"])):
            raise HTTPException(403, "你没有该知识库的访问权限")
        serialized = [item for item in serialized if lib_id in item["lib_ids"]]
    return {
        "items": serialized,
        "filters": {"q": q or "", "mine": mine, "lib_id": lib_id},
        "quota": quota_status("team", team_id, "team_qa"),
    }


@router.get("/{team_id}/qa/archive/{archive_id}")
def get_team_qa_archive(team_id: int, archive_id: int, user: CurrentUser) -> dict:
    member = _membership(team_id, int(user["id"]))
    item = row(
        "SELECT q.*,u.nickname FROM team_qa_archives q JOIN users u ON u.id=q.user_id "
        "WHERE q.team_id=? AND q.id=?",
        (team_id, archive_id),
    )
    if not item:
        raise HTTPException(404, "团队问答归档不存在")
    return _serialize_qa_archive(item, current_user_id=int(user["id"]), role=member["role"])


@router.post("/{team_id}/qa", status_code=201)
def team_qa(team_id: int, payload: TeamQuestionRequest, user: CurrentUser) -> dict:
    return _create_team_qa_archive(team_id, payload, user)
    member = _membership(team_id, int(user["id"]))
    allowed = set(_visible_library_ids(team_id, int(user["id"])))
    lib_ids = payload.lib_ids or sorted(allowed)
    if any(lib_id not in allowed for lib_id in lib_ids):
        raise HTTPException(403, "问答范围包含你无权访问的知识库")
    quota_state = quota_status("team", team_id, "team_qa")
    if quota_state["free_remaining"] <= 0 and member["role"] not in {"owner", "admin"}:
        raise HTTPException(403, "团队免费问答额度已用尽，只有管理员或负责人可以消耗团队公共资金")
    quota = consume_team_quota(
        team_id,
        "team_qa",
        user_id=int(user["id"]),
        idempotency_key=f"team:qa:{team_id}:{secrets.token_hex(12)}",
        reference_type="team_qa",
        reference_id=team_id,
    )
    terms = [term.strip() for term in payload.question.split() if term.strip()]
    params: list[Any] = [team_id]
    where = "m.team_id=? AND m.status='ready'"
    if lib_ids:
        where += f" AND (m.lib_id IS NULL OR m.lib_id IN ({','.join('?' for _ in lib_ids)}))"
        params.extend(lib_ids)
    if terms:
        conditions = []
        for term in terms[:8]:
            conditions.append("(m.name LIKE ? OR m.content LIKE ?)")
            params.extend([f"%{term}%", f"%{term}%"])
        where += " AND (" + " OR ".join(conditions) + ")"
    material_items = rows(
        f"SELECT m.id,m.name,m.content,m.lib_id,l.name lib_name,u.nickname uploader_name "
        f"FROM team_materials m LEFT JOIN team_knowledge_libs l ON l.id=m.lib_id "
        f"JOIN users u ON u.id=m.uploader_id WHERE {where} ORDER BY m.updated_at DESC LIMIT 6",
        tuple(params),
    )
    if not material_items and lib_ids:
        material_items = rows(
            f"SELECT m.id,m.name,m.content,m.lib_id,l.name lib_name,u.nickname uploader_name "
            f"FROM team_materials m LEFT JOIN team_knowledge_libs l ON l.id=m.lib_id "
            f"JOIN users u ON u.id=m.uploader_id WHERE m.team_id=? AND m.status='ready' "
            f"AND (m.lib_id IS NULL OR m.lib_id IN ({','.join('?' for _ in lib_ids)})) ORDER BY m.updated_at DESC LIMIT 4",
            (team_id, *lib_ids),
        )
    sources = [
        {
            "material_id": item["id"],
            "name": item["name"],
            "library": item["lib_name"] or "未归属知识库",
            "uploader": item["uploader_name"],
            "snippet": (item["content"] or "")[:600],
        }
        for item in material_items
    ]
    if sources:
        answer = "基于团队知识库检索到以下参考内容：\n\n" + "\n\n".join(
            f"【{source['name']} / {source['library']}】\n{source['snippet']}" for source in sources
        )
        mode = "team-local-fallback"
    else:
        answer = "当前授权的团队知识库中没有检索到相关内容，请先上传素材或调整检索范围。"
        mode = "team-no-match"
    archive_id = execute(
        "INSERT INTO team_qa_archives(team_id,user_id,question,answer,sources,lib_ids,created_at) VALUES(?,?,?,?,?,?,?)",
        (team_id, int(user["id"]), payload.question, answer, json.dumps(sources, ensure_ascii=False), json.dumps(lib_ids), utcnow()),
    )
    _log(team_id, int(user["id"]), "qa", "ask", f"团队问答 #{archive_id}")
    return {
        "id": archive_id,
        "question": payload.question,
        "answer": answer,
        "sources": sources,
        "mode": mode,
        "lib_ids": lib_ids,
        "currency": {
            "charged": quota.get("charged", 0),
            "currency": "knowledge",
        },
    }


@router.delete("/{team_id}/qa/archive/{archive_id}", status_code=204, response_class=Response)
def delete_team_qa_archive(team_id: int, archive_id: int, user: CurrentUser):
    member = _membership(team_id, int(user["id"]))
    item = row("SELECT * FROM team_qa_archives WHERE team_id=? AND id=?", (team_id, archive_id))
    if not item:
        raise HTTPException(404, "团队问答归档不存在")
    if int(item["user_id"]) != int(user["id"]) and member["role"] not in {"owner", "admin"}:
        raise HTTPException(403, "只能删除自己的归档，管理员可删除团队归档")
    execute("DELETE FROM team_qa_archives WHERE team_id=? AND id=?", (team_id, archive_id))
    _log(team_id, int(user["id"]), "qa", "delete", f"删除团队问答归档 #{archive_id}")
    return Response(status_code=204)


@router.get("/{team_id}/evolution")
def list_team_evolution(team_id: int, user: CurrentUser) -> dict:
    member = _membership(team_id, int(user["id"]))
    # 私有任务仅创建者和管理员可见
    if member["role"] in {"owner", "admin"}:
        tasks = rows(
            "SELECT t.*,u.nickname creator_name,l.name lib_name FROM team_evolution_tasks t "
            "JOIN users u ON u.id=t.created_by LEFT JOIN team_knowledge_libs l ON l.id=t.lib_id "
            "WHERE t.team_id=? ORDER BY t.id DESC",
            (team_id,),
        )
    else:
        tasks = rows(
            "SELECT t.*,u.nickname creator_name,l.name lib_name FROM team_evolution_tasks t "
            "JOIN users u ON u.id=t.created_by LEFT JOIN team_knowledge_libs l ON l.id=t.lib_id "
            "WHERE t.team_id=? AND (t.visibility='team' OR t.created_by=?) ORDER BY t.id DESC",
            (team_id, int(user["id"])),
        )
    review_map: dict[int, list[dict]] = {}
    for review in rows(
        "SELECT r.*,u.nickname reviewer_name FROM team_evolution_reviews r JOIN users u ON u.id=r.reviewer_id WHERE r.team_id=? ORDER BY r.id",
        (team_id,),
    ):
        review_map.setdefault(int(review["task_id"]), []).append(review)
    return {"items": [_serialize_task(task, review_map) for task in tasks]}



async def _run_team_auto_evolution(team_id: int, task_id: int, lib_id: int | None) -> None:
    """Background task: run AI evolution pipeline on team materials."""
    import os
    from datetime import datetime, timezone
    from .database import connection as _conn

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    proxy_url = os.getenv("DEEPSEEK_PROXY_URL", "")

    if not api_key:
        with _conn() as conn:
            conn.execute("UPDATE team_evolution_tasks SET status=?,progress=?,summary=? WHERE id=?",
                         ("needs_changes", 60, "AI 自动进化失败：未配置 DEEPSEEK_API_KEY", task_id))
        return

    # Fetch materials from the team library
    params: list = [team_id]
    where = "m.team_id=?"
    if lib_id is not None:
        where += " AND m.lib_id=?"
        params.append(lib_id)
    with _conn() as conn:
        materials = conn.execute(
            f"SELECT m.* FROM team_materials m WHERE {where} AND m.status='ready' ORDER BY m.id DESC LIMIT 5",
            tuple(params),
        ).fetchall()
    materials = [dict(m) for m in materials]

    if not materials:
        with _conn() as conn:
            conn.execute("UPDATE team_evolution_tasks SET status=?,progress=?,summary=?,finished_at=? WHERE id=?",
                         ("completed", 100, "自动进化完成：知识库中暂无可进化素材", datetime.now(timezone.utc).isoformat(), task_id))
        return

    evolved_count = 0
    errors: list[str] = []
    for material in materials:
        try:
            evolved_content, reason = await run_evolution_agents(
                material=material,
                api_key=api_key,
                base_url=base_url,
                model=model,
                proxy_url=proxy_url,
            )
            with _conn() as conn:
                ver = conn.execute("SELECT COALESCE(MAX(version),0)+1 value FROM team_material_versions WHERE material_id=?", (material["id"],)).fetchone()
                version_num = ver["value"] if ver else 1
                conn.execute(
                    "INSERT INTO team_material_versions(material_id,team_id,user_id,version,content,note,created_at) VALUES(?,?,?,?,?,?,?)",
                    (material["id"], team_id, material["uploader_id"], version_num, evolved_content,
                     f"AI 自动进化 v{version_num} — {reason}", datetime.now(timezone.utc).isoformat()),
                )
            evolved_count += 1
        except Exception as exc:
            errors.append(f"{material.get('name', '?')[:30]}: {str(exc)[:120]}")

    progress = min(100, int(evolved_count / max(len(materials), 1) * 100))
    status = "completed" if evolved_count > 0 else "needs_changes"
    summary_parts = [f"自动进化完成：处理 {evolved_count}/{len(materials)} 条素材"]
    if errors:
        summary_parts.append(f"跳过 {len(errors)} 条：" + "; ".join(errors[:3]))
    with _conn() as conn:
        conn.execute(
            "UPDATE team_evolution_tasks SET status=?,progress=?,summary=?,finished_at=? WHERE id=?",
            (status, progress, "。".join(summary_parts)[:2000],
             datetime.now(timezone.utc).isoformat(), task_id),
        )


@router.post("/{team_id}/evolution", status_code=201)
def create_team_evolution(
    team_id: int, payload: TeamEvolutionTaskRequest, user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> dict:
    member = _require_role(team_id, user, "admin")
    if payload.lib_id is not None:
        _library_access(team_id, payload.lib_id, int(user["id"]))
    team = _team(team_id)
    auto_mode = payload.mode == "auto"
    if auto_mode and member["role"] not in {"owner", "admin"}:
        raise HTTPException(403, "只有负责人或管理员可以启动自动进化")
    summary = payload.summary.strip() or "团队知识进化任务已创建，等待协同审核。"
    status = "processing" if auto_mode else "pending_review"
    progress = 0 if auto_mode else 35
    charge_key = f"team:evolution:{team_id}:{secrets.token_hex(12)}"
    debit_team(
        team_id,
        "truth",
        2 if auto_mode else 1,
        reason_code="team_evolution_charge",
        reason=f"启动团队{'自动' if auto_mode else '协同'}知识进化",
        idempotency_key=charge_key,
        reference_type="team_evolution",
        reference_id=team_id,
        metadata={"mode": payload.mode, "review_strategy": payload.review_strategy},
        user_id=int(user["id"]),
    )
    try:
        task_id = execute(
            "INSERT INTO team_evolution_tasks(team_id,lib_id,created_by,mode,visibility,status,review_strategy,progress,summary,created_at,finished_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (team_id, payload.lib_id, int(user["id"]), payload.mode, payload.visibility, status, payload.review_strategy, progress, summary, utcnow(), None),
        )
    except Exception:
        credit_team(
            team_id,
            "truth",
            2 if auto_mode else 1,
            reason_code="team_evolution_refund",
            reason="团队进化任务创建失败，退回真知晶",
            idempotency_key=f"{charge_key}:refund",
            reference_type="team_evolution",
            reference_id=team_id,
            user_id=int(user["id"]),
        )
        raise
    _log(team_id, int(user["id"]), "evolution", "create", f"发起团队{('自动' if auto_mode else '协同')}进化任务 #{task_id}")
    try:
        rabbitmq_publish(
            f"team.evolution.{team_id}",
            {"team_id": team_id, "task_id": task_id, "mode": payload.mode, "review_strategy": payload.review_strategy},
        )
    except Exception:
        pass
    if auto_mode:
        background_tasks.add_task(_run_team_auto_evolution, team_id, task_id, payload.lib_id)
        _log(team_id, int(user["id"]), "evolution", "auto_start", f"自动进化任务 #{task_id} 已加入 AI 处理队列")
        _notify_team_members(
            team_id,
            actor_id=int(user["id"]),
            module="evolution",
            action="processing",
            title=f"「{_team_name(team_id)}」AI 自动进化已启动",
            detail=f"自动进化任务 #{task_id} 正在后台处理，完成后将生成进化版本。",
            minimum_role="admin",
            exclude_user_id=int(user["id"]),
            target_type="evolution_task",
            target_id=task_id,
            metadata={"mode": payload.mode, "review_strategy": payload.review_strategy},
        )
    else:
        _notify_team_members(
            team_id,
            actor_id=int(user["id"]),
            module="evolution",
            action="review_requested",
            title=f"「{_team_name(team_id)}」有新的协同进化待审核",
            detail=f"进化任务 #{task_id} 已进入待审核状态，编辑及以上成员可在个人端提交审核意见。",
            minimum_role="editor",
            exclude_user_id=None,
            target_type="evolution_task",
            target_id=task_id,
            metadata={"mode": payload.mode, "review_strategy": payload.review_strategy},
        )
    return row("SELECT * FROM team_evolution_tasks WHERE id=?", (task_id,))


@router.post("/{team_id}/evolution/{task_id}/reviews", status_code=201)
def review_team_evolution(team_id: int, task_id: int, payload: TeamEvolutionReviewRequest, user: CurrentUser) -> dict:
    _require_role(team_id, user, "editor")
    task = row("SELECT * FROM team_evolution_tasks WHERE team_id=? AND id=?", (team_id, task_id))
    if not task:
        raise HTTPException(404, "进化任务不存在")
    if task["status"] == "completed":
        raise HTTPException(409, "该进化任务已经完成")
    existing = row("SELECT * FROM team_evolution_reviews WHERE task_id=? AND reviewer_id=?", (task_id, int(user["id"])))
    if existing:
        review_id = existing["id"]
        execute(
            "UPDATE team_evolution_reviews SET decision=?,feedback=?,created_at=? WHERE id=?",
            (payload.decision, payload.feedback, utcnow(), review_id),
        )
    else:
        review_id = execute(
            "INSERT INTO team_evolution_reviews(task_id,team_id,reviewer_id,decision,feedback,created_at) VALUES(?,?,?,?,?,?)",
            (task_id, team_id, int(user["id"]), payload.decision, payload.feedback, utcnow()),
        )
    credit_team(
        team_id,
        "knowledge",
        2,
        reason_code="team_evolution_review",
        reason="成员参与团队协同审核奖励",
        idempotency_key=f"team:evolution:{task_id}:review:{user['id']}",
        reference_type="team_evolution_review",
        reference_id=str(review_id),
        user_id=int(user["id"]),
    )
    completed_now = False
    if payload.decision in {"rejected", "needs_changes"}:
        execute("UPDATE team_evolution_tasks SET status='needs_changes',progress=60 WHERE id=?", (task_id,))
    else:
        reviewers = rows(
            "SELECT user_id,role FROM team_members WHERE team_id=? AND status='active' AND role IN ('owner','admin','editor')",
            (team_id,),
        )
        accepted = row(
            "SELECT COUNT(*) value FROM team_evolution_reviews WHERE task_id=? AND decision='accepted'",
            (task_id,),
        )["value"]
        owner_accepted = row(
            "SELECT id FROM team_evolution_reviews WHERE task_id=? AND reviewer_id=? AND decision='accepted'",
            (task_id, _team(team_id)["owner_id"]),
        )
        eligible = max(len(reviewers), 1)
        if task["review_strategy"] == "owner_final":
            should_complete = bool(owner_accepted)
        elif task["review_strategy"] == "all_agree":
            should_complete = accepted >= eligible
        else:
            should_complete = accepted >= math.ceil(eligible / 2)
        if should_complete:
            execute(
                "UPDATE team_evolution_tasks SET status='completed',progress=100,finished_at=? WHERE id=?",
                (utcnow(), task_id),
            )
            completed_now = True
    if completed_now:
        credit_team(
            team_id,
            "knowledge",
            10,
            reason_code="team_evolution_reward",
            reason="团队协同审核完成奖励",
            idempotency_key=f"team:evolution:{task_id}:complete",
            reference_type="team_evolution",
            reference_id=str(task_id),
            user_id=int(user["id"]),
        )
        _notify_team_members(
            team_id,
            actor_id=int(user["id"]),
            module="evolution",
            action="completed",
            title=f"「{_team_name(team_id)}」协同进化已完成",
            detail=f"进化任务 #{task_id} 已满足审核策略并完成，协作奖励已结算到团队公共资金池。",
            minimum_role="editor",
            target_type="evolution_task",
            target_id=task_id,
            status="done",
        )
    elif payload.decision in {"rejected", "needs_changes"}:
        _notify_team_member(
            team_id=team_id,
            user_id=int(task["created_by"]),
            actor_id=int(user["id"]),
            module="evolution",
            action="needs_changes",
            title=f"「{_team_name(team_id)}」进化任务需要调整",
            detail=f"成员 {user['nickname']} 对任务 #{task_id} 提交了 {payload.decision}，反馈：{payload.feedback or '无补充说明'}",
            target_type="evolution_task",
            target_id=task_id,
            metadata={"decision": payload.decision, "feedback": payload.feedback},
        )
    else:
        _notify_team_member(
            team_id=team_id,
            user_id=int(task["created_by"]),
            actor_id=int(user["id"]),
            module="evolution",
            action="review_submitted",
            title=f"「{_team_name(team_id)}」进化任务收到审核",
            detail=f"成员 {user['nickname']} 已接受任务 #{task_id} 的进化建议，系统将继续等待审核策略达成。",
            target_type="evolution_task",
            target_id=task_id,
            metadata={"decision": payload.decision},
        )
    _log(team_id, int(user["id"]), "evolution", "review", f"{payload.decision} 团队进化任务 #{task_id}")
    return row("SELECT * FROM team_evolution_reviews WHERE id=?", (review_id,))


@router.post("/{team_id}/evolution/{task_id}/regenerate")
def regenerate_team_evolution(team_id: int, task_id: int, user: CurrentUser) -> dict:
    _require_role(team_id, user, "editor")
    task = row("SELECT * FROM team_evolution_tasks WHERE team_id=? AND id=?", (team_id, task_id))
    if not task:
        raise HTTPException(404, "进化任务不存在")
    if task["status"] == "completed":
        raise HTTPException(409, "已完成任务不能重新生成")
    execute(
        "UPDATE team_evolution_tasks SET status='pending_review',progress=35,summary=?,finished_at=NULL WHERE id=?",
        (f"{task['summary']} 已根据团队反馈重新生成。", task_id),
    )
    _log(team_id, int(user["id"]), "evolution", "regenerate", f"重新生成团队进化任务 #{task_id}")
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="evolution",
        action="review_requested",
        title=f"「{_team_name(team_id)}」进化任务已重新生成",
        detail=f"进化任务 #{task_id} 已根据团队反馈重新生成，请编辑及以上成员重新审核。",
        minimum_role="editor",
        target_type="evolution_task",
        target_id=task_id,
        metadata={"regenerated": True},
    )
    return row("SELECT * FROM team_evolution_tasks WHERE id=?", (task_id,))


@router.patch("/{team_id}/evolution/{task_id}")
def update_team_evolution(
    team_id: int, task_id: int, payload: TeamEvolutionTaskUpdateRequest, user: CurrentUser,
) -> dict:
    _require_role(team_id, user, "admin")
    task = row("SELECT * FROM team_evolution_tasks WHERE team_id=? AND id=?", (team_id, task_id))
    if not task:
        raise HTTPException(404, "进化任务不存在")
    if task["status"] == "completed":
        raise HTTPException(409, "已完成任务不能修改")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return task
    assignments = ",".join(f"{key}=?" for key in updates)
    execute(
        f"UPDATE team_evolution_tasks SET {assignments} WHERE team_id=? AND id=?",
        (*tuple(updates.values()), team_id, task_id),
    )
    _log(team_id, int(user["id"]), "evolution", "update", f"更新团队进化任务 #{task_id}")
    return row("SELECT * FROM team_evolution_tasks WHERE id=?", (task_id,))


@router.get("/{team_id}/games/rank")
def team_game_rank(team_id: int, user: CurrentUser, period: str = Query("all", pattern="^(day|week|all)$")) -> dict:
    _membership(team_id, int(user["id"]))
    cutoff = _now_cutoff(period)
    params: list[Any] = [team_id]
    where = "r.team_id=?"
    if cutoff:
        where += " AND r.created_at>=?"
        params.append(cutoff)
    items = rows(
        f"SELECT r.user_id,u.nickname,SUM(r.score) score,SUM(r.correct) correct,SUM(r.total) total,COUNT(*) sessions "
        f"FROM team_game_rank r JOIN users u ON u.id=r.user_id WHERE {where} "
        f"GROUP BY r.user_id,u.nickname ORDER BY score DESC",
        tuple(params),
    )
    return {"period": period, "items": items}


@router.post("/{team_id}/games/score", status_code=201)
def submit_team_game_score(team_id: int, payload: TeamGameScoreRequest, user: CurrentUser) -> dict:
    _membership(team_id, int(user["id"]))
    if payload.correct > payload.total:
        raise HTTPException(422, "答对题数不能超过总题数")
    score_id = execute(
        "INSERT INTO team_game_rank(team_id,user_id,game,score,correct,total,created_at) VALUES(?,?,?,?,?,?,?)",
        (team_id, int(user["id"]), payload.game, payload.score, payload.correct, payload.total, utcnow()),
    )
    badges: list[dict] = []
    if payload.score >= 500:
        badges.append({"badge": "score_500", "label": "团队积分达人"})
    if payload.total and payload.correct / payload.total >= 0.9:
        badges.append({"badge": "accuracy_90", "label": "高正确率"})
    with connection() as conn:
        for badge in badges:
            conn.execute(
                "INSERT OR IGNORE INTO team_game_achievements(team_id,user_id,badge,label,awarded_at) VALUES(?,?,?,?,?)",
                (team_id, int(user["id"]), badge["badge"], badge["label"], utcnow()),
            )
    team_reward = min(25, max(0, int(payload.correct) * 2 + int(payload.score) // 1000))
    if team_reward:
        credit_team(
            team_id,
            "knowledge",
            team_reward,
            reason_code="team_game_reward",
            reason="团队游戏答题奖励",
            idempotency_key=f"team:game:{score_id}:reward",
            reference_type="team_game_rank",
            reference_id=str(score_id),
            metadata={"game": payload.game, "score": payload.score, "correct": payload.correct},
            user_id=int(user["id"]),
        )
    _log(team_id, int(user["id"]), "game", "score", f"{payload.game} 团队积分 {payload.score}")
    detail = f"团队学习成绩已同步：{payload.game} 得分 {payload.score}，答对 {payload.correct}/{payload.total}，团队公共资金池奖励 {team_reward} 学识币。"
    if badges:
        detail += " 解锁徽章：" + "、".join(badge["label"] for badge in badges)
    _notify_team_member(
        team_id=team_id,
        user_id=int(user["id"]),
        actor_id=int(user["id"]),
        module="game",
        action="score_settled",
        title=f"「{_team_name(team_id)}」学习成绩已结算",
        detail=detail,
        target_type="game_score",
        target_id=score_id,
        status="done",
        metadata={"badges": badges, "knowledge_reward": team_reward},
    )
    return {
        **row("SELECT * FROM team_game_rank WHERE id=?", (score_id,)),
        "badges": badges,
        "currency": {"knowledge_reward": team_reward},
    }


@router.get("/{team_id}/games/achievements")
def team_game_achievements(team_id: int, user: CurrentUser) -> dict:
    _membership(team_id, int(user["id"]))
    return {
        "items": rows(
            "SELECT a.*,u.nickname FROM team_game_achievements a JOIN users u ON u.id=a.user_id WHERE a.team_id=? ORDER BY a.awarded_at DESC",
            (team_id,),
        )
    }


@router.websocket("/{team_id}/games/ws")
async def team_game_websocket(team_id: int, websocket: WebSocket) -> None:
    await websocket.accept()
    token = websocket.query_params.get("token", "")
    user_id: int | None = None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if payload.get("type", "access") != "access":
            raise ValueError("invalid token")
        user_id = int(payload["sub"])
        _membership(team_id, user_id)
        room = TEAM_GAME_ROOMS.setdefault(team_id, set())
        room.add(websocket)
        await websocket.send_json({"type": "connected", "team_id": team_id, "user_id": user_id})
        while True:
            message = await websocket.receive_json()
            packet = {"type": "game_event", "user_id": user_id, "payload": message}
            for peer in list(room):
                try:
                    await peer.send_json(packet)
                except Exception:
                    room.discard(peer)
    except (jwt.PyJWTError, KeyError, ValueError, HTTPException):
        await websocket.close(code=4403)
    except WebSocketDisconnect:
        pass
    finally:
        if user_id is not None and team_id in TEAM_GAME_ROOMS:
            TEAM_GAME_ROOMS[team_id].discard(websocket)
            if not TEAM_GAME_ROOMS[team_id]:
                TEAM_GAME_ROOMS.pop(team_id, None)


@router.get("/{team_id}/activities")
def list_team_activities(team_id: int, user: CurrentUser) -> dict:
    _membership(team_id, int(user["id"]))
    return {"items": rows("SELECT * FROM team_activity WHERE team_id=? ORDER BY id DESC", (team_id,))}


@router.post("/{team_id}/activities", status_code=201)
def create_team_activity(team_id: int, payload: TeamActivityRequest, user: CurrentUser) -> dict:
    _require_role(team_id, user, "admin")
    activity_id = execute(
        "INSERT INTO team_activity(team_id,created_by,name,activity_type,status,starts_at,ends_at,reward,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (team_id, int(user["id"]), payload.name, payload.activity_type, "planned", payload.starts_at, payload.ends_at, payload.reward, utcnow()),
    )
    _log(team_id, int(user["id"]), "activity", "create", f"创建团队活动 {payload.name}")
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="activity",
        action="create",
        title=f"「{_team_name(team_id)}」发布新活动",
        detail=f"团队活动「{payload.name}」已创建，类型为 {payload.activity_type}，成员可在个人端同步学习成绩参与排行。",
        exclude_user_id=int(user["id"]),
        target_type="activity",
        target_id=activity_id,
        metadata={"activity_type": payload.activity_type, "reward": payload.reward},
    )
    return row("SELECT * FROM team_activity WHERE id=?", (activity_id,))


@router.patch("/{team_id}/activities/{activity_id}")
def update_team_activity(
    team_id: int,
    activity_id: int,
    payload: TeamActivityUpdateRequest,
    user: CurrentUser,
) -> dict:
    _require_role(team_id, user, "admin")
    activity = row("SELECT * FROM team_activity WHERE team_id=? AND id=?", (team_id, activity_id))
    if not activity:
        raise HTTPException(404, "团队活动不存在")
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        assignment = ",".join(f"{key}=?" for key in updates)
        execute(f"UPDATE team_activity SET {assignment} WHERE team_id=? AND id=?", (*updates.values(), team_id, activity_id))
    _log(team_id, int(user["id"]), "activity", "update", f"更新团队活动 #{activity_id}")
    updated_name = updates.get("name") or activity["name"]
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="activity",
        action="update",
        title=f"「{_team_name(team_id)}」活动已更新",
        detail=f"团队活动「{updated_name}」的状态、时间或奖励规则已更新，请按最新信息参与。",
        exclude_user_id=int(user["id"]),
        target_type="activity",
        target_id=activity_id,
        metadata=updates,
    )
    return row("SELECT * FROM team_activity WHERE id=?", (activity_id,))


@router.get("/{team_id}/settings")
def get_team_settings(team_id: int, user: CurrentUser) -> dict:
    _require_role(team_id, user, "admin")
    team = _team(team_id)
    return {"settings": {**team["settings"], "storage_quota": team["storage_quota"], "daily_deepseek_quota": team["api_quota"]}}


@router.put("/{team_id}/settings")
def update_team_settings(team_id: int, payload: TeamSettingsRequest, user: CurrentUser) -> dict:
    _require_role(team_id, user, "admin")
    team = _team(team_id)
    settings_payload = {**team["settings"], **payload.model_dump(exclude={"storage_quota", "daily_deepseek_quota"})}
    execute(
        "UPDATE teams SET settings=?,storage_quota=?,api_quota=? WHERE id=?",
        (json.dumps(settings_payload, ensure_ascii=False), payload.storage_quota, payload.daily_deepseek_quota, team_id),
    )
    _log(team_id, int(user["id"]), "settings", "update", "更新团队全局配置")
    _notify_team_members(
        team_id,
        actor_id=int(user["id"]),
        module="settings",
        action="update",
        title=f"「{_team_name(team_id)}」团队策略已更新",
        detail="团队管理员更新了分享、进化、配额或并发策略，个人端可用操作会按新规则校验。",
        minimum_role="editor",
        exclude_user_id=int(user["id"]),
        target_type="settings",
        target_id=team_id,
        metadata=payload.model_dump(),
    )
    return {"settings": {**settings_payload, "storage_quota": payload.storage_quota, "daily_deepseek_quota": payload.daily_deepseek_quota}}


@router.get("/{team_id}/stats")
def team_stats(team_id: int, user: CurrentUser) -> dict:
    _membership(team_id, int(user["id"]))
    member_stats = rows(
        "SELECT tm.user_id,u.nickname,tm.role,"
        "(SELECT COUNT(*) FROM team_materials m WHERE m.team_id=tm.team_id AND m.uploader_id=tm.user_id) materials,"
        "(SELECT COUNT(*) FROM team_evolution_reviews r WHERE r.team_id=tm.team_id AND r.reviewer_id=tm.user_id) reviews,"
        "(SELECT COALESCE(SUM(g.score),0) FROM team_game_rank g WHERE g.team_id=tm.team_id AND g.user_id=tm.user_id) score,"
        "(SELECT COALESCE(SUM(g.correct),0) FROM team_game_rank g WHERE g.team_id=tm.team_id AND g.user_id=tm.user_id) correct,"
        "(SELECT COALESCE(SUM(g.total),0) FROM team_game_rank g WHERE g.team_id=tm.team_id AND g.user_id=tm.user_id) total "
        "FROM team_members tm JOIN users u ON u.id=tm.user_id WHERE tm.team_id=? AND tm.status='active' ORDER BY score DESC",
        (team_id,),
    )
    for item in member_stats:
        item["accuracy"] = round(item["correct"] / item["total"], 4) if item["total"] else 0
    library_stats = rows(
        "SELECT l.id,l.name,COUNT(m.id) materials,COALESCE(SUM(m.size),0) storage "
        "FROM team_knowledge_libs l LEFT JOIN team_materials m ON m.lib_id=l.id "
        "WHERE l.team_id=? GROUP BY l.id,l.name ORDER BY materials DESC",
        (team_id,),
    )
    return {"overview": _team_counts(team_id), "members": member_stats, "libraries": library_stats}


@router.get("/{team_id}/graph")
def team_graph(team_id: int, user: CurrentUser, member_id: int | None = None) -> dict:
    _membership(team_id, int(user["id"]))
    params: list[Any] = [team_id]
    where = "m.team_id=?"
    if member_id:
        where += " AND m.uploader_id=?"
        params.append(member_id)
    materials = rows(f"SELECT m.id,m.name,m.uploader_id,m.tags,l.name lib_name FROM team_materials m LEFT JOIN team_knowledge_libs l ON l.id=m.lib_id WHERE {where} ORDER BY m.id DESC LIMIT 120", tuple(params))
    nodes: list[dict] = []
    edges: list[dict] = []
    for material in materials:
        material_node = f"material:{material['id']}"
        nodes.append({"id": material_node, "label": material["name"], "type": "material", "member_id": material["uploader_id"], "library": material["lib_name"]})
        for tag in _json(material.get("tags"), []):
            tag_node = f"tag:{tag}"
            if not any(node["id"] == tag_node for node in nodes):
                nodes.append({"id": tag_node, "label": tag, "type": "tag"})
            edges.append({"source": material_node, "target": tag_node})
    return {"nodes": nodes, "edges": edges, "member_id": member_id}


@router.get("/{team_id}/logs")
def team_logs(team_id: int, user: CurrentUser, module: str | None = None, limit: int = Query(60, ge=1, le=200)) -> dict:
    _require_role(team_id, user, "admin")
    params: list[Any] = [team_id]
    where = "team_id=?"
    if module:
        where += " AND module=?"
        params.append(module)
    items = rows(f"SELECT * FROM team_system_logs WHERE {where}", tuple(params))
    if not module or module == "member":
        member_params: list[Any] = [team_id]
        member_where = "l.team_id=?"
        if module == "member":
            member_where = "1=1 AND l.team_id=?"
        member_items = rows(
            f"SELECT l.id,l.team_id,'member' module,l.action,l.detail,l.created_at,a.nickname actor_name,t.nickname target_name "
            f"FROM team_member_operation_logs l "
            f"LEFT JOIN users a ON a.id=l.actor_id LEFT JOIN users t ON t.id=l.target_user_id "
            f"WHERE {member_where}",
            tuple(member_params),
        )
        items.extend(member_items)
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {"items": items[:limit]}


@router.get("/{team_id}/exports/{kind}")
def export_team_data(team_id: int, kind: str, user: CurrentUser) -> Response:
    _require_role(team_id, user, "admin")
    if kind not in {"materials", "evolution", "games", "logs"}:
        raise HTTPException(404, "不支持的导出类型")
    debit_team(
        team_id,
        "truth",
        1,
        reason_code="team_export",
        reason=f"导出团队{kind}报表",
        idempotency_key=f"team:export:{team_id}:{kind}:{secrets.token_hex(12)}",
        reference_type="team_export",
        reference_id=kind,
        user_id=int(user["id"]),
    )
    if kind == "materials":
        items = rows(
            "SELECT m.id,m.name,m.kind,m.source,m.status,m.size,m.tags,m.created_at,u.nickname uploader,l.name library "
            "FROM team_materials m JOIN users u ON u.id=m.uploader_id LEFT JOIN team_knowledge_libs l ON l.id=m.lib_id WHERE m.team_id=? ORDER BY m.id",
            (team_id,),
        )
        return _export_xlsx("team-materials.xlsx", ["ID", "名称", "类型", "来源", "状态", "大小", "标签", "创建时间", "上传人", "知识库"], [[item.get(key) for key in ["id", "name", "kind", "source", "status", "size", "tags", "created_at", "uploader", "library"]] for item in items])
    if kind == "evolution":
        items = rows(
            "SELECT r.id,r.task_id,r.decision,r.feedback,r.created_at,u.nickname reviewer,t.summary,t.status "
            "FROM team_evolution_reviews r JOIN users u ON u.id=r.reviewer_id JOIN team_evolution_tasks t ON t.id=r.task_id WHERE r.team_id=? ORDER BY r.id",
            (team_id,),
        )
        return _export_xlsx("team-evolution-reviews.xlsx", ["ID", "任务ID", "决策", "反馈", "时间", "审核人", "任务摘要", "任务状态"], [[item.get(key) for key in ["id", "task_id", "decision", "feedback", "created_at", "reviewer", "summary", "status"]] for item in items])
    if kind == "games":
        items = rows(
            "SELECT g.id,g.game,g.score,g.correct,g.total,g.created_at,u.nickname FROM team_game_rank g JOIN users u ON u.id=g.user_id WHERE g.team_id=? ORDER BY g.id",
            (team_id,),
        )
        return _export_xlsx("team-game-logs.xlsx", ["ID", "游戏", "积分", "答对", "总题数", "时间", "成员"], [[item.get(key) for key in ["id", "game", "score", "correct", "total", "created_at", "nickname"]] for item in items])
    if kind == "logs":
        items = rows(
            "SELECT l.id,l.module,l.action,l.detail,l.created_at,u.nickname FROM team_system_logs l LEFT JOIN users u ON u.id=l.user_id WHERE l.team_id=? ORDER BY l.id",
            (team_id,),
        )
        items.extend(
            rows(
                "SELECT l.id,'member' module,l.action,l.detail,l.created_at,u.nickname "
                "FROM team_member_operation_logs l LEFT JOIN users u ON u.id=l.actor_id WHERE l.team_id=? ORDER BY l.id",
                (team_id,),
            )
        )
        return _export_xlsx("team-operation-logs.xlsx", ["ID", "模块", "动作", "详情", "时间", "操作人"], [[item.get(key) for key in ["id", "module", "action", "detail", "created_at", "nickname"]] for item in items])
    raise HTTPException(404, "不支持的导出类型")


@router.get("/{team_id}/backup")
def backup_team(team_id: int, user: CurrentUser) -> Response:
    _require_role(team_id, user, "owner")
    debit_team(
        team_id,
        "truth",
        2,
        reason_code="team_backup",
        reason="导出团队完整备份包",
        idempotency_key=f"team:backup:{team_id}:{secrets.token_hex(12)}",
        reference_type="team_backup",
        reference_id=str(team_id),
        user_id=int(user["id"]),
    )
    tables = {
        "team": row("SELECT * FROM teams WHERE id=?", (team_id,)),
        "members": rows("SELECT * FROM team_members WHERE team_id=?", (team_id,)),
        "libraries": rows("SELECT * FROM team_knowledge_libs WHERE team_id=?", (team_id,)),
        "library_members": rows("SELECT * FROM team_library_members WHERE team_id=?", (team_id,)),
        "materials": rows("SELECT * FROM team_materials WHERE team_id=?", (team_id,)),
        "material_comments": rows("SELECT * FROM team_material_comments WHERE team_id=?", (team_id,)),
        "material_versions": rows("SELECT * FROM team_material_versions WHERE team_id=?", (team_id,)),
        "shares": rows("SELECT id,team_id,lib_id,created_by,name,description,scope,expires_at,visits,status,watermark,audience_user_ids,created_at FROM team_shares WHERE team_id=?", (team_id,)),
        "evolution_tasks": rows("SELECT * FROM team_evolution_tasks WHERE team_id=?", (team_id,)),
        "evolution_reviews": rows("SELECT * FROM team_evolution_reviews WHERE team_id=?", (team_id,)),
        "qa_archives": rows("SELECT * FROM team_qa_archives WHERE team_id=?", (team_id,)),
        "game_rank": rows("SELECT * FROM team_game_rank WHERE team_id=?", (team_id,)),
        "achievements": rows("SELECT * FROM team_game_achievements WHERE team_id=?", (team_id,)),
        "activities": rows("SELECT * FROM team_activity WHERE team_id=?", (team_id,)),
        "system_logs": rows("SELECT * FROM team_system_logs WHERE team_id=?", (team_id,)),
        "member_logs": rows("SELECT * FROM team_member_operation_logs WHERE team_id=?", (team_id,)),
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"team_id": team_id, "exported_at": utcnow(), "format": "zhiyan-team-backup-v1"}, ensure_ascii=False, indent=2))
        for name, value in tables.items():
            archive.writestr(f"{name}.json", json.dumps(value, ensure_ascii=False, default=str, indent=2))
    return Response(
        content=stream.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="team-{team_id}-backup.zip"'},
    )


@public_router.get("/api/share/team/{share_id}")
def public_team_share(share_id: str, request: Request, password: str | None = None) -> dict:
    share = row(
        "SELECT s.*,t.name team_name,t.description team_description,t.status team_status,l.name lib_name "
        "FROM team_shares s JOIN teams t ON t.id=s.team_id LEFT JOIN team_knowledge_libs l ON l.id=s.lib_id WHERE s.id=?",
        (share_id,),
    )
    if not share or share["status"] != "active" or share["team_status"] != "active":
        raise HTTPException(404, "团队分享不存在或已失效")
    if share["expires_at"] and datetime.fromisoformat(share["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(410, "团队分享已过期")
    if share["password_hash"] and (not password or not verify_password(password, share["password_hash"])):
        raise HTTPException(401, "访问密码错误")
    params: list[Any] = [share["team_id"]]
    where = "team_id=? AND status='ready'"
    if share["lib_id"]:
        where += " AND lib_id=?"
        params.append(share["lib_id"])
    materials = rows(
        f"SELECT id,name,kind,size,status,tags,content,created_at FROM team_materials WHERE {where} ORDER BY id DESC LIMIT 80",
        tuple(params),
    )
    execute("UPDATE team_shares SET visits=visits+1 WHERE id=?", (share_id,))
    execute(
        "INSERT INTO team_share_visits(share_id,team_id,visitor_type,created_at) VALUES(?,?,?,?)",
        (share_id, share["team_id"], "external", utcnow()),
    )
    visitor_ip = (request.client.host if request.client else "anonymous").strip()
    visitor_fingerprint = hashlib.sha256(visitor_ip.encode("utf-8")).hexdigest()[:24]
    credit_team(
        int(share["team_id"]),
        "knowledge",
        2,
        reason_code="team_share_visit_reward",
        reason="外部访客访问团队分享奖励",
        idempotency_key=f"team:share:visit:{share_id}:{datetime.now(timezone.utc).date().isoformat()}:{visitor_fingerprint}",
        reference_type="team_share",
        reference_id=share_id,
        metadata={"visitor_fingerprint": visitor_fingerprint},
    )
    return {
        "id": share["id"],
        "name": share["name"],
        "description": share["description"],
        "team": {"name": share["team_name"], "description": share["team_description"]},
        "scope": share["scope"],
        "library": share["lib_name"],
        "watermark": bool(share["watermark"]),
        "items": [{**item, "tags": _json(item.get("tags"), [])} for item in materials],
    }


@public_router.post("/api/share/team/{share_id}/qa")
def public_team_share_qa(share_id: str, payload: TeamQuestionRequest, request: Request, password: str | None = None) -> dict:
    share = row(
        "SELECT s.*,t.name team_name,t.status team_status,l.name lib_name "
        "FROM team_shares s JOIN teams t ON t.id=s.team_id LEFT JOIN team_knowledge_libs l ON l.id=s.lib_id WHERE s.id=?",
        (share_id,),
    )
    if not share or share["status"] != "active" or share["team_status"] != "active":
        raise HTTPException(404, "团队分享不存在或已失效")
    if share["expires_at"] and datetime.fromisoformat(share["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(410, "团队分享已过期")
    if share["password_hash"] and (not password or not verify_password(password, share["password_hash"])):
        raise HTTPException(401, "访问密码错误")
    params: list[Any] = [share["team_id"]]
    where = "team_id=? AND status='ready'"
    if share["lib_id"]:
        where += " AND lib_id=?"
        params.append(share["lib_id"])
    materials = rows(
        f"SELECT id,name,kind,content,lib_id,tags,updated_at FROM team_materials WHERE {where} ORDER BY id DESC LIMIT 120",
        tuple(params),
    )
    terms = _team_question_terms(payload.question)
    ranked = []
    for item in materials:
        score = _team_material_score(item, terms)
        if score > 0:
            ranked.append((score, item))
    if not ranked and materials:
        ranked = [(1, item) for item in materials[:5]]
    ranked.sort(key=lambda pair: (pair[0], pair[1].get("updated_at") or ""), reverse=True)
    sources = [
        {
            "material_id": item["id"],
            "name": item["name"],
            "library": share["lib_name"] or "团队共享范围",
            "snippet": _team_source_snippet(item.get("content") or "", terms),
            "score": score,
        }
        for score, item in ranked[:5]
    ]
    if sources:
        answer = "基于该团队分享范围，检索到以下参考内容：\n\n" + "\n\n".join(
            f"{index}. {source['name']}（{source['library']}）\n{source['snippet']}"
            for index, source in enumerate(sources, start=1)
        )
    else:
        answer = "该分享范围内暂未检索到可引用内容，请联系团队补充素材或扩大分享范围。"
    visitor_ip = (request.client.host if request.client else "anonymous").strip()
    visitor_fingerprint = hashlib.sha256(visitor_ip.encode("utf-8")).hexdigest()[:24]
    credit_team(
        int(share["team_id"]),
        "knowledge",
        1,
        reason_code="team_share_qa_reward",
        reason="外部访客使用团队分享问答奖励",
        idempotency_key=f"team:share:qa:{share_id}:{datetime.now(timezone.utc).date().isoformat()}:{visitor_fingerprint}",
        reference_type="team_share",
        reference_id=share_id,
        metadata={"visitor_fingerprint": visitor_fingerprint},
    )
    execute(
        "INSERT INTO team_share_visits(share_id,team_id,visitor_type,created_at) VALUES(?,?,?,?)",
        (share_id, share["team_id"], "external_qa", utcnow()),
    )
    return {
        "question": payload.question.strip(),
        "answer": answer,
        "sources": sources,
        "mode": "public-team-share-rag",
    }
