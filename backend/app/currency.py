from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from fastapi import HTTPException

from .database import connection, row, rows, utcnow


CURRENCY_LABELS = {
    "knowledge": "学识币",
    "truth": "真知晶",
}
SCOPE_LABELS = {
    "personal": "个人钱包",
    "team": "团队公共资金池",
}
PERSONAL_SEED = {"knowledge": 200, "truth": 3}
TEAM_SEED = {"knowledge": 100, "truth": 2}

PERSONAL_DAILY_QUOTAS = {
    "ai_chat": {"free": 10, "cost": 2, "currency": "knowledge", "label": "标准 AI 问答"},
    "material_ask": {"free": 5, "cost": 2, "currency": "knowledge", "label": "素材 AI 问答"},
    "search": {"free": 20, "cost": 1, "currency": "knowledge", "label": "额外检索"},
    "image_ocr": {"free": 3, "cost": 2, "currency": "knowledge", "label": "图片 OCR"},
    "video_transcribe": {"free": 1, "cost": 5, "currency": "knowledge", "label": "视频转写"},
}
TEAM_DAILY_QUOTAS = {
    "team_qa": {"free": 20, "cost": 2, "currency": "knowledge", "label": "团队 AI 问答"},
    "team_media": {"free": 10, "cost": 5, "currency": "knowledge", "label": "团队媒体处理"},
}

STORE_ITEMS = [
    {
        "item_id": "search_boost_10",
        "name": "额外检索次数",
        "description": "增加 10 次个人知识检索额度。",
        "currency": "knowledge",
        "price": 20,
        "quantity": 10,
        "category": "基础工具",
    },
    {
        "item_id": "game_hint_3",
        "name": "游戏提示道具",
        "description": "获得 3 次游戏提示机会。",
        "currency": "knowledge",
        "price": 15,
        "quantity": 3,
        "category": "游戏道具",
    },
    {
        "item_id": "permanent_share",
        "name": "永久分享凭证",
        "description": "用于创建一个不设过期时间的个人分享链接。",
        "currency": "truth",
        "price": 1,
        "quantity": 1,
        "category": "高级能力",
    },
    {
        "item_id": "hd_graph_export",
        "name": "高清图谱导出",
        "description": "兑换一次高清知识图谱导出资格。",
        "currency": "truth",
        "price": 2,
        "quantity": 1,
        "category": "高级能力",
    },
    {
        "item_id": "task_acceleration",
        "name": "任务加速",
        "description": "兑换一次高优先级任务加速资格。",
        "currency": "truth",
        "price": 1,
        "quantity": 1,
        "category": "高级能力",
    },
]


def _day(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).date().isoformat()


def _metadata(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def _wallet_query(scope: str, owner_id: int) -> tuple[str, str]:
    if scope == "personal":
        return "user_id=?", f"user:{int(owner_id)}"
    if scope == "team":
        return "team_id=?", f"team:{int(owner_id)}"
    raise ValueError("不支持的钱包范围")


def _wallet_row(conn, scope: str, owner_id: int):
    condition, _ = _wallet_query(scope, owner_id)
    return conn.execute(
        f"SELECT * FROM currency_wallets WHERE scope=? AND {condition}",
        (scope, int(owner_id)),
    ).fetchone()


def _wallet_dict(wallet: Any) -> dict[str, Any]:
    if wallet is None:
        return {}
    item = dict(wallet)
    item["scope_label"] = SCOPE_LABELS.get(item.get("scope"), item.get("scope"))
    item["knowledge_label"] = CURRENCY_LABELS["knowledge"]
    item["truth_label"] = CURRENCY_LABELS["truth"]
    item["knowledge_balance"] = int(item.get("knowledge_balance") or 0)
    item["truth_balance"] = int(item.get("truth_balance") or 0)
    item["truth_crystals"] = item["truth_balance"]
    return item


def _insert_transaction(
    conn,
    *,
    wallet: Any,
    scope: str,
    owner_id: int,
    currency: str,
    amount: int,
    balance_after: int,
    reason_code: str,
    reason: str,
    reference_type: str,
    reference_id: str,
    idempotency_key: str,
    metadata: dict[str, Any] | None,
    user_id: int | None = None,
) -> int:
    return int(conn.execute(
        "INSERT INTO currency_transactions("
        "wallet_id,scope,user_id,team_id,currency,amount,balance_after,reason_code,reason,"
        "reference_type,reference_id,idempotency_key,metadata,created_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            int(wallet["id"]),
            scope,
            int(user_id) if user_id is not None else (int(owner_id) if scope == "personal" else None),
            int(owner_id) if scope == "team" else None,
            currency,
            int(amount),
            int(balance_after),
            reason_code,
            reason,
            reference_type,
            str(reference_id or ""),
            idempotency_key,
            _metadata(metadata),
            utcnow(),
        ),
    ).lastrowid)


