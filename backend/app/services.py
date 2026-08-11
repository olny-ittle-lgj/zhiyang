"""
Service connection layer for ZhiYan AI.
Connects to Docker-hosted services: Redis, Elasticsearch, RabbitMQ, MySQL, and Milvus Lite.
Each service has a lazy initialization pattern — only connects when actually used.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

from .config import settings
from .embeddings import StandardRuntimeError, bge_m3_embedding, embedding_runtime_status

logger = logging.getLogger("zhiyan.services")


# ---------------------------------------------------------------------------
# Connection pool helpers
# ---------------------------------------------------------------------------

def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default).lower()).lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

_redis_client: Any = None  # redis.Redis | None


def get_redis():
    """Return a Redis client connected to the configured Docker Redis instance."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not _env_bool("REDIS_ENABLED"):
        return None
    try:
        import redis as _redis
        _redis_client = _redis.Redis(
            host=os.getenv("REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            db=int(os.getenv("REDIS_DB", "0")),
            socket_connect_timeout=3,
            decode_responses=True,
        )
        _redis_client.ping()
        logger.info("Redis connected successfully")
    except Exception as exc:
        logger.warning("Redis unavailable: %s", exc)
        _redis_client = None
    return _redis_client


def redis_cache_get(key: str) -> str | None:
    """Get a value from Redis cache."""
    global _redis_client
    r = get_redis()
    if r is None:
        return None
    try:
        return r.get(key)
    except Exception as exc:
        logger.warning("Redis get error for %s: %s", key, exc)
        # Force a reconnect on the next request after a dropped connection.
        _redis_client = None
        return None


def redis_cache_set(key: str, value: str, ttl: int = 300) -> bool:
    """Set a value in Redis cache with optional TTL (seconds)."""
    global _redis_client
    r = get_redis()
    if r is None:
        return False
    try:
        r.setex(key, ttl, value)
        return True
    except Exception as exc:
        logger.warning("Redis set error for %s: %s", key, exc)
        _redis_client = None
        return False


def redis_cache_delete(key: str) -> bool:
    global _redis_client
    r = get_redis()
    if r is None:
        return False
    try:
        r.delete(key)
        return True
    except Exception as exc:
        logger.warning("Redis delete error for %s: %s", key, exc)
        _redis_client = None
        return False


def redis_cache_get_json(key: str) -> dict | list | None:
    """Read a JSON value from Redis without leaking decode errors to callers."""
    value = redis_cache_get(key)
    if not value:
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, (dict, list)) else None
    except (TypeError, ValueError):
        redis_cache_delete(key)
        return None


def redis_cache_set_json(key: str, value: dict | list, ttl: int = 300) -> bool:
    """Serialize and cache a JSON-compatible value with a bounded TTL."""
    return redis_cache_set(key, json.dumps(value, ensure_ascii=False, default=str), ttl=max(1, int(ttl)))


def redis_cache_delete_pattern(pattern: str) -> int:
    """Delete all keys matching a narrowly scoped application pattern."""
    global _redis_client
    r = get_redis()
    if r is None:
        return 0
    try:
        keys = list(r.scan_iter(match=pattern, count=100))
        return int(r.delete(*keys)) if keys else 0
    except Exception as exc:
        logger.warning("Redis pattern delete error for %s: %s", pattern, exc)
        _redis_client = None
        return 0


# ---------------------------------------------------------------------------
# Elasticsearch
# ---------------------------------------------------------------------------

_es_client: Any = None  # elasticsearch.Elasticsearch | None
_es_ready_indices: set[str] = set()


