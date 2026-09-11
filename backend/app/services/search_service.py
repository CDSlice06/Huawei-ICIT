"""知识搜索服务（P1-4，spec §5.4.1规则4、§4.1.4；design §2.4.9）。

三类对象（卡片/素材/错题）全局与库内搜索，相关性排序：
- MySQL：FULLTEXT ngram MATCH...AGAINST（自然语言模式），标题命中加权（标题>标签>要点>正文由
  索引列权重近似：标题单独MATCH加权2）
- 其他方言（SQLite兼容层/本地演示）：LIKE 降级路径（业务测试与本地演示可用）
返回分组结果与片段（snippet），前端负责关键词高亮。
"""
import logging

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

KEYWORD_MAX_CHARS = 100
LIMIT_PER_TYPE = 20
SNIPPET_RADIUS = 60

_CARD_LIKE = """
    SELECT id, kb_id, title, summary, tags, created_at,
           CASE WHEN title LIKE :pat ESCAPE '\\' THEN 2 ELSE 0 END AS rel
    FROM t_knowledge_card
    WHERE user_id = :uid AND (title LIKE :pat ESCAPE '\\' OR summary LIKE :pat ESCAPE '\\'
          OR key_points_text LIKE :pat ESCAPE '\\' OR tags_text LIKE :pat ESCAPE '\\')
    ORDER BY rel DESC, created_at DESC
    LIMIT :lim
"""

_CARD_FTS = """
    SELECT id, kb_id, title, summary, tags, created_at,
           (MATCH(title, summary, tags_text, key_points_text) AGAINST (:kw IN NATURAL LANGUAGE MODE)
            + CASE WHEN MATCH(title) AGAINST (:kw IN NATURAL LANGUAGE MODE) > 0 THEN 2 ELSE 0 END
           ) AS rel
    FROM t_knowledge_card
    WHERE user_id = :uid
      AND MATCH(title, summary, tags_text, key_points_text) AGAINST (:kw IN NATURAL LANGUAGE MODE)
    ORDER BY rel DESC, created_at DESC
    LIMIT :lim
"""

_ASSET_LIKE = """
    SELECT id, kb_id, type, raw_content, extracted_text, created_at
    FROM t_knowledge_asset
    WHERE user_id = :uid AND (extracted_text LIKE :pat ESCAPE '\\' OR raw_content LIKE :pat ESCAPE '\\')
    ORDER BY created_at DESC
    LIMIT :lim
"""

_ASSET_FTS = """
    SELECT id, kb_id, type, raw_content, extracted_text, created_at,
           MATCH(extracted_text) AGAINST (:kw IN NATURAL LANGUAGE MODE) AS rel
    FROM t_knowledge_asset
    WHERE user_id = :uid AND MATCH(extracted_text) AGAINST (:kw IN NATURAL LANGUAGE MODE)
    ORDER BY rel DESC, created_at DESC
    LIMIT :lim
"""

_MISTAKE_LIKE = """
    SELECT id, kb_id, question, answer, error_analysis, tags, mastery, created_at,
           CASE WHEN question LIKE :pat ESCAPE '\\' THEN 2 ELSE 0 END AS rel
    FROM t_mistake_entry
    WHERE user_id = :uid AND parse_status = 'done'
      AND (question LIKE :pat ESCAPE '\\' OR answer LIKE :pat ESCAPE '\\'
           OR error_analysis LIKE :pat ESCAPE '\\' OR tags_text LIKE :pat ESCAPE '\\')
    ORDER BY rel DESC, created_at DESC
    LIMIT :lim
"""

_MISTAKE_FTS = """
    SELECT id, kb_id, question, answer, error_analysis, tags, mastery, created_at,
           (MATCH(question, answer, error_analysis, tags_text) AGAINST (:kw IN NATURAL LANGUAGE MODE)
            + CASE WHEN MATCH(question) AGAINST (:kw IN NATURAL LANGUAGE MODE) > 0 THEN 2 ELSE 0 END
           ) AS rel
    FROM t_mistake_entry
    WHERE user_id = :uid AND parse_status = 'done'
      AND MATCH(question, answer, error_analysis, tags_text) AGAINST (:kw IN NATURAL LANGUAGE MODE)
    ORDER BY rel DESC, created_at DESC
    LIMIT :lim
"""


class SearchValidationError(Exception):
    pass


def _parse_tags(value) -> list:
    """原生SQL查询返回的JSON列在两种方言下都是字符串，统一解析。"""
    import json

    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except ValueError:
            return []
    return []


def _like_pattern(keyword: str) -> str:
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _snippet(text: str | None, keyword: str, radius: int = SNIPPET_RADIUS) -> str:
    """围绕关键词截取片段（大小写不敏感定位，前端做高亮）。"""
    if not text:
        return ""
    lower_text, lower_kw = text.lower(), keyword.lower()
    pos = lower_text.find(lower_kw)
    if pos < 0:
        return text[: radius * 2] + ("…" if len(text) > radius * 2 else "")
    start = max(0, pos - radius)
    end = min(len(text), pos + len(keyword) + radius)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


