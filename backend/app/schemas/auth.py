"""认证相关 Pydantic 模型（tasks.md 3.1/3.2，spec §5.1.1）。"""
from pydantic import BaseModel, EmailStr, Field, field_validator

PASSWORD_PATTERN = r"^(?=.*[A-Za-z])(?=.*\d)\S{8,32}$"
PHONE_PATTERN = r"^1[3-9]\d{9}$"


class RegisterRequest(BaseModel):
    email: EmailStr = Field(description="邮箱")
    password: str = Field(description="密码，8~32位且同时包含字母与数字")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        import re

        if not re.fullmatch(PASSWORD_PATTERN, v):
            raise ValueError("密码须为8~32位且同时包含字母与数字")
        return v


class LoginRequest(BaseModel):
    email: EmailStr = Field(description="邮箱")
    password: str = Field(description="密码")


class UserBrief(BaseModel):
    id: str
    email: str


class AuthResponse(BaseModel):
    token: str
    user: UserBrief

class SmsCodeRequest(BaseModel):
    phone: str = Field(description="手机号（中国大陆11位）")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        import re

        if not re.fullmatch(PHONE_PATTERN, v):
            raise ValueError("手机号格式不正确")
        return v


class PhoneRegisterRequest(SmsCodeRequest):
    code: str = Field(min_length=6, max_length=6, description="短信验证码")
    password: str = Field(description="密码，8~32位且同时包含字母与数字")

    @field_validator("password")
    @classmethod
    def validate_password2(cls, v: str) -> str:
        import re

        if not re.fullmatch(PASSWORD_PATTERN, v):
            raise ValueError("密码须为8~32位且同时包含字母与数字")
        return v
