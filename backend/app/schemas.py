from typing import Literal

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    nickname: str = Field(min_length=1, max_length=40)


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=4096)


class TextMaterialRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    category: str = Field(default="未分类", max_length=80)


class UrlMaterialRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    name: str = Field(default="网页素材", min_length=1, max_length=200)
    category: str = Field(default="未分类", max_length=80)
    content: str | None = Field(default=None, min_length=1)


class UrlPreviewRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


class CustomerServiceMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class CustomerServiceAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[CustomerServiceMessage] = Field(default_factory=list, max_length=20)


class MaterialAskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


class EvolutionRequest(BaseModel):
    mode: Literal["auto", "manual"] = "manual"
    material_ids: list[int] = Field(min_length=1, max_length=10)


class ReviewRequest(BaseModel):
    decision: Literal["accepted", "rejected"]
    proposed_text: str | None = None


class GameSubmitRequest(BaseModel):
    question_id: int
    answer: str
    duration: int = Field(default=20, ge=0)
    pack_id: int | None = None


class GameGenerateRequest(BaseModel):
    game: Literal["flashcard", "monopoly", "matching"]
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    material_ids: list[int] = Field(min_length=1, max_length=10)


class MatchingRoundRequest(BaseModel):
    pack_id: int = Field(gt=0)
    round: int = Field(default=1, ge=1, le=10000)


class GraphRebuildRequest(BaseModel):
    material_ids: list[int] = Field(default_factory=list, max_length=50)
    node_limit: int = Field(default=80, ge=8, le=300)


class GraphReviewRequest(BaseModel):
    result: Literal["known", "weak"]


class MemoryGameCompleteRequest(BaseModel):
    difficulty: Literal["easy", "hard"] = "easy"
    moves: int = Field(ge=8, le=500)
    duration: int = Field(ge=1, le=86_400)
    pack_id: int | None = Field(default=None, gt=0)


class ShareRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    scope: str = "all"
    expires_days: int | None = Field(default=30, ge=1, le=3650)
    password: str | None = Field(default=None, min_length=4, max_length=8)


class SettingsRequest(BaseModel):
    auto_evolution: bool
    trigger_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    evolution_mode: Literal["auto", "manual"]
    monopoly_difficulty: Literal["easy", "medium", "hard"]
    flashcard_difficulty: Literal["easy", "medium", "hard"]
    matching_difficulty: Literal["easy", "medium", "hard"]
    gamified_review: bool


class StorePurchaseRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=80)
    quantity: int = Field(default=1, ge=1, le=99)
    idempotency_key: str | None = Field(default=None, max_length=200)


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    team_type: Literal["learning", "research", "studio"] = "learning"
    avatar: str = Field(default="", max_length=500)


class TeamUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    team_type: Literal["learning", "research", "studio"] | None = None
    avatar: str | None = Field(default=None, max_length=500)
    status: Literal["active", "archived", "frozen"] | None = None


class TeamInviteRequest(BaseModel):
    role: Literal["admin", "editor", "viewer"] = "viewer"
    expires_days: int | None = Field(default=7, ge=1, le=3650)


class TeamJoinRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class TeamJoinApplyRequest(BaseModel):
    message: str = Field(default="", max_length=500)


class TeamJoinRequestReview(BaseModel):
    decision: Literal["approved", "rejected"]
    role: Literal["admin", "editor", "viewer"] = "viewer"
    note: str = Field(default="", max_length=500)


class TeamMemberRoleRequest(BaseModel):
    role: Literal["owner", "admin", "editor", "viewer"]
    status: Literal["active", "disabled"] = "active"


class TeamMaterialUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = Field(default=None, max_length=20)
    note: str = Field(default="", max_length=300)


class TeamMaterialCommentResolveRequest(BaseModel):
    resolved: bool


class TeamMaterialTagRequest(BaseModel):
    material_ids: list[int] = Field(min_length=1, max_length=100)
    tags: list[str] = Field(min_length=1, max_length=20)