async def search_all(
    db: AsyncSession, user_id: str, keyword: str, kb_id: str | None = None, kind: str = "all"
) -> dict:
    """执行三类搜索（kb_id 限定库内范围；kind 限定对象类型）。"""
    kw = (keyword or "").strip()
    if not kw:
        raise SearchValidationError("搜索关键词不能为空")
    if len(kw) > KEYWORD_MAX_CHARS:
        raise SearchValidationError(f"关键词超过{KEYWORD_MAX_CHARS}字符")
    if kind not in ("all", "card", "asset", "mistake"):
        raise SearchValidationError("type 取值非法")

    dialect = db.bind.dialect.name if db.bind is not None else "mysql"
    use_fts = dialect == "mysql"
    if use_fts and len(kw) < 2:
        # ngram_token_size=2 下单字无token，退化为LIKE保证可用性
        use_fts = False

    result: dict = {"keyword": kw, "cards": [], "assets": [], "mistakes": [], "counts": {}}

    if kind in ("all", "card"):
        sql = sa_text(_CARD_FTS if use_fts else _CARD_LIKE)
        params: dict = {"uid": user_id, "lim": LIMIT_PER_TYPE}
        if use_fts:
            params["kw"] = kw
        else:
            params["pat"] = _like_pattern(kw)
        if kb_id:
            sql = sa_text(((_CARD_FTS if use_fts else _CARD_LIKE)).replace(
                "WHERE user_id = :uid", "WHERE user_id = :uid AND kb_id = :kbid"
            ))
            params["kbid"] = kb_id
        rows = (await db.execute(sql, params)).all()
        result["cards"] = [
            {
                "id": str(r.id),
                "kb_id": str(r.kb_id) if r.kb_id else None,
                "title": r.title,
                "snippet": _snippet(r.summary, kw),
                "tags": _parse_tags(r.tags),
                "relevance": float(r.rel or 0),
            }
            for r in rows
        ]

    if kind in ("all", "asset"):
        sql = sa_text(_ASSET_FTS if use_fts else _ASSET_LIKE)
        params = {"uid": user_id, "lim": LIMIT_PER_TYPE}
        if use_fts:
            params["kw"] = kw
        else:
            params["pat"] = _like_pattern(kw)
        rows = (await db.execute(sql, params)).all()
        result["assets"] = [
            {
                "id": str(r.id),
                "kb_id": str(r.kb_id) if r.kb_id else None,
                "asset_type": r.type,
                "snippet": _snippet(r.extracted_text or r.raw_content or "", kw),
                "relevance": float(getattr(r, "rel", 0) or 0),
            }
            for r in rows
        ]

    if kind in ("all", "mistake"):
        sql = sa_text(_MISTAKE_FTS if use_fts else _MISTAKE_LIKE)
        params = {"uid": user_id, "lim": LIMIT_PER_TYPE}
        if use_fts:
            params["kw"] = kw
        else:
            params["pat"] = _like_pattern(kw)
        rows = (await db.execute(sql, params)).all()
        result["mistakes"] = [
            {
                "id": str(r.id),
                "kb_id": str(r.kb_id) if r.kb_id else None,
                "question": r.question,
                "snippet": _snippet(r.error_analysis or r.answer, kw),
                "mastery": r.mastery,
                "tags": _parse_tags(r.tags),
                "relevance": float(r.rel or 0),
            }
            for r in rows
        ]

    result["counts"] = {
        "cards": len(result["cards"]),
        "assets": len(result["assets"]),
        "mistakes": len(result["mistakes"]),
    }
    return result


async def aggregate_tags(db: AsyncSession, user_id: str, limit: int = 50) -> list[dict]:
    """用户卡片标签聚合（GET /api/tags，P1-5，spec §5.4.1规则6）。

    Python侧聚合（演示体量≤1000卡/库可接受，避免MySQL JSON_TABLE方言绑定）。
    """
    from app.models import KnowledgeCard

    rows = (await db.execute(
        sa_text("SELECT tags FROM t_knowledge_card WHERE user_id = :uid"),
        {"uid": user_id},
    )).all()
    counts: dict[str, int] = {}
    for (tags,) in rows:
        if isinstance(tags, str):
            import json

            try:
                tags = json.loads(tags)
            except ValueError:
                tags = []
        for tag in tags or []:
            counts[tag] = counts.get(tag, 0) + 1
    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:limit]
    return [{"tag": t, "count": c} for t, c in ordered]


# ---------------- 语义搜索（P2-3，spec §5.4.1规则5） ----------------


def _cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（内存比对，单用户万级以内可接受）。"""
    import math

    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def semantic_search(db: AsyncSession, user_id: str, keyword: str, limit: int = 10) -> dict:
    """语义搜索：查询文本向量化后与卡片向量内存余弦比对，返回最相近卡片。"""
    from app.infrastructure.maas_client import MaasError, get_maas_client
    from app.models import KnowledgeCard

    kw = (keyword or "").strip()
    if not kw:
        raise SearchValidationError("搜索关键词不能为空")
    if len(kw) > KEYWORD_MAX_CHARS:
        raise SearchValidationError(f"关键词超过{KEYWORD_MAX_CHARS}字符")

    try:
        client = get_maas_client()
        query_vec = await client.embed(kw)
    except MaasError as exc:
        raise SearchValidationError(f"语义搜索需要MaaS embedding支持：{exc}") from exc

    rows = (
        await db.execute(
            sa_text(
                "SELECT id, kb_id, title, summary, tags, embedding FROM t_knowledge_card "
                "WHERE user_id = :uid AND embedding IS NOT NULL"
            ),
            {"uid": user_id},
        )
    ).all()

    scored = []
    for r in rows:
        vec = _parse_tags(r.embedding)  # JSON数组同样以字符串形式返回
        if not vec:
            continue
        scored.append((float(_cosine(query_vec, vec)), r))
    scored.sort(key=lambda x: -x[0])

    items = [
        {
            "id": str(r.id),
            "kb_id": str(r.kb_id) if r.kb_id else None,
            "title": r.title,
            "snippet": _snippet(r.summary, kw) if kw.lower() in (r.summary or "").lower() else r.summary,
            "tags": _parse_tags(r.tags),
            "similarity": round(score, 4),
        }
        for score, r in scored[:limit]
        if score > 0.0
    ]
    return {"keyword": kw, "items": items, "total": len(items), "vectorized_cards": len(scored)}
