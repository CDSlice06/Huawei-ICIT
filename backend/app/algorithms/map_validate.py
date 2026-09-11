"""导图结构校验纯函数（tasks.md 7.1，design.md §2.1.3.3、spec §6.4）。"""
from typing import Any


def validate_map_tree(
    data: dict, valid_card_ids: set[str]
) -> list[dict]:
    """校验MaaS返回的导图层级JSON（后端权威校验）。

    校验项（design.md §2.1.3.3）：
    1. 根节点唯一（root 必须存在且为单对象）
    2. 无环（树结构本身天然无环；此处校验 card_id 引用合法性 + 深度限制防异常嵌套）
    3. 叶子节点 card_id 指向库内有效卡片
    4. 非叶子节点不挂 card_id
    返回：拍平的节点列表 [{title, parent_key, card_id}]（parent_key=None 为根）。
    校验失败抛 MapValidationError。
    """
    root = data.get("root")
    if not isinstance(root, dict) or not root.get("title"):
        raise MapValidationError("根节点缺失或非法")

    nodes: list[dict] = []
    MAX_DEPTH = 6
    MAX_NODES = 300

    def walk(node: dict, parent_key: str | None, depth: int) -> None:
        if len(nodes) > MAX_NODES:
            raise MapValidationError("导图节点数超出上限")
        if depth > MAX_DEPTH:
            raise MapValidationError("导图层级过深")

        title = (node.get("title") or "").strip()
        if not title or len(title) > 50:
            raise MapValidationError(f"节点标题缺失或超过50字符: {title[:20]}")

        card_id = node.get("card_id")
        children = node.get("children") or []
        key = f"n{len(nodes)}"

        if children:
            # 非叶子节点不挂卡片（spec §6.4规则5）
            if card_id:
                raise MapValidationError(f"非叶子节点不应关联卡片: {title[:20]}")
        else:
            # 叶子节点 card_id 可选，但必须合法（spec §6.4规则5）
            if card_id and card_id not in valid_card_ids:
                raise MapValidationError(f"叶子节点引用了库外卡片: {title[:20]}")

        nodes.append({"title": title, "parent_key": parent_key, "card_id": card_id, "key": key})
        for child in children:
            if not isinstance(child, dict):
                raise MapValidationError("子节点格式非法")
            walk(child, key, depth + 1)

    walk(root, None, 1)
    return nodes


def detect_cycle(edges: dict[str, str], node_id: str, new_parent_id: str) -> bool:
    """环检测：将 node_id 挂到 new_parent_id 下是否形成环（后端DFS权威校验）。

    规则（design.md §2.1.3.3）：若 new_parent_id 在 node_id 的现有后代中，则成环。
    edges: {node_id: parent_id}
    """
    # 收集 node_id 的全部后代
    children_map: dict[str, list[str]] = {}
    for child, parent in edges.items():
        children_map.setdefault(parent, []).append(child)

    stack = [node_id]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current == new_parent_id:
            return True  # 新父节点在node子树中 → 成环
        if current in seen:
            continue
        seen.add(current)
        stack.extend(children_map.get(current, []))
    return False


class MapValidationError(Exception):
    """导图结构校验失败。"""