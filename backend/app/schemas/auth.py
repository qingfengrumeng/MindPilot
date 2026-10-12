import re
from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.base import CamelModel


class RegisterIn(CamelModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=1024)
    research_field: str = Field(default="", max_length=160)
    default_domain: str = Field(default="personal_learning", max_length=80)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[\w-]{3,64}", value, re.UNICODE):
            raise ValueError("用户名只能包含字母、数字、汉字、下划线和连字符")
        return value


class LoginIn(CamelModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = True


class ProfileIn(CamelModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    avatar: str | None = Field(default=None, max_length=180_000)
    research_field: str | None = Field(default=None, max_length=160)
    default_domain: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=2000)

    @field_validator("avatar")
    @classmethod
    def valid_avatar(cls, value):
        if value and not re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}", value):
            raise ValueError("头像须为 PNG、JPEG 或 WebP 图片")
        return value

    @field_validator("display_name")
    @classmethod
    def valid_display_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("名称不能为空")
        return value.strip() if value else value


class PasswordChangeIn(CamelModel):
    current_password: str
    next_password: str = Field(min_length=8, max_length=1024)


class UserOut(CamelModel):
    id: str
    username: str
    display_name: str
    avatar: str = ""
    research_field: str
    default_domain: str
    bio: str
    created_at: datetime

    @classmethod
    def from_user(cls, user):
        return cls.model_validate({
            "id": user.id,
            "username": user.username,
            "displayName": user.display_name,
            "avatar": user.avatar,
            "researchField": user.research_field,
            "defaultDomain": user.default_domain,
            "bio": user.bio,
            "createdAt": user.created_at,
        })


class SessionOut(CamelModel):
    id: str
    created_at: datetime
    expires_at: datetime
    current: bool
