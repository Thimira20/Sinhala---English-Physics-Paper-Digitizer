"""
Gemini OCR Engine: invokes Google Gemini Vision API via the official google-genai SDK,
handles SHA256 disk caching, JSON repairing for LaTeX backslashes, exponential backoff with jitter,
and token usage/cost calculation.
"""
import asyncio
import hashlib
import json
import logging
import random
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from google import genai
from google.genai import types

from core.models import GeminiPageResult, GeminiDiagram, Settings
from core.prompts import SYSTEM_PROMPT, PROMPT_VERSION, SCHEMA_VERSION

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "workspace" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

class OcrResult:
    def __init__(
        self,
        markdown: str,
        diagrams: List[GeminiDiagram],
        usage: Dict[str, int],
        cache_key: str,
        model_used: str,
        cost_usd: float,
        cached: bool = False
    ):
        self.markdown = markdown
        self.diagrams = diagrams
        self.usage = usage
        self.cache_key = cache_key
        self.model_used = model_used
        self.cost_usd = cost_usd
        self.cached = cached

    def to_dict(self) -> Dict[str, Any]:
        return {
            "markdown": self.markdown,
            "diagrams": [d.model_dump() for d in self.diagrams],
            "usage": self.usage,
            "cache_key": self.cache_key,
            "model_used": self.model_used,
            "cost_usd": self.cost_usd,
            "cached": self.cached
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OcrResult":
        return cls(
            markdown=data["markdown"],
            diagrams=[GeminiDiagram.model_validate(d) for d in data.get("diagrams", [])],
            usage=data.get("usage", {"input": 0, "output": 0, "thinking": 0}),
            cache_key=data.get("cache_key", ""),
            model_used=data.get("model_used", ""),
            cost_usd=data.get("cost_usd", 0.0),
            cached=True
        )

def compute_cache_key(jpeg_bytes: bytes, model_id: str) -> str:
    h = hashlib.sha256()
    h.update(jpeg_bytes)
    h.update(PROMPT_VERSION.encode("utf-8"))
    h.update(SCHEMA_VERSION.encode("utf-8"))
    h.update(model_id.encode("utf-8"))
    return h.hexdigest()

def repair_json(raw_text: str) -> str:
    """
    Cleans markdown code fences and fixes single backslashes in LaTeX equations
    so standard JSON parsers don't fail on escape sequences like \\theta, \\frac, \\beta.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
        text = text.strip()

    # Repair LaTeX backslashes that are invalid in JSON:
    # Protect valid JSON escape sequences: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
    # But in LaTeX inside JSON strings, \t[letter], \f[letter], \b[letter], \r[letter] are almost always LaTeX!
    text = re.sub(r'\\([bftr])([a-zA-Z])', r'\\\\\1\2', text)
    text = re.sub(r'\\(?![/\\bfnrtu"0-9])', r'\\\\', text)
    return text

def sanitize_latex_escapes(text: str) -> str:
    """
    Restores LaTeX backslashes that were inadvertently unescaped during JSON decoding
    (e.g., \frac, \begin, \text, \theta, \beta, \rho).
    """
    if not text:
        return ""
    # \b -> \x08
    text = re.sub(r'\x08(egin|eta|ar|ullet|old|oxed|f|mod|ra)\b', r'\\b\1', text)
    # \f -> \x0c
    text = re.sub(r'\x0c(rac|lat|orall)\b', r'\\f\1', text)
    # \t -> \x09 (\t)
    text = re.sub(r'\t(ext|extbf|textit|textrm|heta|imes|au|an|o|herefore|ilde)\b', r'\\t\1', text)
    # \r -> \x0d (\r)
    text = re.sub(r'\r(ho|ight|oot)\b', r'\\r\1', text)
    # Clean any remaining rogue form feeds or backspaces
    text = text.replace('\x0c', r'\f').replace('\x08', r'\b')
    return text

def validate_boxes(diagrams: List[GeminiDiagram]) -> List[GeminiDiagram]:
    valid: List[GeminiDiagram] = []
    for d in diagrams:
        if len(d.box_2d) != 4:
            continue
        ymin, xmin, ymax, xmax = d.box_2d
        # Clamp to 0..1000
        ymin = max(0, min(1000, ymin))
        xmin = max(0, min(1000, xmin))
        ymax = max(0, min(1000, ymax))
        xmax = max(0, min(1000, xmax))

        if ymin < ymax and xmin < xmax:
            valid.append(GeminiDiagram(id=d.id, box_2d=[ymin, xmin, ymax, xmax], label=d.label))
        else:
            logger.warning(f"Dropping inverted diagram box: {d.id} -> {[ymin, xmin, ymax, xmax]}")
    return valid

def calculate_cost(usage: Dict[str, int], model_id: str, settings: Settings) -> float:
    pricing = settings.pricing_usd_per_million_tokens.get(
        model_id,
        settings.pricing_usd_per_million_tokens.get("gemini-2.5-pro")
    )
    if not pricing:
        return 0.0

    in_tokens = usage.get("input", 0)
    out_tokens = usage.get("output", 0) + usage.get("thinking", 0)
    cost = (in_tokens * pricing.input + out_tokens * pricing.output) / 1_000_000.0
    return round(cost, 6)

async def ocr_page(
    jpeg_bytes: bytes,
    settings: Settings,
    model_override: Optional[str] = None,
    force_refresh: bool = False,
    rate_wait_cb: Optional[Any] = None
) -> OcrResult:
    """
    Digitizes a single page JPEG image using Gemini Vision with exponential backoff and caching.
    """
    model_id = model_override or settings.gemini_model
    cache_key = compute_cache_key(jpeg_bytes, model_id)
    cache_file = CACHE_DIR / f"{cache_key}.json"

    # 1. Check disk cache
    if not force_refresh and cache_file.exists():
        try:
            cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
            logger.info(f"Cache hit for page (key={cache_key[:8]})")
            cached_res = OcrResult.from_dict(cached_data)
            cached_res.markdown = sanitize_latex_escapes(cached_res.markdown)
            return cached_res
        except Exception as e:
            logger.warning(f"Error reading cache file {cache_file}: {e}")

    # 2. Call Gemini API with exponential backoff
    if not settings.gemini_api_key:
        raise ValueError("Gemini API key is not configured in settings.")

    client = genai.Client(api_key=settings.gemini_api_key)
    delays = [3, 6, 12, 20, 30]
    max_retries = 5
    last_err = None

    for attempt in range(max_retries + 1):
        try:
            logger.info(f"Calling Gemini API (model={model_id}, attempt={attempt+1}/{max_retries+1})")
            
            # Configure thinking budget if specified
            cfg_kwargs: Dict[str, Any] = {
                "system_instruction": SYSTEM_PROMPT,
                "temperature": 0.0,
                "response_mime_type": "application/json",
                "response_schema": GeminiPageResult,
            }
            if settings.thinking_budget > 0:
                try:
                    cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=settings.thinking_budget)
                except Exception:
                    pass

            config = types.GenerateContentConfig(**cfg_kwargs)
            contents = [
                types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
                "IMPORTANT: Extract ONLY the examination problems, questions, diagrams, and options. Strictly omit all exam headers, page numbers, instructions/rules, watermarks, institute/teacher names, and any student handwriting (ticks, circled numbers, annotations). Transcribe ALL questions on this page completely and cleanly without truncating."
            ]

            resp = await client.aio.models.generate_content(
                model=model_id,
                contents=contents,
                config=config
            )

            # Extract parsed output or fallback to repair_json
            parsed_result: Optional[GeminiPageResult] = None
            if hasattr(resp, "parsed") and resp.parsed is not None:
                parsed_result = resp.parsed
            else:
                raw_text = resp.text or ""
                repaired = repair_json(raw_text)
                parsed_result = GeminiPageResult.model_validate_json(repaired)

            if not parsed_result or not parsed_result.markdown:
                raise ValueError("Empty response received from model.")

            clean_md = sanitize_latex_escapes(parsed_result.markdown)

            # Usage metadata
            usage = {"input": 0, "output": 0, "thinking": 0}
            if hasattr(resp, "usage_metadata") and resp.usage_metadata is not None:
                um = resp.usage_metadata
                def _get_int(obj, attr):
                    try:
                        val = getattr(obj, attr, 0)
                        return int(val) if val is not None else 0
                    except (ValueError, TypeError):
                        return 0
                usage["input"] = _get_int(um, "prompt_token_count")
                usage["output"] = _get_int(um, "candidates_token_count")
                usage["thinking"] = _get_int(um, "thoughts_token_count")

            cost_usd = calculate_cost(usage, model_id, settings)
            valid_diagrams = validate_boxes(parsed_result.diagrams)

            result = OcrResult(
                markdown=clean_md,
                diagrams=valid_diagrams,
                usage=usage,
                cache_key=cache_key,
                model_used=model_id,
                cost_usd=cost_usd,
                cached=False
            )

            # Save to disk cache
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to write cache file {cache_file}: {e}")

            return result

        except Exception as e:
            err_str = str(e)
            last_err = e
            is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
            is_server_err = (
                "500" in err_str or "503" in err_str or "UNAVAILABLE" in err_str or
                "json_invalid" in err_str or "EOF while parsing" in err_str or
                "Empty response" in err_str
            )

            if (is_rate_limit or is_server_err) and attempt < max_retries:
                base_delay = delays[attempt]
                jitter = base_delay * random.uniform(-0.2, 0.2)
                wait_sec = max(1.0, round(base_delay + jitter, 1))
                logger.warning(f"Gemini API rate limit/error: {e}. Retrying in {wait_sec}s...")
                if rate_wait_cb:
                    try:
                        rate_wait_cb(wait_sec)
                    except Exception:
                        pass
                await asyncio.sleep(wait_sec)
            else:
                logger.error(f"Gemini API failed permanently: {e}")
                raise last_err or RuntimeError("Gemini OCR call failed.")