def _ensure_wallet_in_connection(conn, scope: str, owner_id: int, *, user_id: int | None = None):
    wallet = _wallet_row(conn, scope, owner_id)
    if wallet:
        return wallet
    seed = PERSONAL_SEED if scope == "personal" else TEAM_SEED
    if scope == "team" and user_id is None:
        team = conn.execute("SELECT owner_id FROM teams WHERE id=?", (int(owner_id),)).fetchone()
        user_id = int(team["owner_id"]) if team else None
    now = utcnow()
    if scope == "personal":
        cursor = conn.execute(
            "INSERT INTO currency_wallets(scope,owner_key,user_id,knowledge_balance,truth_balance,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            ("personal", f"user:{int(owner_id)}", int(owner_id), seed["knowledge"], seed["truth"], now, now),
        )
    else:
        cursor = conn.execute(
            "INSERT INTO currency_wallets(scope,owner_key,team_id,knowledge_balance,truth_balance,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            ("team", f"team:{int(owner_id)}", int(owner_id), seed["knowledge"], seed["truth"], now, now),
        )
    wallet_id = int(cursor.lastrowid)
    wallet = conn.execute("SELECT * FROM currency_wallets WHERE id=?", (wallet_id,)).fetchone()
    for currency, amount in seed.items():
        _insert_transaction(
            conn,
            wallet=wallet,
            scope=scope,
            owner_id=int(owner_id),
            currency=currency,
            amount=amount,
            balance_after=amount,
            reason_code="welcome_grant" if scope == "personal" else "team_seed_grant",
            reason=f"{SCOPE_LABELS[scope]}初始{CURRENCY_LABELS[currency]}",
            reference_type="wallet",
            reference_id=str(owner_id),
            idempotency_key=f"{scope}-seed:{owner_id}:{currency}",
            metadata={"seed": True},
            user_id=user_id,
        )
    return wallet


def ensure_personal_wallet(user_id: int) -> dict[str, Any]:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return _wallet_dict(_ensure_wallet_in_connection(conn, "personal", int(user_id), user_id=int(user_id)))


def ensure_team_wallet(team_id: int, *, user_id: int | None = None) -> dict[str, Any]:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return _wallet_dict(_ensure_wallet_in_connection(conn, "team", int(team_id), user_id=user_id))


