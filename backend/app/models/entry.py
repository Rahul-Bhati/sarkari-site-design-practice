from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Category(str, Enum):
    yojana = "yojana"
    naukri = "naukri"
    tender = "tender"
    rule = "rule"
    auction = "auction"
    notice = "notice"


class Urgency(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Status(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


class SourceOut(BaseModel):
    id: int
    name: str
    url: str


class Entry(BaseModel):
    id: str
    source_id: Optional[int] = None
    source: Optional[SourceOut] = None

    title: str
    summary_en: str = ""
    summary_hi: Optional[str] = None

    category: Category
    state: str
    district: Optional[str] = None
    department: Optional[str] = None

    original_url: str
    pdf_url: Optional[str] = None

    deadline: Optional[date] = None
    published_date: Optional[date] = None

    budget_amount: Optional[int] = None  # paisa
    salary_range: Optional[dict[str, Any]] = None
    eligibility: Optional[dict[str, Any]] = None
    key_details: dict[str, Any] = Field(default_factory=dict)

    ai_confidence: float = 0
    urgency: Urgency = Urgency.low
    status: Status = Status.pending

    published_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class EntriesResponse(BaseModel):
    entries: list[Entry]
    total: int
    page: int
    limit: int
    has_more: bool


class StatsResponse(BaseModel):
    total_entries: int
    entries_today: int
    states_covered: int
    sources_active: int
    categories: dict[str, int]


# --- AI extraction schema -------------------------------------------------
# Passed to the Claude API as a structured-output schema, so the model returns
# JSON that already validates against this shape.


class KeyDetails(BaseModel):
    application_link: Optional[str] = None
    helpline: Optional[str] = None
    vacancies: Optional[int] = None
    emd_amount: Optional[int] = None  # INR
    post: Optional[str] = None
    pay: Optional[str] = None
    age: Optional[str] = None
    qualification: Optional[str] = None
    fee: Optional[str] = None
    benefit: Optional[str] = None
    how_to_apply: Optional[str] = None
    important_dates: Optional[str] = None


class Summary(BaseModel):
    title: str = Field(description="Clear, plain-language title, max 80 characters. No jargon.")
    summary_en: str = Field(
        description=(
            "2-3 sentence summary in simple English. What is this about? Who is it "
            "for? What should they do? Include the most important number (salary, "
            "budget, subsidy amount) if applicable."
        )
    )
    summary_hi: str = Field(
        description="Same summary in simple Hindi (Devanagari). Everyday Hindi, not Shudh Hindi."
    )
    category: Literal["yojana", "naukri", "tender", "rule", "auction", "notice"]
    urgency: Literal["low", "medium", "high", "critical"] = Field(
        description=(
            "critical = deadline within 7 days. high = deadline within 30 days or "
            "major policy change."
        )
    )
    deadline: Optional[str] = Field(
        default=None, description="ISO date (YYYY-MM-DD) or null."
    )
    department: Optional[str] = Field(default=None, description="Issuing department or ministry.")
    eligibility: Optional[str] = Field(default=None, description="Who is eligible? Brief text.")
    budget_or_salary: Optional[int] = Field(
        default=None, description="Key financial figure as an integer in INR (not paisa)."
    )
    confidence: float = Field(
        description=(
            "0.0-1.0. How confident are you that this summary is accurate and the "
            "source text was complete enough to summarise? Be strict: below 0.9 if "
            "the source text was truncated, ambiguous, or a bare corrigendum."
        )
    )
    key_details: KeyDetails = Field(default_factory=KeyDetails)


class SummaryBatch(BaseModel):
    """Several summaries from one call.

    Batching exists for a measured reason: on a single-entry call the JSON
    schema and system prompt are ~87% of the input, and both are byte-identical
    every time. Summarising N notices in one request pays that overhead once
    instead of N times, which roughly doubles how many entries a free daily
    token budget covers.

    `summaries` must come back in the same order as the notices were given, one
    per notice. The caller checks the count rather than trusting it.
    """

    summaries: list[Summary] = Field(
        description=(
            "One summary per numbered notice, in the same order they were "
            "given. Return exactly as many summaries as there were notices."
        )
    )
