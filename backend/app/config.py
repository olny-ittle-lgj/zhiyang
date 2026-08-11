from dataclasses import dataclass
from pathlib import Path
import os
import tempfile
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _resolve_path(value: str | os.PathLike[str] | None, default: Path) -> Path:
    raw = os.path.expandvars(os.path.expanduser(str(value or "").strip()))
    path = Path(raw) if raw else default
    return path if path.is_absolute() else BASE_DIR / path


@dataclass(frozen=True)
class Settings:
    app_name: str = "知衍 API"
    secret_key: str = os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET_KEY", "change-me-in-production-zhiyan")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    # Access tokens are short-lived; refresh tokens keep a signed session
    # alive without requiring the user to log in again.
    jwt_expire_minutes: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    refresh_token_expire_days: int = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    database_path: Path = _resolve_path(os.getenv("DATABASE_PATH"), BASE_DIR / "data" / "zhiyan.db")
    upload_dir: Path = _resolve_path(os.getenv("UPLOAD_DIR"), BASE_DIR / "data" / "uploads")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    deepseek_proxy_url: str = os.getenv("DEEPSEEK_PROXY_URL", "").strip()
    bge_m3_model: str = os.getenv("BGE_M3_MODEL", "BAAI/bge-m3")
    bge_m3_device: str = os.getenv("BGE_M3_DEVICE", "")
    bge_m3_backend: str = os.getenv("BGE_M3_BACKEND", "torch").strip().lower() or "torch"
    bge_m3_onnx_file: str = os.getenv("BGE_M3_ONNX_FILE", "").strip()
    model_cache_dir: Path = _resolve_path(
        os.getenv("HF_HOME") or os.getenv("SENTENCE_TRANSFORMERS_HOME"),
        Path(tempfile.gettempdir()) / "zhiyan-huggingface",
    )
    milvus_enabled: bool = os.getenv("MILVUS_ENABLED", "true").lower() in ("1", "true", "yes")
    milvus_uri: str = os.getenv("MILVUS_URI", "").strip()
    milvus_token: str = os.getenv("MILVUS_TOKEN", "")
    milvus_db_path: Path = _resolve_path(
        os.getenv("MILVUS_DB_PATH"),
        Path(tempfile.gettempdir()) / "zhiyan-milvus-standard.db",
    )
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    max_upload_bytes: int = 200 * 1024 * 1024
    # FETCH_MCP_URL is the current transport-neutral setting. Keep the SSE
    # name as a fallback so existing deployments remain compatible.
    fetch_mcp_url: str = (os.getenv("FETCH_MCP_URL") or os.getenv("FETCH_MCP_SSE_URL", "")).strip()
    fetch_mcp_transport: str = os.getenv("FETCH_MCP_TRANSPORT", "auto").strip().lower() or "auto"
    fetch_mcp_token: str = os.getenv("FETCH_MCP_TOKEN", "")
    fetch_mcp_tool: str = os.getenv("FETCH_MCP_TOOL", "fetch").strip() or "fetch"
    fetch_mcp_timeout: float = float(os.getenv("FETCH_MCP_TIMEOUT", "30"))
    fetch_mcp_max_chars: int = int(os.getenv("FETCH_MCP_MAX_CHARS", "100000"))
    fetch_direct_timeout: float = float(os.getenv("FETCH_DIRECT_TIMEOUT", "15"))
    ocr_max_image_bytes: int = int(os.getenv("OCR_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
    ocr_max_image_pixels: int = int(os.getenv("OCR_MAX_IMAGE_PIXELS", "40000000"))
    video_analysis_timeout: int = int(os.getenv("VIDEO_ANALYSIS_TIMEOUT", "45"))
    video_ocr_frame_count: int = int(os.getenv("VIDEO_OCR_FRAME_COUNT", "3"))
    video_max_duration_seconds: int = int(os.getenv("VIDEO_MAX_DURATION_SECONDS", "1800"))
    video_max_pixels: int = int(os.getenv("VIDEO_MAX_PIXELS", str(3840 * 2160)))
settings = Settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