def wallet_snapshot(scope: str, owner_id: int, *, user_id: int | None = None) -> dict[str, Any]:
    if scope == "personal":
        ensure_personal_wallet(owner_id)
    else:
        ensure_team_wallet(owner_id, user_id=user_id)
    wallet = row(
        "SELECT * FROM currency_wallets WHERE scope=? AND owner_key=?",
        (scope, f"{scope.replace('personal', 'user').replace('team', 'team')}:{int(owner_id)}"),
    )
    if not wallet:
        raise HTTPException(404, "货币钱包不存在")
    result = _wallet_dict(wallet)
    result["balances"] = {
        "knowledge": result["knowledge_balance"],
        "truth": result["truth_balance"],
    }
    result["currencies"] = [
        {"id": "knowledge", "name": CURRENCY_LABELS["knowledge"], "balance": result["knowledge_balance"]},
        {"id": "truth", "name": CURRENCY_LABELS["truth"], "balance": result["truth_balance"]},
    ]
    today = _day()
    if scope == "personal":
        usage_rows = rows(
            "SELECT action,free_used,paid_used FROM currency_daily_usage WHERE user_id=? AND day=?",
            (int(owner_id), today),
        )
        checkin = row(
            "SELECT day,streak,knowledge_amount,truth_amount FROM currency_checkins WHERE user_id=? ORDER BY day DESC LIMIT 1",
            (int(owner_id),),
        )
    else:
        usage_rows = rows(
            "SELECT action,free_used,paid_used FROM currency_team_daily_usage WHERE team_id=? AND day=?",
            (int(owner_id), today),
        )
        checkin = None
    result["today"] = {
        "day": today,
        "usage": {
            item["action"]: {
                "free_used": int(item["free_used"]),
                "paid_used": int(item["paid_used"]),
            }
            for item in usage_rows
        },
        "quotas": PERSONAL_DAILY_QUOTAS if scope == "personal" else TEAM_DAILY_QUOTAS,
    }
    result["last_checkin"] = checkin
    result["inventory"] = rows(
        "SELECT item_id,quantity,updated_at FROM currency_inventory WHERE user_id=? AND quantity>0 ORDER BY item_id",
        (int(owner_id),),
    ) if scope == "personal" else []
    return result