def _ensure_es_index(es: Any, index: str) -> None:
    """Create the application index with stable mappings before first use."""
    if index in _es_ready_indices:
        return
    if es.indices.exists(index=index):
        _es_ready_indices.add(index)
        return
    mappings = {
        "properties": {
            "id": {"type": "integer"},
            "user_id": {"type": "integer"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "content": {"type": "text"},
            "kind": {"type": "keyword"},
            "category": {"type": "keyword"},
            "status": {"type": "keyword"},
            "origin_url": {"type": "keyword", "ignore_above": 1024},
            "created_at": {"type": "date"},
        }
    }
    try:
        es.indices.create(index=index, mappings=mappings)
    except Exception:
        # Another worker may have created it between exists/create.
        if not es.indices.exists(index=index):
            raise
    _es_ready_indices.add(index)


def get_elasticsearch():
    """Return an Elasticsearch client for full-text search."""
    global _es_client
    if _es_client is not None:
        return _es_client
    if not _env_bool("ELASTICSEARCH_ENABLED"):
        return None
    try:
        from elasticsearch import Elasticsearch
        host = os.getenv("ELASTICSEARCH_HOST", "127.0.0.1")
        port = int(os.getenv("ELASTICSEARCH_PORT", "9200"))
        user = os.getenv("ELASTICSEARCH_USER", "elastic")
        password = os.getenv("ELASTICSEARCH_PASSWORD", "")
        _es_client = Elasticsearch(
            [f"http://{host}:{port}"],
            basic_auth=(user, password),
            verify_certs=False,
            request_timeout=10,
        )
        if _es_client.ping():
            logger.info("Elasticsearch connected successfully")
        else:
            logger.warning("Elasticsearch ping failed")
            _es_client = None
    except Exception as exc:
        logger.warning("Elasticsearch unavailable: %s", exc)
        _es_client = None
    return _es_client


def es_index_document(index: str, doc_id: str, body: dict) -> bool:
    """Index a document in Elasticsearch."""
    mysql_synced = False
    vector_synced = True
    if index == "zhiyan_materials" and body.get("id") is not None and body.get("user_id") is not None:
        mysql_synced = mysql_upsert_material(body)
        vector_synced = index_material_vectors(body)
    es = get_elasticsearch()
    if es is None:
        return mysql_synced and vector_synced
    try:
        _ensure_es_index(es, index)
        es.index(index=index, id=doc_id, document=body, refresh="wait_for")
        return vector_synced
    except Exception as exc:
        logger.warning("ES index error: %s", exc)
        return vector_synced


def es_search(
    index: str,
    query: str,
    fields: list[str] | None = None,
    size: int = 10,
    user_id: int | str | None = None,
) -> list[dict]:
    """Full-text search in Elasticsearch."""
    es = get_elasticsearch()
    if es is None:
        return []
    if not query or not query.strip():
        return []
    try:
        _ensure_es_index(es, index)
        search_fields = fields or ["content", "name"]
        match_query: dict[str, Any] = {
            "multi_match": {
                "query": query,
                "fields": search_fields,
                "type": "best_fields",
            }
        }
        query_body: dict[str, Any] = match_query
        if user_id is not None:
            query_body = {
                "bool": {
                    "must": [match_query],
                    "filter": [{"term": {"user_id": int(user_id)}}],
                }
            }
        result = es.search(
            index=index,
            body={
                "query": query_body,
                "size": size,
            },
        )
        return [hit["_source"] for hit in result["hits"]["hits"]]
    except Exception as exc:
        logger.warning("ES search error: %s", exc)
        return []


def es_delete_document(index: str, doc_id: str) -> bool:
    """Delete a document while treating an already absent document as success."""
    mysql_deleted = mysql_delete_material(doc_id) if index == "zhiyan_materials" else False
    if index == "zhiyan_materials":
        milvus_delete_document(doc_id=doc_id)
    es = get_elasticsearch()
    if es is None:
        return mysql_deleted
    try:
        _ensure_es_index(es, index)
        response = es.delete(index=index, id=doc_id, refresh="wait_for", ignore=[404])
        return int(response.get("status", 200)) < 500 or mysql_deleted
    except Exception as exc:
        logger.warning("ES delete error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# RabbitMQ
# ---------------------------------------------------------------------------

_rabbitmq_connection: Any = None  # pika.BlockingConnection | None


def get_rabbitmq():
    """Return a RabbitMQ connection for async task publishing."""
    global _rabbitmq_connection
    if _rabbitmq_connection is not None and not _rabbitmq_connection.is_closed:
        return _rabbitmq_connection
    if not _env_bool("RABBITMQ_ENABLED"):
        return None
    try:
        import pika
        host = os.getenv("RABBITMQ_HOST", "127.0.0.1")
        port = int(os.getenv("RABBITMQ_PORT", "5672"))
        user = os.getenv("RABBITMQ_USER", "guest")
        password = os.getenv("RABBITMQ_PASSWORD", "guest")
        params = pika.ConnectionParameters(
            host=host, port=port,
            credentials=pika.PlainCredentials(user, password),
            heartbeat=600,
            blocked_connection_timeout=300,
        )
        _rabbitmq_connection = pika.BlockingConnection(params)
        logger.info("RabbitMQ connected successfully")
    except Exception as exc:
        logger.warning("RabbitMQ unavailable: %s", exc)
        _rabbitmq_connection = None
    return _rabbitmq_connection


def rabbitmq_publish(queue: str, message: dict) -> bool:
    """Publish a JSON message to a RabbitMQ queue (creates queue if needed)."""
    conn = get_rabbitmq()
    if conn is None:
        return False
    try:
        import pika
        channel = conn.channel()
        channel.queue_declare(queue=queue, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=queue,
            body=json.dumps(message, ensure_ascii=False),
            properties=pika.BasicProperties(delivery_mode=2),  # persistent
        )
        channel.close()
        return True
    except Exception as exc:
        logger.warning("RabbitMQ publish error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# MySQL (Alchemy-style helper — uses pymysql directly for simplicity)
# ---------------------------------------------------------------------------

_mysql_conn: Any = None
_mysql_schema_ready = False


def get_mysql():
    """Return a pymysql connection to the Docker MySQL instance."""
    global _mysql_conn
    if _mysql_conn is not None:
        try:
            _mysql_conn.ping(reconnect=True)
            return _mysql_conn
        except Exception:
            _mysql_conn = None
    if not _env_bool("MYSQL_ENABLED"):
        return None
    try:
        import pymysql
        _mysql_conn = pymysql.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3307")),
            user=os.getenv("MYSQL_USER", "zhiyan"),
            password=os.getenv("MYSQL_PASSWORD", "zhiyan2024!"),
            database=os.getenv("MYSQL_DATABASE", "zhiyan"),
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=5,
        )
        logger.info("MySQL connected successfully")
    except Exception as exc:
        logger.warning("MySQL unavailable: %s", exc)
        _mysql_conn = None
    return _mysql_conn


def mysql_execute(sql: str, params: tuple | None = None) -> int | None:
    """Execute SQL and return lastrowid."""
    conn = get_mysql()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.lastrowid
    except Exception as exc:
        logger.warning("MySQL execute error: %s", exc)
        return None


def mysql_fetchall(sql: str, params: tuple | None = None) -> list[dict]:
    """Execute SQL and return all rows as dicts."""
    conn = get_mysql()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [col[0] for col in cur.description] if cur.description else []
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("MySQL fetch error: %s", exc)
        return []


def mysql_fetchone(sql: str, params: tuple | None = None) -> dict | None:
    """Execute SQL and return one row as dict."""
    rows = mysql_fetchall(sql, params)
    return rows[0] if rows else None


def mysql_initialize_schema() -> bool:
    """Create the external material mirror used by search/reporting flows."""
    global _mysql_schema_ready
    if _mysql_schema_ready:
        return True
    conn = get_mysql()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS zhiyan_material_index (
                    material_id BIGINT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    kind VARCHAR(64) NOT NULL,
                    category VARCHAR(128) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    content LONGTEXT NOT NULL,
                    origin_url VARCHAR(1024) NOT NULL DEFAULT '',
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_material_user (user_id),
                    FULLTEXT KEY ft_material_text (name, content)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
            )
        _mysql_schema_ready = True
        return True
    except Exception as exc:
        logger.warning("MySQL schema initialization error: %s", exc)
        return False


def mysql_upsert_material(body: dict) -> bool:
    """Mirror a material after its transactional SQLite write."""
    if not mysql_initialize_schema():
        return False
    conn = get_mysql()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO zhiyan_material_index
                (material_id,user_id,name,kind,category,status,content,origin_url)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                user_id=VALUES(user_id),name=VALUES(name),kind=VALUES(kind),
                category=VALUES(category),status=VALUES(status),content=VALUES(content),
                origin_url=VALUES(origin_url)""",
                (
                    int(body.get("id")), int(body.get("user_id")), str(body.get("name", ""))[:255],
                    str(body.get("kind", ""))[:64], str(body.get("category", ""))[:128],
                    str(body.get("status", "ready"))[:32], str(body.get("content", "")),
                    str(body.get("origin_url", ""))[:1024],
                ),
            )
        return True
    except Exception as exc:
        logger.warning("MySQL material mirror error: %s", exc)
        return False


def mysql_delete_material(material_id: str | int) -> bool:
    if not mysql_initialize_schema():
        return False
    conn = get_mysql()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM zhiyan_material_index WHERE material_id=%s", (int(material_id),))
        return True
    except Exception as exc:
        logger.warning("MySQL material delete error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Milvus Lite (embedded vector database)
# ---------------------------------------------------------------------------

_milvus_client: Any = None


def get_milvus():
    """Return a Milvus Lite client for vector storage/retrieval."""
    global _milvus_client
    if _milvus_client is not None:
        return _milvus_client
    if not settings.milvus_enabled:
        return None
    try:
        from pymilvus import MilvusClient, DataType

        milvus_uri = settings.milvus_uri
        if milvus_uri:
            _milvus_client = MilvusClient(uri=milvus_uri, token=settings.milvus_token)
        else:
            configured_path = settings.milvus_db_path
            fallback_path = Path(tempfile.gettempdir()) / "zhiyan-milvus-fallback.db"
            paths = [configured_path]
            if configured_path != fallback_path:
                paths.append(fallback_path)
            last_error: Exception | None = None
            for db_path in paths:
                try:
                    # Ensure the parent exists; Milvus Lite owns the database directory.
                    db_path.parent.mkdir(parents=True, exist_ok=True)
                    _milvus_client = MilvusClient(str(db_path))
                    break
                except Exception as exc:
                    last_error = exc
                    logger.warning("Milvus Lite path unavailable (%s): %s", db_path, exc)
            if _milvus_client is None and last_error is not None:
                raise last_error

        # Create collection if not exists
        collection_name = "knowledge_chunks"
        if collection_name not in _milvus_client.list_collections():
            schema = _milvus_client.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=64, is_primary=True)
            schema.add_field(field_name="user_id", datatype=DataType.VARCHAR, max_length=32)
            schema.add_field(field_name="doc_id", datatype=DataType.VARCHAR, max_length=64)
            schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535)
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=1024)
            schema.add_field(field_name="topics", datatype=DataType.VARCHAR, max_length=512)

            # pymilvus 2.6+ requires its typed IndexParams object here;
            # older releases accepted a plain dictionary.  Build the typed
            # object when available and retain the dictionary fallback for
            # older standalone deployments.
            index_type = os.getenv("MILVUS_INDEX_TYPE", "FLAT").strip().upper() or "FLAT"
            try:
                index_params = _milvus_client.prepare_index_params()
                index_kwargs = {
                    "field_name": "vector",
                    "index_type": index_type,
                    "metric_type": "COSINE",
                }
                if index_type != "FLAT":
                    index_kwargs["params"] = {"nlist": 128}
                index_params.add_index(**index_kwargs)
            except AttributeError:
                index_params = {
                    "metric_type": "COSINE",
                    "index_type": index_type,
                }
                if index_type != "FLAT":
                    index_params["params"] = {"nlist": 128}
            _milvus_client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )
            logger.info("Milvus Lite collection 'knowledge_chunks' created")

        # Milvus Lite creates collections in the released state. Loading here
        # keeps search available immediately after the first write or restart.
        _milvus_client.load_collection(collection_name=collection_name)
        logger.info("Milvus connected successfully")
    except Exception as exc:
        logger.warning("Milvus Lite unavailable: %s", exc)
        _milvus_client = None
    return _milvus_client


def milvus_insert(chunks: list[dict]) -> bool:
    """Insert vectorized chunks into Milvus. Each chunk must have chunk_id, user_id, doc_id, text, vector, topics."""
    client = get_milvus()
    if client is None:
        return False
    try:
        client.insert(collection_name="knowledge_chunks", data=chunks)
        return True
    except Exception as exc:
        logger.warning("Milvus insert error: %s", exc)
        return False


def milvus_search(query_vector: list[float], user_id: str, top_k: int = 10, doc_id: str | None = None) -> list[dict]:
    """Search Milvus for similar vectors."""
    client = get_milvus()
    if client is None:
        return []
    try:
        expression = f'user_id == "{user_id}"'
        if doc_id is not None:
            expression += f' and doc_id == "{doc_id}"'
        results = client.search(
            collection_name="knowledge_chunks",
            data=[query_vector],
            limit=top_k,
            output_fields=["chunk_id", "text", "doc_id", "topics"],
            filter=expression,
        )
        return results[0] if results else []
    except Exception as exc:
        logger.warning("Milvus search error: %s", exc)
        return []


def _semantic_chunks(text: str, *, max_chars: int = 1_200, overlap: int = 160) -> list[str]:
    """Create LangChain recursive chunks for BGE-M3 indexing."""
    value = str(text or "").strip()
    if not value:
        return []
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError as exc:
        raise StandardRuntimeError("缺少 langchain-text-splitters，无法执行标准语义分块") from exc
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_chars,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
    )
    return splitter.split_text(value)[:200]


def milvus_delete_document(user_id: str | int | None = None, doc_id: str | int | None = None) -> bool:
    """Delete indexed vectors for one document or one user's document set."""
    client = get_milvus()
    if client is None:
        return False
    clauses: list[str] = []
    if user_id is not None:
        clauses.append(f'user_id == "{user_id}"')
    if doc_id is not None:
        clauses.append(f'doc_id == "{doc_id}"')
    if not clauses:
        return False
    try:
        client.delete(collection_name="knowledge_chunks", filter=" and ".join(clauses))
        return True
    except Exception as exc:
        logger.warning("Milvus delete error: %s", exc)
        return False


def index_material_vectors(body: dict) -> bool:
    """Index one ready material with PRD-standard BGE-M3 embeddings in Milvus Lite."""
    if str(body.get("status", "ready")) != "ready":
        return True
    text = str(body.get("content") or "").strip()
    if not text:
        return True
    client = get_milvus()
    if client is None:
        raise StandardRuntimeError("标准模式需要 Milvus Lite/Milvus Standalone，但当前 Milvus 不可用")

    user_id = str(body["user_id"])
    doc_id = str(body["id"])
    milvus_delete_document(user_id=user_id, doc_id=doc_id)
    chunks = []
    for index, chunk in enumerate(_semantic_chunks(text)):
        vector_text = f"{body.get('name', '')}\n{body.get('category', '')}\n{chunk}".strip()
        chunks.append({
            "chunk_id": f"material-{doc_id}-{index}",
            "user_id": user_id,
            "doc_id": doc_id,
            "text": chunk[:65_000],
            "vector": bge_m3_embedding(vector_text),
            "topics": str(body.get("category") or body.get("name") or "")[:500],
        })
    if not chunks:
        return True
    return milvus_insert(chunks)


def mysql_fulltext_search(query: str, user_id: int | str, size: int = 10) -> list[dict]:
    """Use the PRD MySQL FULLTEXT path when Elasticsearch is not available."""
    value = str(query or "").strip()
    if not value:
        return []
    return mysql_fetchall(
        "SELECT material_id id,name,content,category,status,origin_url,"
        "MATCH(name,content) AGAINST(%s IN NATURAL LANGUAGE MODE) score "
        "FROM zhiyan_material_index WHERE user_id=%s "
        "AND MATCH(name,content) AGAINST(%s IN NATURAL LANGUAGE MODE) "
        "ORDER BY score DESC LIMIT %s",
        (value, int(user_id), value, int(size)),
    )


def hybrid_search(query: str, user_id: int | str, top_k: int = 5) -> list[dict]:
    """Hybrid retrieval: Milvus vector search plus ES/MySQL full-text, fused by RRF."""
    value = str(query or "").strip()
    if not value:
        return []

    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    query_vector = bge_m3_embedding(value)
    for rank, hit in enumerate(milvus_search(query_vector, str(user_id), top_k=top_k * 2), start=1):
        entity = hit.get("entity") if isinstance(hit.get("entity"), dict) else hit
        doc_id = str(entity.get("doc_id") or hit.get("doc_id") or "")
        if not doc_id:
            continue
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (60 + rank)
        payloads.setdefault(doc_id, {
            "id": doc_id,
            "name": entity.get("topics") or "Milvus 命中",
            "content": entity.get("text") or "",
            "retrieval": "milvus",
        })

    fulltext_results = es_search("zhiyan_materials", value, fields=["content", "name"], size=top_k * 2, user_id=user_id)
    if not fulltext_results:
        fulltext_results = mysql_fulltext_search(value, user_id, size=top_k * 2)
    for rank, item in enumerate(fulltext_results, start=1):
        doc_id = str(item.get("id") or item.get("material_id") or "")
        if not doc_id:
            continue
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (60 + rank)
        payloads[doc_id] = {**item, "id": doc_id, "retrieval": item.get("retrieval", "fulltext")}

    if not scores:
        return []

    missing_ids = [int(doc_id) for doc_id, payload in payloads.items() if payload.get("name") == "Milvus 命中" and doc_id.isdigit()]
    if missing_ids:
        try:
            from .database import rows
            placeholders = ",".join("?" for _ in missing_ids)
            for item in rows(f"SELECT id,name,content,category FROM materials WHERE id IN ({placeholders})", tuple(missing_ids)):
                payloads[str(item["id"])] = {**item, "retrieval": payloads[str(item["id"])].get("retrieval", "milvus")}
        except Exception:
            logger.debug("Could not enrich Milvus hits from SQLite", exc_info=True)

    ranked_ids = sorted(scores, key=lambda doc_id: scores[doc_id], reverse=True)[:top_k]
    return [{**payloads[doc_id], "rrf_score": round(scores[doc_id], 6)} for doc_id in ranked_ids]


# ---------------------------------------------------------------------------
# Service health summary
# ---------------------------------------------------------------------------

def all_services_health() -> dict[str, str]:
    """Return a health summary of all services."""
    def state(flag: str, client: Any) -> str:
        if client is not None:
            return "active"
        return "error" if _env_bool(flag) else "not_configured"

    result = {
        "redis": state("REDIS_ENABLED", get_redis()),
        "elasticsearch": state("ELASTICSEARCH_ENABLED", get_elasticsearch()),
        "rabbitmq": state("RABBITMQ_ENABLED", get_rabbitmq()),
        "mysql": state("MYSQL_ENABLED", get_mysql()),
        "milvus": state("MILVUS_ENABLED", get_milvus()),
        "bge_m3": embedding_runtime_status()["status"],
    }
    return result


# late import
from pathlib import Path
