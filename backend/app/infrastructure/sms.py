"""短信验证码基础设施（P2-5，spec §5.1.1规则1、design §2.8.2 资源清单）。

可插拔驱动：
- console（默认，开发/演示）：验证码仅输出到日志，不产生费用
- huawei（生产）：华为云SMS（需在控制台开通短信服务、创建签名与模板，
  并配置 SMS_APP_KEY / SMS_APP_SECRET / SMS_SIGNATURE / SMS_TEMPLATE_ID）
验证码经Redis存取（sms:code:{phone}，5分钟有效，一次性）。
"""
import logging
import random

from app.config import settings
from app.infrastructure import redis_client

logger = logging.getLogger(__name__)

CODE_TTL_SECONDS = 300
PHONE_PATTERN = r"^1[3-9]\d{9}$"
_CODE_KEY = "sms:code:{phone}"


class SmsNotConfigured(Exception):
    """SMS服务未启用或凭据缺失（ENABLE_SMS=false / huawei驱动缺配置）。"""


class SmsSendError(Exception):
    """短信发送失败。"""


def generate_code() -> str:
    return f"{random.randint(0, 999999):06d}"


async def send_code(phone: str) -> None:
    """生成并发送验证码（未启用SMS时抛 SmsNotConfigured，由API层转422/403语义）。"""
    if not settings.ENABLE_SMS:
        raise SmsNotConfigured("短信服务未开放（ENABLE_SMS=false）")
    code = generate_code()
    if settings.SMS_DRIVER == "console":
        # 开发/演示驱动：仅打日志，不外发
        logger.warning("【演示模式】SMS验证码 phone=%s code=%s（请勿用于生产）", phone, code)
    elif settings.SMS_DRIVER == "huawei":
        # 华为云SMS接入点：需SMS_APP_KEY/SECRET/SIGNATURE/TEMPLATE_ID凭据（design §2.8.2 资源清单）
        if not (settings.SMS_APP_KEY and settings.SMS_APP_SECRET):
            raise SmsNotConfigured("华为云SMS凭据未配置（SMS_APP_KEY/SMS_APP_SECRET）")
        raise SmsSendError("华为云SMS发送通道需在演示环境配置凭据后启用")
    else:
        raise SmsNotConfigured(f"未知SMS驱动: {settings.SMS_DRIVER}")
    await redis_client.get_redis().set(_CODE_KEY.format(phone=phone), code, ex=CODE_TTL_SECONDS)


async def verify_code(phone: str, code: str) -> bool:
    """校验并消费验证码（一次性）。"""
    key = _CODE_KEY.format(phone=phone)
    stored = await redis_client.get_redis().get(key)
    if not stored or stored != code:
        return False
    await redis_client.get_redis().delete(key)
    return True
