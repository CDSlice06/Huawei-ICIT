"""间隔复习算法（tasks.md 8.1，design.md §2.1.3.2，spec §5.6.1规则2）。

间隔集 [1,2,4,7,15,30]（design.md §2.11.4-③ 配置常量，不做SM-2）：
- 记住（remember）→ 间隔升一档（第6档保持30天）
- 模糊（blur）→ 间隔保持当前档
- 忘记（forget）→ 间隔重置1天，复习次数归零
纯函数无副作用。
"""

INTERVALS: list[int] = [1, 2, 4, 7, 15, 30]


def next_review(
    current_interval_days: int, review_count: int, rating: str
) -> tuple[int, int]:
    """计算下次复习间隔与复习次数。

    输入：当前间隔天数、当前累计复习次数、自评（forget/blur/remember）
    输出：（下次间隔天数、下次复习次数）
    """
    if rating not in ("forget", "blur", "remember"):
        raise ValueError(f"非法自评值: {rating}")

    if rating == "forget":
        return 1, 0

    current_idx = _interval_index(current_interval_days)
    if rating == "blur":
        return INTERVALS[current_idx], review_count + 1

    # remember：升一档，最高档保持30天
    next_idx = min(current_idx + 1, len(INTERVALS) - 1)
    return INTERVALS[next_idx], review_count + 1


def first_interval() -> int:
    """首次排定间隔（卡片创建即排定，spec §5.6.1规则1）。"""
    return INTERVALS[0]


def _interval_index(interval_days: int) -> int:
    """定位当前间隔在间隔集中的档位（容错：非标准间隔归入最近档）。"""
    try:
        return INTERVALS.index(interval_days)
    except ValueError:
        for i, v in enumerate(INTERVALS):
            if interval_days < v:
                return max(i - 1, 0)
        return len(INTERVALS) - 1