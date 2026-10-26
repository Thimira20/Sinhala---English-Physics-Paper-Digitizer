"""
Pydantic data models for configuration, projects, pages, diagrams, and OCR results.
"""
from datetime import datetime
from typing import Literal, Optional, Dict, List, Any
from pydantic import BaseModel, Field

# --- Settings ---

class TokenPricing(BaseModel):
    input: float
    output: float

class Settings(BaseModel):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_draft_model: str = "gemini-3.5-flash-lite"
    thinking_budget: int = 0
    requests_per_minute: int = 60
    max_concurrent_jobs: int = 4
    pricing_usd_per_million_tokens: Dict[str, TokenPricing] = Field(default_factory=lambda: {
        "gemini-3.5-flash": TokenPricing(input=0.30, output=2.50),
        "gemini-3.5-flash-lite": TokenPricing(input=0.15, output=1.25),
        "gemini-3.8-flash": TokenPricing(input=0.30, output=2.50),
        "gemini-3.1-pro-preview": TokenPricing(input=1.25, output=10.0),
        "gemini-2.5-pro": TokenPricing(input=1.25, output=10.0),
        "gemini-2.5-flash": TokenPricing(input=0.30, output=2.50)
    })
    monthly_budget_warning_usd: float = 10.0
    send_max_long_edge_px: int = 2400
    send_jpeg_quality: int = 90
    default_top_crop_percent: float = 0.0
    default_bottom_crop_percent: float = 6.5
    auto_deskew: bool = False
    sinhala_font: str = "Noto Sans Sinhala"
    sinhala_fallback_font: str = "Iskoola Pota"
    latin_font: str = "Noto Sans"
    body_font_size_pt: float = 11.0
    line_spacing: float = 1.15
    embed_fonts_in_docx: bool = True
    sinhala_math_mode: Literal["omml", "outside"] = "omml"
    mcq_default_layout: str = "as_original"
    diagram_clean_mode: Literal["normalize", "binary", "original"] = "normalize"
    pdf_engine_order: List[str] = Field(default_factory=lambda: ["word", "libreoffice", "browser"])
    branding_blacklist: List[str] = Field(default_factory=lambda: ["Samitha Ratnayake", "Innovative Physics"])
    scrub_phone_numbers: bool = True
    scrub_urls_emails: bool = True
    server_port: int = 8000

    def masked_copy(self) -> "Settings":
        data = self.model_dump()
        raw_key = self.gemini_api_key
        if raw_key and len(raw_key) > 8:
            data["gemini_api_key"] = f"{raw_key[:4]}...{raw_key[-4:]}"
        elif raw_key:
            data["gemini_api_key"] = "********"
        return Settings.model_validate(data)

# --- Diagrams & Crop ---

class PageCrop(BaseModel):
    top_pct: float = 0.0
    bottom_pct: float = 6.5
    override: bool = False

class Diagram(BaseModel):
    id: str
    box_px: List[int] = Field(description="[ymin, xmin, ymax, xmax] relative to work.png")
    label: str = ""
    mode: Literal["normalize", "binary", "original"] = "normalize"
    file: str = Field(description="Relative path inside project folder")
    raw_file: Optional[str] = None
    replaced: bool = False
    width_pct: int = 45
    version: int = 0

class EraseRegion(BaseModel):
    id: str
    box_px: List[int] = Field(description="[ymin, xmin, ymax, xmax] relative to work.png")

# --- Page & Project ---

class PageTokens(BaseModel):
    input: int = 0
    output: int = 0
    thinking: int = 0

class Page(BaseModel):
    index: int
    source_file: str
    work_file: str
    thumb_file: str
    width: int = 0
    height: int = 0
    crop: PageCrop = Field(default_factory=PageCrop)
    deskew: bool = False
    status: Literal["pending", "queued", "processing", "done", "error"] = "pending"
    error: Optional[str] = None
    model_used: str = "gemini-2.5-pro"
    cache_key: Optional[str] = None
    markdown: str = ""
    user_edited: bool = False
    ocr_markdown_pending: Optional[str] = None
    ocr_at: Optional[str] = None
    diagrams: List[Diagram] = Field(default_factory=list)
    erase_regions: List[EraseRegion] = Field(default_factory=list)
    include_in_export: bool = True
    page_break_after: bool = True
    uncertain_count: int = 0
    tokens: PageTokens = Field(default_factory=PageTokens)
    cost_usd: float = 0.0

class Project(BaseModel):
    schema_version: int = 1
    id: str
    name: str
    created_at: str
    updated_at: str
    page_order: List[int] = Field(default_factory=list)
    pages: Dict[str, Page] = Field(default_factory=dict)

# --- Gemini OCR Raw Schema ---

class GeminiDiagram(BaseModel):
    id: str
    box_2d: List[int] = Field(description="[ymin, xmin, ymax, xmax] normalized 0..1000")
    label: str

class GeminiPageResult(BaseModel):
    markdown: str
    diagrams: List[GeminiDiagram] = Field(default_factory=list)
