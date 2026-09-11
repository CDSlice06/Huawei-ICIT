# -*- coding: utf-8 -*-
"""导图结构校验测试（tasks.md 7.1 验收：根唯一/环/card_id合法/非叶不挂卡）。"""
import pytest

from app.algorithms.map_validate import MapValidationError, detect_cycle, validate_map_tree


def test_valid_tree():
    data = {
        "root": {
            "title": "根",
            "children": [
                {"title": "叶1", "card_id": "11111111-1111-1111-1111-111111111111"},
                {"title": "子树", "children": [{"title": "叶2", "card_id": "22222222-2222-2222-2222-222222222222"}]},
            ],
        }
    }
    valid = {"11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"}
    nodes = validate_map_tree(data, valid)
    assert len(nodes) == 4
    assert nodes[0]["parent_key"] is None


def test_missing_root():
    with pytest.raises(MapValidationError):
        validate_map_tree({}, set())


def test_leaf_invalid_card_id():
    data = {"root": {"title": "根", "children": [{"title": "叶", "card_id": "not-exist"}]}}
    with pytest.raises(MapValidationError):
        validate_map_tree(data, set())


def test_internal_node_with_card_id_rejected():
    data = {
        "root": {
            "title": "根",
            "children": [
                {"title": "中间节点", "card_id": "22222222-2222-2222-2222-222222222222", "children": [{"title": "叶"}]}
            ],
        }
    }
    with pytest.raises(MapValidationError):
        validate_map_tree(data, {"22222222-2222-2222-2222-222222222222"})


def test_detect_cycle_blocks_reparent_to_descendant():
    # 树：a → b → c（a是根）。把 a 挂到 c 下应成环
    edges = {"b": "a", "c": "b"}
    assert detect_cycle(edges, "a", "c") is True
    # 把 a 挂到 b 下也成环（b是a后代）
    assert detect_cycle(edges, "a", "b") is True
    # 把 c 挂到 a 下不成环（移动到根下）
    assert detect_cycle(edges, "c", "a") is False


def test_detect_cycle_noop_same_parent():
    edges = {"b": "a"}
    assert detect_cycle(edges, "b", "a") is False