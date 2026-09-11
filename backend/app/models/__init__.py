"""models 包：SQLAlchemy ORM 模型（P0 八张核心表 + P1 错题本两表）。"""
from app.models.asset import KnowledgeAsset
from app.models.async_task import AsyncTask
from app.models.base import Base, UuidPkMixin, gen_uuid
from app.models.card import KnowledgeCard
from app.models.knowledge_base import KnowledgeBase
from app.models.mind_map import MapNode, MindMap
from app.models.mistake import MistakeEntry, MistakeQuizRecord
from app.models.p2 import MapPuzzleRecord, SharedKnowledgeBase
from app.models.review_statistics import ReviewStatistics
from app.models.review_task import ReviewTask
from app.models.user import User

__all__ = [
    "Base",
    "UuidPkMixin",
    "gen_uuid",
    "User",
    "KnowledgeBase",
    "KnowledgeAsset",
    "KnowledgeCard",
    "MindMap",
    "MapNode",
    "ReviewTask",
    "ReviewStatistics",
    "AsyncTask",
    "MistakeEntry",
    "MistakeQuizRecord",
    "SharedKnowledgeBase",
    "MapPuzzleRecord",
]