class TeamMaterialTransferRequest(BaseModel):
    target_user_id: int | None = Field(default=None, gt=0)


class TeamLibraryMemberRequest(BaseModel):
    access: Literal["read", "write"] = "read"


class TeamLibraryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="通用", max_length=80)
    visibility: Literal["team", "private", "public_internal"] = "team"
    permission_mode: Literal["team_editors", "admins_only", "custom"] = "team_editors"


class TeamLibraryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=80)
    visibility: Literal["team", "private", "public_internal"] | None = None
    permission_mode: Literal["team_editors", "admins_only", "custom"] | None = None


class TeamMaterialRequest(BaseModel):
    lib_id: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list, max_length=20)
    kind: str = Field(default="Markdown", max_length=40)


class TeamPersonalMaterialImportRequest(BaseModel):
    material_id: int = Field(gt=0)
    lib_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)


class TeamMaterialCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=1000)


class TeamMaterialUrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    name: str = Field(min_length=1, max_length=200)
    lib_id: int | None = Field(default=None, gt=0)
    tags: list[str] = Field(default_factory=list, max_length=20)
    content: str | None = Field(default=None, min_length=1)


class TeamShareRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    lib_id: int | None = Field(default=None, gt=0)
    scope: Literal["team", "library", "tag"] = "team"
    expires_days: int | None = Field(default=30, ge=1, le=3650)
    password: str | None = Field(default=None, min_length=4, max_length=12)
    watermark: bool = True
    member_ids: list[int] = Field(default_factory=list, max_length=100)


class TeamEvolutionTaskRequest(BaseModel):
    lib_id: int | None = Field(default=None, gt=0)
    mode: Literal["auto", "manual"] = "manual"
    visibility: Literal["private", "team"] = "team"
    review_strategy: Literal["all_agree", "majority", "owner_final"] = "owner_final"
    summary: str = Field(default="", max_length=1000)



class TeamEvolutionTaskUpdateRequest(BaseModel):
    mode: Literal["auto", "manual"] | None = None
    visibility: Literal["private", "team"] | None = None
    review_strategy: Literal["all_agree", "majority", "owner_final"] | None = None
    summary: str | None = Field(default=None, max_length=1000)

class TeamEvolutionReviewRequest(BaseModel):
    decision: Literal["accepted", "rejected", "needs_changes"]
    feedback: str = Field(default="", max_length=1000)


class TeamQuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    lib_ids: list[int] = Field(default_factory=list, max_length=20)


class TeamGameScoreRequest(BaseModel):
    game: Literal["flashcard", "monopoly", "matching"] = "flashcard"
    score: int = Field(ge=0, le=1_000_000)
    correct: int = Field(ge=0, le=10000)
    total: int = Field(ge=1, le=10000)


class TeamActivityRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    activity_type: Literal["contest", "chapter", "battle"] = "contest"
    starts_at: str | None = None
    ends_at: str | None = None
    reward: str = Field(default="", max_length=200)


class TeamActivityUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["planned", "published", "running", "ended", "cancelled"] | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    reward: str | None = Field(default=None, max_length=200)


class TeamSettingsRequest(BaseModel):
    allow_editor_external_share: bool = False
    review_strategy: Literal["single", "all_agree", "majority", "owner_final"] = "owner_final"
    watermark_enabled: bool = True
    auto_evolution_enabled: bool = False
    auto_evolution_time: str = Field(default="02:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    daily_deepseek_quota: int = Field(default=1000, ge=0, le=1_000_000)
    storage_quota: int = Field(default=1073741824, ge=0)
    media_concurrency: int = Field(default=2, ge=1, le=50)
    evolution_concurrency: int = Field(default=1, ge=1, le=50)
    sandbox_concurrency: int = Field(default=1, ge=1, le=50)
    game_multiplayer_enabled: bool = True
    log_retention_days: int = Field(default=180, ge=7, le=3650)
    queue_prefix: str = Field(default="team", max_length=40)
