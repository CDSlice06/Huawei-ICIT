# -*- coding: utf-8 -*-
"""结构化输出校验测试（tasks.md 5.2：不落库残缺卡片，spec §5.3.3异常2、§6.3约束）。"""
import pytest

from app.services.card_service import StructuredSchemaError, _validate_card_schema


def make_valid_data():
    return {
        "title": "测试卡片标题",
        "summary": "这是一份摘要内容。",
        "key_points": ["要点一", "要点二", "要点三"],
        "qa_pairs": [{"question": "问题？", "answer": "答案"}],
        "tags": ["标签1"],
    }


def test_valid_schema_passes():
    data = _validate_card_schema(make_valid_data())
    assert data["title"] == "测试卡片标题"
    assert len(data["key_points"]) == 3


def test_missing_title_rejected():
    data = make_valid_data()
    data["title"] = ""
    with pytest.raises(StructuredSchemaError):
        _validate_card_schema(data)


def test_missing_qa_rejected():
    data = make_valid_data()
    data["qa_pairs"] = []
    with pytest.raises(StructuredSchemaError):
        _validate_card_schema(data)


def test_too_few_key_points_rejected():
    data = make_valid_data()
    data["key_points"] = ["只有一条"]
    with pytest.raises(StructuredSchemaError):
        _validate_card_schema(data)


def test_title_over_100_rejected():
    data = make_valid_data()
    data["title"] = "长" * 101
    with pytest.raises(StructuredSchemaError):
        _validate_card_schema(data)


def test_tags_empty_allowed():
    """标签可空（v1.1矛盾修复：四必填字段+标签可空）。"""
    data = make_valid_data()
    data["tags"] = []
    assert _validate_card_schema(data)["tags"] == []