"""认证相关 Pydantic 模型（tasks.md 3.1/3.2，spec §5.1.1）。"""
from pydantic import BaseModel, EmailStr, Field, field_validator

PASSWORD_PATTERN = r"^(?=.*[A-Za-z])(?=.*\d)\S{8,32}$"


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