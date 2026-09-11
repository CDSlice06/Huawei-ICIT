# -*- coding: utf-8 -*-
"""演示账号手动重置脚本（tasks.md 9.2：python -m app.scripts.reset_demo）"""
import asyncio


async def main() -> None:
    from app.db import AsyncSessionLocal
    from app.services import demo_service

    async with AsyncSessionLocal() as db:
        stats = await demo_service.reset_demo_account(db)
        print(f"演示账号已重置: {stats}")


if __name__ == "__main__":
    asyncio.run(main())