def _apply_mutation(
    conn,
    *,
    scope: str,
    owner_id: int,
    currency: str,
    amount: int,
    reason_code: str,
    reason: str,
    idempotency_key: str,
    reference_type: str = "",
    reference_id: str = "",
    metadata: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    if currency not in CURRENCY_LABELS:
        raise HTTPException(422, "不支持的货币类型")
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(422, "货币操作缺少有效幂等键")
    if not amount:
        raise HTTPException(422, "货币变更数量不能为 0")
    wallet = _ensure_wallet_in_connection(conn, scope, owner_id, user_id=user_id)
    existing = conn.execute(
        "SELECT * FROM currency_transactions WHERE wallet_id=? AND currency=? AND idempotency_key=?",
        (int(wallet["id"]), currency, idempotency_key),
    ).fetchone()
    if existing:
        return {
            "applied": False,
            "transaction": dict(existing),
            "balance_after": int(existing["balance_after"]),
            "wallet": _wallet_dict(conn.execute("SELECT * FROM currency_wallets WHERE id=?", (wallet["id"],)).fetchone()),
        }
    field = "knowledge_balance" if currency == "knowledge" else "truth_balance"
    current = int(wallet[field] or 0)
    after = current + int(amount)
    if after < 0:
        raise HTTPException(
            status_code=402,
            detail=f"{CURRENCY_LABELS[currency]}余额不足，需要 {abs(int(amount))}，当前仅有 {current}",
        )
    now = utcnow()
    conn.execute(
        f"UPDATE currency_wallets SET {field}=?,updated_at=? WHERE id=?",
        (after, now, int(wallet["id"])),
    )
    transaction_id = _insert_transaction(
        conn,
        wallet=wallet,
        scope=scope,
        owner_id=owner_id,
        currency=currency,
        amount=int(amount),
        balance_after=after,
        reason_code=reason_code,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        metadata=metadata,
        user_id=user_id,
    )
    updated_wallet = conn.execute("SELECT * FROM currency_wallets WHERE id=?", (wallet["id"],)).fetchone()
    return {
        "applied": True,
        "transaction": dict(conn.execute("SELECT * FROM currency_transactions WHERE id=?", (transaction_id,)).fetchone()),
        "balance_after": after,
        "wallet": _wallet_dict(updated_wallet),
    }


def mutate_wallet(
    scope: str,
    owner_id: int,
    currency: str,
    amount: int,
    *,
    reason_code: str,
    reason: str,
    idempotency_key: str,
    reference_type: str = "",
    reference_id: str = "",
    metadata: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return _apply_mutation(
            conn,
            scope=scope,
            owner_id=int(owner_id),
            currency=currency,
            amount=int(amount),
            reason_code=reason_code,
            reason=reason,
            idempotency_key=idempotency_key,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata=metadata,
            user_id=user_id,
        )


def mutate_wallet_bundle(
    scope: str,
    owner_id: int,
    changes: Iterable[dict[str, Any]],
    *,
    reference_type: str = "",
    reference_id: str = "",
    metadata: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    changes = list(changes)
    if not changes:
        raise HTTPException(422, "货币变更不能为空")
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        results = []
        for change in changes:
            results.append(_apply_mutation(
                conn,
                scope=scope,
                owner_id=int(owner_id),
                currency=change["currency"],
                amount=int(change["amount"]),
                reason_code=change["reason_code"],
                reason=change.get("reason", ""),
                idempotency_key=change["idempotency_key"],
                reference_type=change.get("reference_type", reference_type),
                reference_id=change.get("reference_id", reference_id),
                metadata=change.get("metadata", metadata),
                user_id=user_id,
            ))
        wallet = _wallet_row(conn, scope, int(owner_id))
        return {"wallet": _wallet_dict(wallet), "results": results}


def credit_personal(user_id: int, currency: str, amount: int, *, reason_code: str, reason: str, idempotency_key: str, reference_type: str = "", reference_id: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return mutate_wallet(
        "personal",
        user_id,
        currency,
        abs(int(amount)),
        reason_code=reason_code,
        reason=reason,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_id=reference_id,
        metadata=metadata,
        user_id=user_id,
    )


def debit_personal(user_id: int, currency: str, amount: int, *, reason_code: str, reason: str, idempotency_key: str, reference_type: str = "", reference_id: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return mutate_wallet(
        "personal",
        user_id,
        currency,
        -abs(int(amount)),
        reason_code=reason_code,
        reason=reason,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_id=reference_id,
        metadata=metadata,
        user_id=user_id,
    )


def credit_team(team_id: int, currency: str, amount: int, *, reason_code: str, reason: str, idempotency_key: str, reference_type: str = "", reference_id: str = "", metadata: dict[str, Any] | None = None, user_id: int | None = None) -> dict[str, Any]:
    return mutate_wallet(
        "team",
        team_id,
        currency,
        abs(int(amount)),
        reason_code=reason_code,
        reason=reason,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_id=reference_id,
        metadata=metadata,
        user_id=user_id,
    )


def debit_team(team_id: int, currency: str, amount: int, *, reason_code: str, reason: str, idempotency_key: str, reference_type: str = "", reference_id: str = "", metadata: dict[str, Any] | None = None, user_id: int | None = None) -> dict[str, Any]:
    return mutate_wallet(
        "team",
        team_id,
        currency,
        -abs(int(amount)),
        reason_code=reason_code,
        reason=reason,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_id=reference_id,
        metadata=metadata,
        user_id=user_id,
    )


def list_transactions(scope: str, owner_id: int, *, limit: int = 80, currency: str | None = None) -> list[dict[str, Any]]:
    if scope not in {"personal", "team"}:
        raise HTTPException(422, "不支持的钱包范围")
    ensure_personal_wallet(owner_id) if scope == "personal" else ensure_team_wallet(owner_id)
    params: list[Any] = [scope, f"{'user' if scope == 'personal' else 'team'}:{int(owner_id)}"]
    where = "t.scope=? AND w.owner_key=?"
    if currency:
        if currency not in CURRENCY_LABELS:
            raise HTTPException(422, "不支持的货币类型")
        where += " AND t.currency=?"
        params.append(currency)
    params.append(max(1, min(int(limit), 200)))
    items = rows(
        f"SELECT t.*,w.owner_key FROM currency_transactions t JOIN currency_wallets w ON w.id=t.wallet_id "
        f"WHERE {where} ORDER BY t.id DESC LIMIT ?",
        tuple(params),
    )
    for item in items:
        item["currency_label"] = CURRENCY_LABELS.get(item["currency"], item["currency"])
        item["amount"] = int(item["amount"])
        item["metadata"] = json.loads(item.get("metadata") or "{}")
    return items


def _consume_quota(
    *,
    scope: str,
    owner_id: int,
    actor_user_id: int | None,
    action: str,
    free_limit: int,
    paid_cost: int,
    currency: str,
    idempotency_key: str,
    reason_code: str,
    reason: str,
    reference_type: str,
    reference_id: str,
) -> dict[str, Any]:
    if free_limit < 0 or paid_cost < 0:
        raise ValueError("额度参数不能为负数")
    table = "currency_daily_usage" if scope == "personal" else "currency_team_daily_usage"
    owner_column = "user_id" if scope == "personal" else "team_id"
    owner_key = int(owner_id)
    day = _day()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        wallet = _ensure_wallet_in_connection(conn, scope, owner_id, user_id=actor_user_id)
        guard_key = f"{scope}:{owner_id}"
        guard_cursor = conn.execute(
            "INSERT OR IGNORE INTO currency_operation_guards(scope,owner_key,action,operation_key,created_at) VALUES(?,?,?,?,?)",
            (scope, guard_key, action, idempotency_key, utcnow()),
        )
        usage = conn.execute(
            f"SELECT * FROM {table} WHERE {owner_column}=? AND day=? AND action=?",
            (owner_key, day, action),
        ).fetchone()
        if not usage:
            now = utcnow()
            conn.execute(
                f"INSERT INTO {table}({owner_column},day,action,free_used,paid_used,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (owner_key, day, action, 0, 0, now, now),
            )
            usage = conn.execute(
                f"SELECT * FROM {table} WHERE {owner_column}=? AND day=? AND action=?",
                (owner_key, day, action),
            ).fetchone()
        if guard_cursor.rowcount == 0:
            return {
                "free": False,
                "charged": 0,
                "already_processed": True,
                "action": action,
                "free_used": int(usage["free_used"]),
                "paid_used": int(usage["paid_used"]),
                "wallet": _wallet_dict(wallet),
            }
        if int(usage["free_used"]) < int(free_limit):
            conn.execute(
                f"UPDATE {table} SET free_used=free_used+1,updated_at=? WHERE id=?",
                (utcnow(), usage["id"]),
            )
            return {
                "free": True,
                "charged": 0,
                "action": action,
                "free_used": int(usage["free_used"]) + 1,
                "paid_used": int(usage["paid_used"]),
                "wallet": _wallet_dict(wallet),
            }
        mutation = _apply_mutation(
            conn,
            scope=scope,
            owner_id=owner_id,
            currency=currency,
            amount=-abs(int(paid_cost)),
            reason_code=reason_code,
            reason=reason,
            idempotency_key=idempotency_key,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata={"action": action, "daily_free_limit": free_limit},
            user_id=actor_user_id,
        ) if paid_cost else {"wallet": _wallet_dict(wallet), "applied": False}
        if not mutation.get("applied", False) and paid_cost:
            return {
                "free": False,
                "charged": 0,
                "already_processed": True,
                "action": action,
                "free_used": int(usage["free_used"]),
                "paid_used": int(usage["paid_used"]),
                "wallet": mutation["wallet"],
                "transaction": mutation.get("transaction"),
            }
        conn.execute(
            f"UPDATE {table} SET paid_used=paid_used+1,updated_at=? WHERE id=?",
            (utcnow(), usage["id"]),
        )
        return {
            "free": False,
            "charged": abs(int(paid_cost)),
            "action": action,
            "free_used": int(usage["free_used"]),
            "paid_used": int(usage["paid_used"]) + 1,
            "wallet": mutation["wallet"],
            "transaction": mutation.get("transaction"),
        }


def consume_personal_quota(user_id: int, action: str, *, idempotency_key: str, reference_type: str = "", reference_id: str = "") -> dict[str, Any]:
    config = PERSONAL_DAILY_QUOTAS.get(action)
    if not config:
        raise HTTPException(422, "未配置个人额度规则")
    return _consume_quota(
        scope="personal",
        owner_id=user_id,
        actor_user_id=user_id,
        action=action,
        free_limit=int(config["free"]),
        paid_cost=int(config["cost"]),
        currency=str(config["currency"]),
        idempotency_key=idempotency_key,
        reason_code=f"quota:{action}",
        reason=f"超出每日免费额度：{config['label']}",
        reference_type=reference_type,
        reference_id=reference_id,
    )


def consume_team_quota(team_id: int, action: str, *, user_id: int, idempotency_key: str, reference_type: str = "", reference_id: str = "") -> dict[str, Any]:
    config = TEAM_DAILY_QUOTAS.get(action)
    if not config:
        raise HTTPException(422, "未配置团队额度规则")
    return _consume_quota(
        scope="team",
        owner_id=team_id,
        actor_user_id=user_id,
        action=action,
        free_limit=int(config["free"]),
        paid_cost=int(config["cost"]),
        currency=str(config["currency"]),
        idempotency_key=idempotency_key,
        reason_code=f"team_quota:{action}",
        reason=f"超出团队每日免费额度：{config['label']}",
        reference_type=reference_type,
        reference_id=reference_id,
    )


def quota_status(scope: str, owner_id: int, action: str) -> dict[str, Any]:
    config_map = PERSONAL_DAILY_QUOTAS if scope == "personal" else TEAM_DAILY_QUOTAS
    config = config_map.get(action)
    if not config:
        raise HTTPException(422, "未配置额度规则")
    table = "currency_daily_usage" if scope == "personal" else "currency_team_daily_usage"
    owner_column = "user_id" if scope == "personal" else "team_id"
    usage = row(
        f"SELECT free_used,paid_used FROM {table} WHERE {owner_column}=? AND day=? AND action=?",
        (int(owner_id), _day(), action),
    ) or {"free_used": 0, "paid_used": 0}
    return {
        "action": action,
        "label": config["label"],
        "free_limit": int(config["free"]),
        "paid_cost": int(config["cost"]),
        "currency": config["currency"],
        "free_used": int(usage.get("free_used") or 0),
        "paid_used": int(usage.get("paid_used") or 0),
        "free_remaining": max(0, int(config["free"]) - int(usage.get("free_used") or 0)),
    }


def claim_daily_checkin(user_id: int) -> dict[str, Any]:
    day = _day()
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM currency_checkins WHERE user_id=? AND day=?",
            (int(user_id), day),
        ).fetchone()
        if existing:
            wallet = _ensure_wallet_in_connection(conn, "personal", user_id, user_id=user_id)
            return {"claimed": False, "checkin": dict(existing), "wallet": _wallet_dict(wallet)}
        previous_day = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        previous = conn.execute(
            "SELECT streak FROM currency_checkins WHERE user_id=? AND day=?",
            (int(user_id), previous_day),
        ).fetchone()
        streak = int(previous["streak"]) + 1 if previous else 1
        knowledge_amount = min(30, 8 + streak * 2)
        truth_amount = 1 if streak % 7 == 0 else 0
        now = utcnow()
        conn.execute(
            "INSERT INTO currency_checkins(user_id,day,streak,knowledge_amount,truth_amount,created_at) VALUES(?,?,?,?,?,?)",
            (int(user_id), day, streak, knowledge_amount, truth_amount, now),
        )
        changes = [
            {
                "currency": "knowledge",
                "amount": knowledge_amount,
                "reason_code": "daily_checkin",
                "reason": f"每日签到（连续第{streak}天）",
                "idempotency_key": f"checkin:{user_id}:{day}:knowledge",
                "reference_type": "checkin",
                "reference_id": day,
            }
        ]
        if truth_amount:
            changes.append({
                "currency": "truth",
                "amount": truth_amount,
                "reason_code": "checkin_streak_reward",
                "reason": f"连续签到{streak}天奖励",
                "idempotency_key": f"checkin:{user_id}:{day}:truth",
                "reference_type": "checkin",
                "reference_id": day,
            })
        wallet = _ensure_wallet_in_connection(conn, "personal", user_id, user_id=user_id)
        result = []
        for change in changes:
            result.append(_apply_mutation(
                conn,
                scope="personal",
                owner_id=user_id,
                currency=change["currency"],
                amount=change["amount"],
                reason_code=change["reason_code"],
                reason=change["reason"],
                idempotency_key=change["idempotency_key"],
                reference_type="checkin",
                reference_id=day,
                user_id=user_id,
            ))
        return {
            "claimed": True,
            "checkin": dict(conn.execute(
                "SELECT * FROM currency_checkins WHERE user_id=? AND day=?",
                (int(user_id), day),
            ).fetchone()),
            "wallet": _wallet_dict(conn.execute("SELECT * FROM currency_wallets WHERE id=?", (wallet["id"],)).fetchone()),
            "transactions": [item["transaction"] for item in result],
        }


def purchase_store_item(user_id: int, item_id: str, quantity: int, *, idempotency_key: str | None = None) -> dict[str, Any]:
    item = next((item for item in STORE_ITEMS if item["item_id"] == item_id), None)
    if not item:
        raise HTTPException(404, "道具不存在")
    if quantity < 1 or quantity > 99:
        raise HTTPException(422, "购买数量必须在 1 到 99 之间")
    operation_key = idempotency_key or f"purchase:{user_id}:{item_id}:{datetime.now(timezone.utc).timestamp()}"
    total = int(item["price"]) * int(quantity)
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        mutation = _apply_mutation(
            conn,
            scope="personal",
            owner_id=int(user_id),
            currency=item["currency"],
            amount=-abs(total),
            reason_code="store_purchase",
            reason=f"购买{item['name']} x{quantity}",
            idempotency_key=operation_key,
            reference_type="store",
            reference_id=item_id,
            metadata={"item_id": item_id, "quantity": quantity},
            user_id=int(user_id),
        )
        if not mutation.get("applied"):
            inventory = conn.execute(
                "SELECT item_id,quantity,updated_at FROM currency_inventory WHERE user_id=? AND item_id=?",
                (int(user_id), item_id),
            ).fetchone()
            return {
                "item": item,
                "quantity": quantity,
                "charged": 0,
                "currency": item["currency"],
                "wallet": mutation["wallet"],
                "inventory": dict(inventory) if inventory else {"item_id": item_id, "quantity": 0, "updated_at": ""},
                "already_processed": True,
            }
        now = utcnow()
        conn.execute(
            "INSERT INTO currency_inventory(user_id,item_id,quantity,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id,item_id) DO UPDATE SET quantity=quantity+excluded.quantity,updated_at=excluded.updated_at",
            (int(user_id), item_id, int(item["quantity"]) * quantity, now),
        )
        inventory = conn.execute(
            "SELECT item_id,quantity,updated_at FROM currency_inventory WHERE user_id=? AND item_id=?",
            (int(user_id), item_id),
        ).fetchone()
    return {"item": item, "quantity": quantity, "charged": total, "currency": item["currency"], "wallet": mutation["wallet"], "inventory": dict(inventory)}
