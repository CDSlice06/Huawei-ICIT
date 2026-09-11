# -*- coding: utf-8 -*-
"""演示账号预置数据生成脚本（tasks.md 9.1 验收入口：python -m app.scripts.seed_demo）"""
import asyncio


async def main() -> None:
    from app.db import AsyncSessionLocal
    from app.services import demo_service

    async with AsyncSessionLocal() as db:
        stats = await demo_service.seed_demo_account(db)
        print(f"演示账号预置完成: {stats}")


if __name__ == "__main__":
    asyncio.run(main())