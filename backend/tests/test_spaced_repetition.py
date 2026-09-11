# -*- coding: utf-8 -*-
"""间隔复习算法全表测试（tasks.md 8.1 验收：design §2.1.3.2 全部6档×3自评组合）。"""
import pytest

from app.algorithms.spaced_repetition import INTERVALS, next_review


@pytest.mark.parametrize(
    "current,count,rating,expected",
    [
        # 第1档（间隔1天）
        (1, 0, "remember", (2, 1)),
        (1, 0, "blur", (1, 1)),
        (1, 0, "forget", (1, 0)),
        # 第2档
        (2, 1, "remember", (4, 2)),
        (2, 1, "blur", (2, 2)),
        (2, 1, "forget", (1, 0)),
        # 第3档
        (4, 2, "remember", (7, 3)),
        (4, 2, "blur", (4, 3)),
        (4, 2, "forget", (1, 0)),
        # 第4档
        (7, 3, "remember", (15, 4)),
        (7, 3, "blur", (7, 4)),
        (7, 3, "forget", (1, 0)),
        # 第5档
        (15, 4, "remember", (30, 5)),
        (15, 4, "blur", (15, 5)),
        (15, 4, "forget", (1, 0)),
        # 第6档（保持30）
        (30, 5, "remember", (30, 6)),
        (30, 5, "blur", (30, 6)),
        (30, 5, "forget", (1, 0)),
    ],
)
def test_next_review_full_table(current, count, rating, expected):
    assert next_review(current, count, rating) == expected


def test_intervals_constant():
    assert INTERVALS == [1, 2, 4, 7, 15, 30]


@pytest.mark.parametrize("bad", ["", "ok", "mastered", None])
def test_invalid_rating_raises(bad):
    with pytest.raises(ValueError):
        next_review(1, 0, bad)