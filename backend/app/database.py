from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import bcrypt

from .config import settings


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def row(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    result = rows(query, params)
    return result[0] if result else None


def execute(query: str, params: tuple[Any, ...] = ()) -> int:
    with connection() as conn:
        cursor = conn.execute(query, params)
        return int(cursor.lastrowid)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  nickname TEXT NOT NULL,
  phone TEXT,
  avatar TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS materials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  size INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ready',
  category TEXT DEFAULT '未分类',
  content TEXT DEFAULT '',
  origin_url TEXT DEFAULT '',
  file_path TEXT DEFAULT '',
  error TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evolution_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  improvements INTEGER DEFAULT 0,
  corrections INTEGER DEFAULT 0,
  expansions INTEGER DEFAULT 0,
  summary TEXT DEFAULT '',
  error TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS evolution_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES evolution_tasks(id) ON DELETE CASCADE,
  material_id INTEGER REFERENCES materials(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  original_text TEXT NOT NULL,
  proposed_text TEXT NOT NULL,
  reason TEXT NOT NULL,
  decision TEXT NOT NULL DEFAULT 'pending',
  applied_at TEXT
);
CREATE TABLE IF NOT EXISTS evolution_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id INTEGER NOT NULL REFERENCES evolution_tasks(id) ON DELETE CASCADE,
  review_id INTEGER NOT NULL REFERENCES evolution_reviews(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  previous_content TEXT NOT NULL,
  new_content TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS game_packs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  game TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  title TEXT NOT NULL,
  material_ids TEXT NOT NULL,
  knowledge_points TEXT NOT NULL,
  source_mode TEXT NOT NULL,
  agent_note TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS game_questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  pack_id INTEGER REFERENCES game_packs(id) ON DELETE CASCADE,
  source_material_id INTEGER REFERENCES materials(id) ON DELETE SET NULL,
  game TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  prompt TEXT NOT NULL,
  options TEXT NOT NULL,
  answer TEXT NOT NULL,
  explanation TEXT NOT NULL,
  topic TEXT NOT NULL,
  question_type TEXT DEFAULT 'multiple-choice',
  sequence INTEGER DEFAULT 0,
  verified INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS game_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  game TEXT NOT NULL,
  pack_id INTEGER REFERENCES game_packs(id) ON DELETE SET NULL,
  question_id INTEGER REFERENCES game_questions(id) ON DELETE SET NULL,
  score INTEGER NOT NULL,
  correct INTEGER NOT NULL,
  duration INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_nodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  category TEXT NOT NULL,
  mastery INTEGER NOT NULL,
  summary TEXT NOT NULL,
  source_material_id INTEGER REFERENCES materials(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS graph_edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source INTEGER NOT NULL,
  target INTEGER NOT NULL,
  weight REAL NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS graph_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  node_id INTEGER NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  result TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_favorites (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, material_id)
);
CREATE TABLE IF NOT EXISTS notification_reads (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  last_read_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shares (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  scope TEXT NOT NULL DEFAULT 'all',
  expires_at TEXT,
  password_hash TEXT,
  visits INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_settings (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  auto_evolution INTEGER NOT NULL DEFAULT 1,
  trigger_time TEXT NOT NULL DEFAULT '02:00',
  evolution_mode TEXT NOT NULL DEFAULT 'manual',
  monopoly_difficulty TEXT NOT NULL DEFAULT 'medium',
  flashcard_difficulty TEXT NOT NULL DEFAULT 'medium',
  matching_difficulty TEXT NOT NULL DEFAULT 'hard',
  gamified_review INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS system_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  module TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  avatar TEXT DEFAULT '',
  description TEXT DEFAULT '',
  team_type TEXT NOT NULL DEFAULT 'learning',
  status TEXT NOT NULL DEFAULT 'active',
  storage_quota INTEGER NOT NULL DEFAULT 1073741824,
  api_quota INTEGER NOT NULL DEFAULT 10000,
  settings TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  archived_at TEXT
);
CREATE TABLE IF NOT EXISTS team_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'viewer',
  status TEXT NOT NULL DEFAULT 'active',
  storage_used INTEGER NOT NULL DEFAULT 0,
  joined_at TEXT NOT NULL,
  last_active_at TEXT,
  UNIQUE(team_id, user_id)
);
CREATE TABLE IF NOT EXISTS team_invites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL DEFAULT 'viewer',
  expires_at TEXT,
  uses INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_join_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  message TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  reviewer_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  review_note TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  reviewed_at TEXT
);
CREATE TABLE IF NOT EXISTS team_knowledge_libs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  category TEXT DEFAULT '通用',
  dataset_key TEXT NOT NULL,
  visibility TEXT NOT NULL DEFAULT 'team',
  permission_mode TEXT NOT NULL DEFAULT 'team_editors',
  created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_materials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  lib_id INTEGER REFERENCES team_knowledge_libs(id) ON DELETE SET NULL,
  uploader_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'manual',
  kind TEXT NOT NULL DEFAULT 'Markdown',
  size INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ready',
  tags TEXT NOT NULL DEFAULT '[]',
  content TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS team_material_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  material_id INTEGER NOT NULL REFERENCES team_materials(id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  body TEXT NOT NULL,
  resolved INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_material_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  material_id INTEGER NOT NULL REFERENCES team_materials(id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  content TEXT NOT NULL,
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_shares (
  id TEXT PRIMARY KEY,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  lib_id INTEGER REFERENCES team_knowledge_libs(id) ON DELETE SET NULL,
  created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  scope TEXT NOT NULL DEFAULT 'team',
  password_hash TEXT,
  expires_at TEXT,
  visits INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  watermark INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_share_visits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  share_id TEXT NOT NULL REFERENCES team_shares(id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  visitor_type TEXT NOT NULL DEFAULT 'external',
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_evolution_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  lib_id INTEGER REFERENCES team_knowledge_libs(id) ON DELETE SET NULL,
  created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  mode TEXT NOT NULL DEFAULT 'manual',
  visibility TEXT NOT NULL DEFAULT 'team',
  status TEXT NOT NULL DEFAULT 'pending_review',
  review_strategy TEXT NOT NULL DEFAULT 'owner_final',
  progress INTEGER NOT NULL DEFAULT 0,
  summary TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS team_evolution_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES team_evolution_tasks(id) ON DELETE CASCADE,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  reviewer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  decision TEXT NOT NULL DEFAULT 'pending',
  feedback TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_game_rank (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  game TEXT NOT NULL DEFAULT 'flashcard',
  score INTEGER NOT NULL DEFAULT 0,
  correct INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  activity_type TEXT NOT NULL DEFAULT 'contest',
  status TEXT NOT NULL DEFAULT 'planned',
  starts_at TEXT,
  ends_at TEXT,
  reward TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_member_operation_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_member_notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  module TEXT NOT NULL,
  action TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL,
  target_type TEXT DEFAULT '',
  target_id TEXT DEFAULT '',
  action_url TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  read_at TEXT,
  handled_at TEXT
);
CREATE TABLE IF NOT EXISTS team_system_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  module TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_sandbox_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  task_type TEXT NOT NULL,
  routing_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  detail TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS team_library_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  lib_id INTEGER NOT NULL REFERENCES team_knowledge_libs(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  access TEXT NOT NULL DEFAULT 'read',
  created_at TEXT NOT NULL,
  UNIQUE(lib_id, user_id)
);
CREATE TABLE IF NOT EXISTS team_qa_archives (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  sources TEXT NOT NULL DEFAULT '[]',
  lib_ids TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS currency_wallets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL CHECK(scope IN ('personal','team')),
  owner_key TEXT NOT NULL,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
  knowledge_balance INTEGER NOT NULL DEFAULT 0 CHECK(knowledge_balance >= 0),
  truth_balance INTEGER NOT NULL DEFAULT 0 CHECK(truth_balance >= 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(scope, owner_key)
);
CREATE TABLE IF NOT EXISTS currency_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wallet_id INTEGER NOT NULL REFERENCES currency_wallets(id) ON DELETE CASCADE,
  scope TEXT NOT NULL CHECK(scope IN ('personal','team')),
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
  currency TEXT NOT NULL CHECK(currency IN ('knowledge','truth')),
  amount INTEGER NOT NULL CHECK(amount <> 0),
  balance_after INTEGER NOT NULL CHECK(balance_after >= 0),
  reason_code TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  reference_type TEXT DEFAULT '',
  reference_id TEXT DEFAULT '',
  idempotency_key TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(wallet_id, currency, idempotency_key)
);
CREATE TABLE IF NOT EXISTS currency_daily_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day TEXT NOT NULL,
  action TEXT NOT NULL,
  free_used INTEGER NOT NULL DEFAULT 0,
  paid_used INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, day, action)
);
CREATE TABLE IF NOT EXISTS currency_team_daily_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  day TEXT NOT NULL,
  action TEXT NOT NULL,
  free_used INTEGER NOT NULL DEFAULT 0,
  paid_used INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(team_id, day, action)
);
CREATE TABLE IF NOT EXISTS currency_operation_guards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL CHECK(scope IN ('personal','team')),
  owner_key TEXT NOT NULL,
  action TEXT NOT NULL,
  operation_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(scope, owner_key, action, operation_key)
);
CREATE TABLE IF NOT EXISTS currency_checkins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day TEXT NOT NULL,
  streak INTEGER NOT NULL DEFAULT 1,
  knowledge_amount INTEGER NOT NULL DEFAULT 0,
  truth_amount INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE(user_id, day)
);
CREATE TABLE IF NOT EXISTS currency_inventory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item_id TEXT NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, item_id)
);
CREATE TABLE IF NOT EXISTS team_game_achievements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  badge TEXT NOT NULL,
  label TEXT NOT NULL,
  awarded_at TEXT NOT NULL,
  UNIQUE(team_id, user_id, badge)
);
"""


def init_database() -> None:
    with connection() as conn:
        conn.executescript(SCHEMA)
        material_columns = {item["name"] for item in conn.execute("PRAGMA table_info(materials)").fetchall()}
        if "origin_url" not in material_columns:
            conn.execute("ALTER TABLE materials ADD COLUMN origin_url TEXT DEFAULT ''")
        if "file_path" not in material_columns:
            conn.execute("ALTER TABLE materials ADD COLUMN file_path TEXT DEFAULT ''")
        review_columns = {item["name"] for item in conn.execute("PRAGMA table_info(evolution_reviews)").fetchall()}
        if "material_id" not in review_columns:
            conn.execute("ALTER TABLE evolution_reviews ADD COLUMN material_id INTEGER REFERENCES materials(id) ON DELETE SET NULL")
        if "applied_at" not in review_columns:
            conn.execute("ALTER TABLE evolution_reviews ADD COLUMN applied_at TEXT")
        task_columns = {item["name"] for item in conn.execute("PRAGMA table_info(evolution_tasks)").fetchall()}
        if "error" not in task_columns:
            conn.execute("ALTER TABLE evolution_tasks ADD COLUMN error TEXT DEFAULT ''")
        question_columns = {item["name"] for item in conn.execute("PRAGMA table_info(game_questions)").fetchall()}
        for column, definition in {
            "user_id": "INTEGER REFERENCES users(id) ON DELETE CASCADE",
            "pack_id": "INTEGER REFERENCES game_packs(id) ON DELETE CASCADE",
            "source_material_id": "INTEGER REFERENCES materials(id) ON DELETE SET NULL",
            "question_type": "TEXT DEFAULT 'multiple-choice'",
            "sequence": "INTEGER DEFAULT 0",
        }.items():
            if column not in question_columns:
                conn.execute(f"ALTER TABLE game_questions ADD COLUMN {column} {definition}")
        session_columns = {item["name"] for item in conn.execute("PRAGMA table_info(game_sessions)").fetchall()}
        if "pack_id" not in session_columns:
            conn.execute("ALTER TABLE game_sessions ADD COLUMN pack_id INTEGER REFERENCES game_packs(id) ON DELETE SET NULL")
        if "question_id" not in session_columns:
            conn.execute("ALTER TABLE game_sessions ADD COLUMN question_id INTEGER REFERENCES game_questions(id) ON DELETE SET NULL")
        graph_node_columns = {item["name"] for item in conn.execute("PRAGMA table_info(graph_nodes)").fetchall()}
        if "source_material_id" not in graph_node_columns:
            conn.execute("ALTER TABLE graph_nodes ADD COLUMN source_material_id INTEGER REFERENCES materials(id) ON DELETE SET NULL")
        team_columns = {item["name"] for item in conn.execute("PRAGMA table_info(teams)").fetchall()}
        if "settings" not in team_columns:
            conn.execute("ALTER TABLE teams ADD COLUMN settings TEXT NOT NULL DEFAULT '{}'")
        team_material_columns = {item["name"] for item in conn.execute("PRAGMA table_info(team_materials)").fetchall()}
        if "file_path" not in team_material_columns:
            conn.execute("ALTER TABLE team_materials ADD COLUMN file_path TEXT DEFAULT ''")
        if "origin_url" not in team_material_columns:
            conn.execute("ALTER TABLE team_materials ADD COLUMN origin_url TEXT DEFAULT ''")
        share_columns = {item["name"] for item in conn.execute("PRAGMA table_info(team_shares)").fetchall()}
        if "audience_user_ids" not in share_columns:
            conn.execute("ALTER TABLE team_shares ADD COLUMN audience_user_ids TEXT NOT NULL DEFAULT '[]'")
        join_columns = {item["name"] for item in conn.execute("PRAGMA table_info(team_join_requests)").fetchall()}
        if "requested_role" not in join_columns:
            conn.execute("ALTER TABLE team_join_requests ADD COLUMN requested_role TEXT NOT NULL DEFAULT 'viewer'")
        if "invite_id" not in join_columns:
            conn.execute("ALTER TABLE team_join_requests ADD COLUMN invite_id INTEGER REFERENCES team_invites(id) ON DELETE SET NULL")
        now = utcnow()
        for user_item in conn.execute("SELECT id FROM users").fetchall():
            user_id = int(user_item["id"])
            wallet = conn.execute(
                "SELECT id FROM currency_wallets WHERE scope='personal' AND owner_key=?",
                (f"user:{user_id}",),
            ).fetchone()
            if wallet:
                continue
            legacy_coins = int(conn.execute(
                "SELECT COALESCE(SUM(score),0) value FROM game_sessions WHERE user_id=?",
                (user_id,),
            ).fetchone()["value"] or 0)
            initial_coins = 200 + max(0, legacy_coins)
            wallet_id = conn.execute(
                "INSERT INTO currency_wallets(scope,owner_key,user_id,knowledge_balance,truth_balance,created_at,updated_at) "
                "VALUES('personal',?,?,?,?,?,?)",
                (f"user:{user_id}", user_id, initial_coins, 3, now, now),
            ).lastrowid
            conn.execute(
                "INSERT INTO currency_transactions(wallet_id,scope,user_id,currency,amount,balance_after,reason_code,reason,reference_type,reference_id,idempotency_key,metadata,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    wallet_id, "personal", user_id, "knowledge", 200, 200,
                    "welcome_grant", "新用户初始学识币", "user", str(user_id),
                    f"welcome:{user_id}", "{}", now,
                ),
            )
            conn.execute(
                "INSERT INTO currency_transactions(wallet_id,scope,user_id,currency,amount,balance_after,reason_code,reason,reference_type,reference_id,idempotency_key,metadata,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    wallet_id, "personal", user_id, "truth", 3, 3,
                    "welcome_grant", "新用户初始真知晶", "user", str(user_id),
                    f"welcome-truth:{user_id}", "{}", now,
                ),
            )
            if legacy_coins > 0:
                conn.execute(
                    "UPDATE currency_wallets SET knowledge_balance=?,updated_at=? WHERE id=?",
                    (initial_coins, now, wallet_id),
                )
                conn.execute(
                    "INSERT INTO currency_transactions(wallet_id,scope,user_id,currency,amount,balance_after,reason_code,reason,reference_type,reference_id,idempotency_key,metadata,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        wallet_id, "personal", user_id, "knowledge", legacy_coins, initial_coins,
                        "legacy_game_migration", "迁移历史游戏得分为学识币", "migration", str(user_id),
                        f"legacy-game:{user_id}", "{}", now,
                    ),
                )
        for team_item in conn.execute("SELECT id,owner_id FROM teams").fetchall():
            team_id = int(team_item["id"])
            wallet = conn.execute(
                "SELECT id FROM currency_wallets WHERE scope='team' AND owner_key=?",
                (f"team:{team_id}",),
            ).fetchone()
            if wallet:
                continue
            wallet_id = conn.execute(
                "INSERT INTO currency_wallets(scope,owner_key,team_id,knowledge_balance,truth_balance,created_at,updated_at) "
                "VALUES('team',?,?,?,?,?,?)",
                (f"team:{team_id}", team_id, 100, 2, now, now),
            ).lastrowid
            conn.execute(
                "INSERT INTO currency_transactions(wallet_id,scope,user_id,team_id,currency,amount,balance_after,reason_code,reason,reference_type,reference_id,idempotency_key,metadata,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    wallet_id, "team", int(team_item["owner_id"]), team_id, "knowledge", 100, 100,
                    "team_seed_grant", "团队初始学识币", "team", str(team_id),
                    f"team-seed:{team_id}", "{}", now,
                ),
            )
            conn.execute(
                "INSERT INTO currency_transactions(wallet_id,scope,user_id,team_id,currency,amount,balance_after,reason_code,reason,reference_type,reference_id,idempotency_key,metadata,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    wallet_id, "team", int(team_item["owner_id"]), team_id, "truth", 2, 2,
                    "team_seed_grant", "团队初始真知晶", "team", str(team_id),
                    f"team-seed-truth:{team_id}", "{}", now,
                ),
            )
        first_user = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        existing_team = conn.execute("SELECT id FROM teams LIMIT 1").fetchone()
        if first_user and not existing_team:
            seed_team_id = conn.execute(
                "INSERT INTO teams(owner_id,name,description,team_type,settings,created_at) VALUES(?,?,?,?,?,?)",
                (
                    int(first_user["id"]),
                    "知衍示范团队",
                    "用于演示团队空间隔离、成员协作和团队知识库管理。",
                    "learning",
                    json.dumps({
                        "allow_editor_external_share": False,
                        "review_strategy": "owner_final",
                        "watermark_enabled": True,
                        "auto_evolution_enabled": False,
                        "auto_evolution_time": "02:00",
                        "game_multiplayer_enabled": True,
                        "queue_prefix": "team",
                    }, ensure_ascii=False),
                    utcnow(),
                ),
            ).lastrowid
            conn.execute(
                "INSERT INTO team_members(team_id,user_id,role,status,joined_at,last_active_at) VALUES(?,?,?,?,?,?)",
                (seed_team_id, int(first_user["id"]), "owner", "active", utcnow(), utcnow()),
            )
            lib_id = conn.execute(
                "INSERT INTO team_knowledge_libs(team_id,name,description,category,dataset_key,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                (seed_team_id, "团队知识中枢", "独立于个人知识库的团队协作库。", "通用", f"team_{seed_team_id}_core", int(first_user["id"]), utcnow()),
            ).lastrowid
            conn.execute(
                "INSERT INTO team_materials(team_id,lib_id,uploader_id,name,source,kind,size,tags,content,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    seed_team_id,
                    lib_id,
                    int(first_user["id"]),
                    "团队端落地蓝图.md",
                    "manual",
                    "Markdown",
                    2048,
                    json.dumps(["团队端", "PRD", "架构"], ensure_ascii=False),
                    "团队空间使用独立团队表、团队知识库、团队素材和团队日志，避免与个人端数据互相穿透。",
                    utcnow(),
                    utcnow(),
                ),
            )
            conn.execute(
                "INSERT INTO team_system_logs(team_id,user_id,module,action,detail,created_at) VALUES(?,?,?,?,?,?)",
                (seed_team_id, int(first_user["id"]), "team", "seed", "创建示范团队空间", utcnow()),
            )
        existing = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        if existing:
            return
        password = bcrypt.hashpw(b"demo123456", bcrypt.gensalt()).decode()
        user_id = conn.execute(
            "INSERT INTO users(username,password_hash,nickname,created_at) VALUES(?,?,?,?)",
            ("demo@zhiyan.ai", password, "Alex Chen", utcnow()),
        ).lastrowid
        conn.execute("INSERT INTO user_settings(user_id) VALUES(?)", (user_id,))
        seed_team_id = conn.execute(
            "INSERT INTO teams(owner_id,name,description,team_type,settings,created_at) VALUES(?,?,?,?,?,?)",
            (
                user_id,
                "知衍示范团队",
                "用于演示团队空间隔离、成员协作和团队知识库管理。",
                "learning",
                json.dumps({
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
                }, ensure_ascii=False),
                utcnow(),
            ),
        ).lastrowid
        conn.execute(
            "INSERT INTO team_members(team_id,user_id,role,status,joined_at,last_active_at) VALUES(?,?,?,?,?,?)",
            (seed_team_id, user_id, "owner", "active", utcnow(), utcnow()),
        )
        seed_lib_id = conn.execute(
            "INSERT INTO team_knowledge_libs(team_id,name,description,category,dataset_key,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
            (seed_team_id, "团队知识中枢", "独立于个人知识库的团队协作库。", "通用", f"team_{seed_team_id}_core", user_id, utcnow()),
        ).lastrowid
        conn.execute(
            "INSERT INTO team_materials(team_id,lib_id,uploader_id,name,source,kind,size,tags,content,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                seed_team_id,
                seed_lib_id,
                user_id,
                "团队端落地蓝图.md",
                "manual",
                "Markdown",
                2048,
                json.dumps(["团队端", "PRD", "架构"], ensure_ascii=False),
                "团队空间使用独立团队表、团队知识库、团队素材和团队日志，避免与个人端数据互相穿透。",
                utcnow(),
                utcnow(),
            ),
        )
        conn.execute(
            "INSERT INTO team_system_logs(team_id,user_id,module,action,detail,created_at) VALUES(?,?,?,?,?,?)",
            (seed_team_id, user_id, "team", "seed", "创建示范团队空间", utcnow()),
        )
        seed_materials = [
            ("神经网络优化指南.pdf", "upload", "PDF", 4_404_019, "ready", "人工智能", "反向传播通过梯度下降优化神经网络参数。学习率与正则化决定模型的泛化能力。"),
            ("第一天研讨会录像.mp4", "video", "视频", 134_217_728, "processing", "研究记录", "神经架构与检索增强生成研讨会自动转写内容。"),
            ("RAGFlow 多路召回笔记.md", "manual", "Markdown", 18_420, "ready", "RAG", "RAGFlow 通过向量、全文与图谱三路召回融合提升知识检索覆盖率。"),
            ("量子力学入门", "url", "网页", 8_640, "ready", "物理", "量子纠缠描述多个粒子之间无法由经典局域变量解释的关联。"),
        ]
        for item in seed_materials:
            conn.execute(
                "INSERT INTO materials(user_id,name,source,kind,size,status,category,content,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (user_id, *item, utcnow()),
            )
        questions = [
            ("flashcard", "easy", "RAG 的英文全称是什么？", ["Retrieval-Augmented Generation", "Random Agent Graph", "Recursive AI Gateway"], "Retrieval-Augmented Generation", "RAG 指检索增强生成。", "RAG"),
            ("flashcard", "medium", "反向传播的核心作用是什么？", ["更新网络参数", "增加数据量", "压缩模型"], "更新网络参数", "反向传播计算梯度并指导优化器更新权重。", "人工智能"),
            ("monopoly", "medium", "多路召回中，BM25 主要解决哪类匹配？", ["关键词匹配", "图像匹配", "时间序列"], "关键词匹配", "BM25 是经典的全文相关性排序算法。", "RAG"),
            ("matching", "hard", "请选择与 Milvus Lite 最匹配的定义", ["嵌入式向量数据库", "消息队列", "关系数据库"], "嵌入式向量数据库", "Milvus Lite 提供本地嵌入式向量检索。", "向量检索"),
        ]
        for game, difficulty, prompt, options, answer, explanation, topic in questions:
            conn.execute(
                "INSERT INTO game_questions(game,difficulty,prompt,options,answer,explanation,topic) VALUES(?,?,?,?,?,?,?)",
                (game, difficulty, prompt, json.dumps(options, ensure_ascii=False), answer, explanation, topic),
            )
        nodes = [
            ("核心 AI 启发式", "逻辑", 84, "知识生态系统中的空间感知算法基础。"),
            ("量子纠缠", "创意", 72, "量子系统之间的非经典关联。"),
            ("神经路径", "逻辑", 91, "模型中的信息传播与表征路径。"),
            ("已掌握集群", "记忆", 96, "完成复习并达到稳定掌握的知识集合。"),
            ("RAGFlow", "逻辑", 78, "融合向量、全文与图谱召回的知识引擎。"),
            ("BGE-M3", "记忆", 66, "支持多语言和多粒度的嵌入模型。"),
        ]
        node_ids = []
        for node in nodes:
            node_ids.append(conn.execute(
                "INSERT INTO graph_nodes(user_id,label,category,mastery,summary) VALUES(?,?,?,?,?)", (user_id, *node)
            ).lastrowid)
        for source, target, weight in [(0,1,0.8),(0,2,0.9),(0,3,0.7),(2,4,0.9),(4,5,0.85),(3,5,0.6)]:
            conn.execute("INSERT INTO graph_edges(user_id,source,target,weight) VALUES(?,?,?,?)", (user_id,node_ids[source],node_ids[target],weight))
        conn.execute(
            "INSERT INTO evolution_tasks(user_id,mode,status,progress,improvements,corrections,expansions,summary,created_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (user_id,"auto","completed",100,124,18,42,"系统完成知识一致性审计，修复语义漂移并建立 42 条新关联。",utcnow(),utcnow()),
        )
        for module, action, detail in [
            ("material","upload","上传神经网络优化指南.pdf"),
            ("evolution","complete","自动进化完成，新增 42 条关联"),
            ("game","finish","智能闪卡得分 2450"),
        ]:
            conn.execute("INSERT INTO system_logs(user_id,module,action,detail,created_at) VALUES(?,?,?,?,?)", (user_id,module,action,detail,utcnow()))


def log_event(user_id: int, module: str, action: str, detail: str) -> None:
    execute("INSERT INTO system_logs(user_id,module,action,detail,created_at) VALUES(?,?,?,?,?)", (user_id,module,action,detail,utcnow()))
