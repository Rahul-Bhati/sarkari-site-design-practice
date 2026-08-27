from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.entry import Category

INDIAN_PHONE = r"^\+91[6-9]\d{9}$"


class Channel(str, Enum):
    email = "email"
    whatsapp = "whatsapp"
    both = "both"


class Frequency(str, Enum):
    instant = "instant"
    daily = "daily"
    weekly = "weekly"


class Plan(str, Enum):
    free = "free"
    pro = "pro"
    thekedar = "thekedar"


class SubscribeRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, pattern=INDIAN_PHONE)
    channel: Channel = Channel.email
    frequency: Frequency = Frequency.weekly
    categories: list[Category] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("states")
    @classmethod
    def _upper_states(cls, v: list[str]) -> list[str]:
        for s in v:
            if not (2 <= len(s) <= 4 and s.isalpha()):
                raise ValueError(f"invalid state code: {s}")
        return [s.upper() for s in v]

    @model_validator(mode="after")
    def _needs_a_channel(self) -> "SubscribeRequest":
        if not self.email and not self.phone:
            raise ValueError("email or phone is required")
        if self.channel in (Channel.whatsapp, Channel.both) and not self.phone:
            raise ValueError("phone is required for WhatsApp delivery")
        if self.channel in (Channel.email, Channel.both) and not self.email:
            raise ValueError("email is required for email delivery")
        return self


class SubscribeResponse(BaseModel):
    success: bool
    message: str
