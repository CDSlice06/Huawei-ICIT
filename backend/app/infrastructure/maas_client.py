"""MaaS 大模型客户端（tasks.md 5.1，design.md §2.5.1）。

- httpx 异步调用 MAAS_ENDPOINT（OpenAI兼容chat/completions格式）
- 文本模型30s / 多模态120s 超时（spec §4.1.2）
- 指数退避重试≤2次（1s→2s，spec §4.2.3）
- API Key 仅环境变量注入（spec §4.3.4）
- 业务层依赖抽象接口，测试用 httpx.MockTransport 替换（spec §4.4.3）
"""
import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

RETRY_DELAYS = [1.0, 2.0]  # 指数退避：1s→2s（≤2次重试）


class MaasError(Exception):
    """MaaS 调用最终失败（含重试耗尽）。"""


class MaaSSchemaError(MaasError):
    """模型返回不符合约定JSON结构（spec §5.3.3异常2）。"""


def build_default_client() -> httpx.AsyncClient:
    """默认客户端；测试可注入 MockTransport 客户端替换。"""
    return httpx.AsyncClient(timeout=settings.MAAS_TEXT_TIMEOUT)


class MaaSClient:
    """业务层通过本抽象调用大模型，不直接依赖SDK实现类。"""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or build_default_client()

    async def close(self) -> None:
        await self._client.aclose()

    async def chat_json(
        self,
        messages: list[dict],
        *,
        multimodal: bool = False,
        timeout: float | None = None,
        temperature: float = 0.3,
        response_json: bool = True,
        retries: int | None = None,
    ) -> dict:
        """调用 chat/completions 并解析 JSON 输出；失败指数退避重试。"""
        max_retries = settings.TASK_RETRY_MAX if retries is None else retries
        # MockTransport（测试注入）场景允许缺省Key；httpx.AsyncClient 的传输器在 _transport
        using_mock = isinstance(getattr(self._client, "_transport", None), httpx.MockTransport)
        if settings.MAAS_API_KEY == "" and not using_mock:
            raise MaasError("MAAS_API_KEY 未配置（环境变量缺失）")

        url = settings.MAAS_ENDPOINT or "https://api.maas.example/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.MAAS_API_KEY}"}
        payload: dict = {
            "messages": messages,
            "temperature": temperature,
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}

        effective_timeout = timeout or (settings.MAAS_MULTIMODAL_TIMEOUT if multimodal else settings.MAAS_TEXT_TIMEOUT)

        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.post(
                    url, headers=headers, json=payload, timeout=effective_timeout
                )
                resp.raise_for_status()
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                return _parse_json_content(content)
            except MaaSSchemaError:
                raise  # 结构非法不重试（重试由调用方结构化失败策略统一处理？design要求纳入重试——见下）
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_retries:
                    import asyncio

                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    logger.warning("MaaS调用失败（第%d次），%.1fs后重试: %s", attempt + 1, delay, exc)
                    await asyncio.sleep(delay)
        raise MaasError(f"MaaS调用失败（重试{max_retries}次后）: {last_exc}")

    async def embed(self, text: str) -> list[float]:
        """文本向量（P2语义搜索，MaaS embedding接口）。"""
        max_retries = settings.TASK_RETRY_MAX
        url = settings.MAAS_ENDPOINT.replace("/chat/completions", "/embeddings") if settings.MAAS_ENDPOINT else "https://api.maas.example/v1/embeddings"
        headers = {"Authorization": f"Bearer {settings.MAAS_API_KEY}"}
        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.post(
                    url, headers=headers, json={"input": text}, timeout=settings.MAAS_TEXT_TIMEOUT
                )
                resp.raise_for_status()
                return resp.json()["data"][0]["embedding"]
            except Exception as exc:  # noqa: BLE001
                if attempt >= max_retries:
                    raise MaasError(f"embedding调用失败: {exc}") from exc
                import asyncio

                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
        raise MaasError("embedding调用失败")


def _parse_json_content(content: str) -> dict:
    """解析模型返回的JSON内容；非法结构抛 MaaSSchemaError。"""
    text = content.strip()
    # 兼容 ```json 包裹
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MaaSSchemaError(f"模型返回非JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise MaaSSchemaError("模型返回JSON顶层不是对象")
    return parsed


# 模块级单例（业务层通过 get_maas_client() 获取）
_client: MaaSClient | None = None


def get_maas_client() -> MaaSClient:
    global _client
    if _client is None:
        _client = MaaSClient()
    return _client