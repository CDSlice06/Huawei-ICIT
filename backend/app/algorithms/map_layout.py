"""导图默认布局算法（P2-1 快照坐标用，design §2.1.3.4）。

未执行过拖拽编排的导图没有持久化坐标，分享快照需包含"系统默认布局坐标"，
保证浏览端渲染与分享时刻一致（tech-review §一.7）。
采用与前端 compactBox 一致观的简化 LR 树布局：x=层级×层距，y=叶子序×行距，父节点纵向居中。
"""
from typing import Any


def default_layout(nodes: list[dict[str, Any]], *, x_gap: float = 240, y_gap: float = 56) -> dict[str, dict[str, float]]:
    """计算平铺节点列表的默认坐标，返回 {node_id: {"x": float, "y": float}}。

    nodes: [{id, parent_id, ...}]（parent_id 为字符串或 None；仅限合法树结构）
    """
    children: dict[str | None, list[str]] = {}
    for n in nodes:
        parent = n.get("parent_id")
        parent_key = str(parent) if parent else None
        children.setdefault(parent_key, []).append(str(n["id"]))
    roots = children.get(None, [])
    if len(roots) != 1:
        return {}  # 非法结构交由上层校验处理，这里不猜坐标

    coords: dict[str, dict[str, float]] = {}
    leaf_counter = {"i": 0}

    def place(nid: str, depth: int) -> float:
        kids = children.get(nid, [])
        x = 40 + depth * x_gap
        if not kids:
            y = 40 + leaf_counter["i"] * y_gap
            leaf_counter["i"] += 1
            coords[nid] = {"x": x, "y": y}
            return y
        ys = [place(k, depth + 1) for k in kids]
        y = sum(ys) / len(ys)
        coords[nid] = {"x": x, "y": y}
        return y

    place(roots[0], 0)
    return coords
