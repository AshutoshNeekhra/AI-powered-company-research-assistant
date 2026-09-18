"""
Core logic for the Company Research Assistant.
Kept in one module on purpose: search (Serper.dev) -> crawl (requests + bs4)
-> AI reasoning (OpenRouter) -> PDF report (fpdf2) -> optional Discord push.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fpdf import FPDF

# --------------------------------------------------------------------------
# Search — Serper.dev
# --------------------------------------------------------------------------

SERPER_URL = "https://google.serper.dev/search"

BLOCKED_DOMAINS = [
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "wikipedia.org", "crunchbase.com", "glassdoor.com",
    "indeed.com", "bloomberg.com", "reuters.com", "medium.com", "github.com",
]


def serper_search(query: str, api_key: str, num: int = 8) -> list[dict]:
    """Runs one query against Serper.dev and returns normalized organic results."""
    if not api_key:
        raise RuntimeError("Serper.dev API key is missing. Add it in Settings.")

    resp = requests.post(
        SERPER_URL,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "num": num},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for r in data.get("organic", []):
        if r.get("link"):
            results.append({
                "title": r.get("title", ""),
                "link": r["link"],
                "snippet": r.get("snippet", ""),
            })
    return results


def find_official_website(company_name: str, api_key: str) -> str | None:
    """Guesses a company's official site from its name via Serper.dev."""
    results = serper_search(f"{company_name} official website", api_key, num=10)
    for r in results:
        try:
            host = urlparse(r["link"]).hostname or ""
            host = host.lower().removeprefix("www.")
            if any(host == d or host.endswith(f".{d}") for d in BLOCKED_DOMAINS):
                continue
            return f"https://{host}"
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------
# Website crawler
# --------------------------------------------------------------------------

PRIORITY_KEYWORDS = ["about", "product", "service", "solution", "contact", "pricing", "plans", "company"]
IGNORED_PATTERNS = [
    "login", "signin", "sign-in", "signup", "sign-up", "register", "cart",
    "checkout", "account", "privacy", "terms", "cookie", ".pdf", ".jpg",
    ".jpeg", ".png", ".svg", ".gif", ".zip", ".mp4", "mailto:", "tel:", "#",
]
MAX_PAGES = 6
MAX_TEXT_PER_PAGE = 3000
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CompanyResearchBot/1.0)"}


def _normalize(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _is_ignored(url: str) -> bool:
    lower = url.lower()
    return any(p in lower for p in IGNORED_PATTERNS)


def _fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            return None
        if "text/html" not in resp.headers.get("content-type", ""):
            return None
        return resp.text
    except Exception:
        return None


def _extract_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()[:MAX_TEXT_PER_PAGE]


def _extract_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else ""


def _score_link(url: str) -> int:
    lower = url.lower()
    return sum(1 for kw in PRIORITY_KEYWORDS if kw in lower)


def crawl_website(start_url: str) -> list[dict]:
    """Crawls a company site's homepage + up to 5 high-value linked pages."""
    homepage = _normalize(start_url)
    pages: list[dict] = []

    html = _fetch_html(homepage)
    if not html:
        return pages

    soup = BeautifulSoup(html, "lxml")
    visited = {homepage}
    pages.append({"url": homepage, "title": _extract_title(soup), "text": _extract_text(soup)})

    origin = f"{urlparse(homepage).scheme}://{urlparse(homepage).netloc}"
    candidates = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if _is_ignored(href):
            continue
        resolved = urljoin(homepage, href)
        if not resolved.startswith(origin):
            continue
        candidates.add(_normalize(resolved))
    candidates.discard(homepage)

    ranked = sorted(candidates, key=_score_link, reverse=True)[: MAX_PAGES - 1]

    for link in ranked:
        if link in visited:
            continue
        visited.add(link)
        page_html = _fetch_html(link)
        if not page_html:
            continue
        page_soup = BeautifulSoup(page_html, "lxml")
        text = _extract_text(page_soup)
        if text:
            pages.append({"url": link, "title": _extract_title(page_soup), "text": text})

    return pages


# --------------------------------------------------------------------------
# AI reasoning — OpenRouter
# --------------------------------------------------------------------------

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODELS = [
    "openrouter/free",
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-3.5-haiku",
    "google/gemini-2.0-flash-001",
    "meta-llama/llama-3.1-70b-instruct",
    "mistralai/mistral-large",
]

SYSTEM_PROMPT = """You are a meticulous B2B company research analyst.
You will be given raw text scraped from a company's website plus search
engine snippets about that company. Using ONLY that material (do not invent
facts), produce a single JSON object with EXACTLY these keys and nothing else:

{
  "companyName": string,
  "website": string,
  "phone": string,
  "address": string,
  "products": string[],
  "painPoints": string[],
  "summary": string,
  "competitors": [ { "name": string, "website": string } ]
}

Rules:
- Output raw JSON only. No markdown fences, no commentary.
- If a field truly cannot be determined, use "" or [] — never "N/A".
- Competitor websites must be real root domains (e.g. "https://example.com").
- Keep "products" and "painPoints" as short bullet-style phrases.
- Provide 3-6 competitors and 3-6 pain points where possible."""


def _build_user_prompt(company_query, website, crawled_pages, search_snippets, competitor_snippets) -> str:
    pages_block = "\n\n".join(
        f"### Page: {p['url']}\nTitle: {p['title']}\n{p['text']}" for p in crawled_pages
    )[:12000]
    search_block = "\n".join(f"- {s['title']}: {s['snippet']} ({s['link']})" for s in search_snippets)[:3000]
    comp_block = "\n".join(f"- {s['title']}: {s['snippet']} ({s['link']})" for s in competitor_snippets)[:3000]

    return f"""Company query provided by the user: "{company_query}"
Detected official website: {website or 'unknown'}

--- Website content (crawled) ---
{pages_block or '(no content could be crawled from the website)'}

--- General search engine results about the company ---
{search_block or '(none)'}

--- Search results about potential competitors ---
{comp_block or '(none)'}

Now produce the JSON object described in the system prompt."""


def _extract_json(raw: str | None) -> dict:
    """Safely extract a JSON object from an OpenRouter response."""
    if raw is None:
        raise RuntimeError(
            "The AI model returned no text content. "
            "Please try again or select another OpenRouter model."
        )

    if not isinstance(raw, str):
        raw = str(raw)

    if not raw.strip():
        raise RuntimeError(
            "The AI model returned an empty response. "
            "Please try again or select another OpenRouter model."
        )

    cleaned = raw.strip()
    cleaned = re.sub(
        r"^```json",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"^```|```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        raise RuntimeError(
            "The AI model did not return valid JSON. "
            "Please try again or select another OpenRouter model."
        )


def generate_research(company_query, website, crawled_pages, search_snippets,
                       competitor_snippets, model, api_key) -> dict:
    """Calls OpenRouter and returns a normalized research result dict."""
    if not api_key:
        raise RuntimeError("OpenRouter API key is missing. Add it in Settings.")

    resp = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "Company Research Assistant",
        },
        json={
            "model": model,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(
                    company_query, website, crawled_pages, search_snippets, competitor_snippets
                )},
            ],
        },
        timeout=60,
    )
    if not resp.ok:
        raise RuntimeError(f"OpenRouter request failed ({resp.status_code}): {resp.text[:500]}")

    try:
        response_data = resp.json()
    except ValueError as exc:
        raise RuntimeError(
            "OpenRouter returned an invalid JSON response."
        ) from exc

    try:
        message = response_data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "OpenRouter returned an unexpected response structure."
        ) from exc

    content = message.get("content")

    if content is None:
        reasoning = message.get("reasoning")

        if reasoning:
            raise RuntimeError(
                "OpenRouter returned reasoning but no final text content. "
                "Please try the research again or select another free model."
            )

        raise RuntimeError(
            "OpenRouter returned no text content. "
            "Please try again or select another OpenRouter model."
        )

    if not isinstance(content, str):
        content = str(content)

    if not content.strip():
        raise RuntimeError(
            "OpenRouter returned an empty text response. "
            "Please try again or select another OpenRouter model."
        )

    parsed = _extract_json(content)

    competitors = [
        {"name": c.get("name", ""), "website": c.get("website", "")}
        for c in parsed.get("competitors", []) if isinstance(c, dict) and (c.get("name") or c.get("website"))
    ]
    sources = list({p["url"] for p in crawled_pages} | {s["link"] for s in search_snippets})

    return {
        "companyName": parsed.get("companyName") or company_query,
        "website": parsed.get("website") or website or "",
        "phone": parsed.get("phone", ""),
        "address": parsed.get("address", ""),
        "products": [p for p in parsed.get("products", []) if isinstance(p, str)],
        "painPoints": [p for p in parsed.get("painPoints", []) if isinstance(p, str)],
        "summary": parsed.get("summary", ""),
        "competitors": competitors,
        "sources": sources,
        "model": model,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------
# PDF report — fpdf2 (pure Python, no system dependencies)
# --------------------------------------------------------------------------

BRAND_RGB = (91, 91, 245)
DARK_RGB = (33, 33, 41)
GRAY_RGB = (102, 102, 112)


class ReportPDF(FPDF):
    def multi_cell(self, *args, **kwargs):
        # Keep every multi_cell at the left margin. fpdf2 otherwise advances
        # the cursor to the right edge, so a following width=0 cell can have
        # zero available width and raise "Not enough horizontal space...".
        kwargs.setdefault("new_x", "LMARGIN")
        kwargs.setdefault("new_y", "NEXT")
        return super().multi_cell(*args, **kwargs)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", size=8)
        self.set_text_color(*GRAY_RGB)

        half_width = self.epw / 2

        self.cell(
            half_width,
            10,
            "Company Research Assistant",
            align="L",
        )

        self.cell(
            half_width,
            10,
            f"Page {self.page_no()}",
            align="R",
        )


# The core Helvetica font only supports latin-1, and fpdf2's word-wrap has
# no fallback for a single "word" (e.g. a long URL or a run-on token from
# an AI response) that's wider than the page — it just raises
# "Not enough horizontal space to render a single character". _pdf_text()
# neutralizes both problems before any string reaches multi_cell/cell.

_UNICODE_REPLACEMENTS = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " ",
}


def _break_long_tokens(text: str, max_len: int = 45) -> str:
    if not text:
        return text
    words = text.split(" ")
    out = []
    for w in words:
        if len(w) > max_len:
            out.append(" ".join(w[i:i + max_len] for i in range(0, len(w), max_len)))
        else:
            out.append(w)
    return " ".join(out)


def _pdf_text(value) -> str:
    text = str(value or "")
    for bad, good in _UNICODE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    # Drop any remaining character the core font can't render at all,
    # rather than letting fpdf2 raise on it.
    text = text.encode("latin-1", "ignore").decode("latin-1")
    return _break_long_tokens(text)


def _section_heading(pdf: ReportPDF, text: str):
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*BRAND_RGB)
    pdf.ln(2)
    pdf.multi_cell(0, 8, _pdf_text(text))
    pdf.set_text_color(*DARK_RGB)
    pdf.ln(1)


def _bullets(pdf: ReportPDF, items: list[str]):
    pdf.set_font("Helvetica", size=11)
    for item in items:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 6.5, f"-  {_pdf_text(item)}")
    pdf.ln(1)


def generate_pdf(result: dict) -> bytes:
    pdf = ReportPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*DARK_RGB)
    pdf.multi_cell(0, 10, "Company Research Report")

    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(*GRAY_RGB)
    generated = result.get("generatedAt", "")
    pdf.multi_cell(0, 6, _pdf_text(f"Generated {generated} - Model: {result.get('model', '')}"))
    pdf.set_draw_color(220, 220, 228)
    pdf.ln(2)
    pdf.cell(0, 0, "", border="T")
    pdf.ln(6)

    _section_heading(pdf, "Company Information")
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*DARK_RGB)
    pdf.multi_cell(0, 8, _pdf_text(result.get("companyName", "")))
    if result.get("website"):
        pdf.set_font("Helvetica", size=11)
        pdf.set_text_color(*BRAND_RGB)
        pdf.multi_cell(0, 6.5, _pdf_text(result["website"]))
    pdf.set_text_color(*DARK_RGB)
    pdf.set_font("Helvetica", size=11)
    if result.get("phone"):
        pdf.multi_cell(0, 6.5, _pdf_text(f"Phone: {result['phone']}"))
    if result.get("address"):
        pdf.multi_cell(0, 6.5, _pdf_text(f"Address: {result['address']}"))
    if result.get("summary"):
        pdf.ln(1)
        pdf.multi_cell(0, 6.5, _pdf_text(result["summary"]))
    pdf.ln(3)

    _section_heading(pdf, "Products / Services")
    _bullets(pdf, result.get("products") or ["No product or service information could be determined."])

    _section_heading(pdf, "AI-Generated Pain Points")
    _bullets(pdf, result.get("painPoints") or ["No pain points could be determined."])

    _section_heading(pdf, "Competitor Analysis")
    competitors = result.get("competitors") or []
    if not competitors:
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6.5, "No competitors could be determined.")
    else:
        for c in competitors:
            pdf.set_font("Helvetica", "B", 11.5)
            pdf.set_text_color(*DARK_RGB)
            pdf.multi_cell(0, 6.5, _pdf_text(c.get("name") or "Unknown"))
            pdf.set_font("Helvetica", size=10.5)
            pdf.set_text_color(*BRAND_RGB)
            pdf.multi_cell(0, 6, _pdf_text(c.get("website") or "Website unknown"))
            pdf.set_text_color(*DARK_RGB)
            pdf.ln(1)

    return bytes(pdf.output())


# --------------------------------------------------------------------------
# Discord Bot API — send report
# --------------------------------------------------------------------------

def send_to_discord(bot_token: str, channel_id: str, applicant_name: str,
                     applicant_email: str, result: dict, pdf_bytes: bytes) -> None:
    """Posts the applicant + company info and the PDF report to a Discord channel."""
    if not bot_token or not channel_id:
        raise RuntimeError("Discord Bot Token and Channel ID are required.")

    embed = {
        "title": f"Company Research: {result.get('companyName', 'Unknown')}",
        "color": 0x5B5BF5,
        "fields": [
            {"name": "Applicant", "value": applicant_name or "Unknown", "inline": True},
            {"name": "Applicant Email", "value": applicant_email or "Unknown", "inline": True},
            {"name": "Company Website", "value": result.get("website") or "Unknown", "inline": False},
        ],
    }
    payload = {
        "content": f"New company research report generated for **{result.get('companyName', 'Unknown')}**.",
        "embeds": [embed],
    }

    safe_name = re.sub(r"[^a-z0-9-_]+", "-", (result.get("companyName") or "company").lower())[:60] or "company"

    resp = requests.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {bot_token}"},
        data={"payload_json": json.dumps(payload)},
        files={"files[0]": (f"{safe_name}-research-report.pdf", pdf_bytes, "application/pdf")},
        timeout=20,
    )
    if not resp.ok:
        raise RuntimeError(f"Discord API request failed ({resp.status_code}): {resp.text[:500]}")


# --------------------------------------------------------------------------
# Orchestration helper
# --------------------------------------------------------------------------

def looks_like_url(value: str) -> bool:
    value = value.strip()
    if re.match(r"^https?://", value):
        return True
    return bool(re.match(r"^[\w-]+\.[a-z]{2,}(/.*)?$", value, flags=re.IGNORECASE))


def to_url(value: str) -> str:
    value = value.strip()
    if re.match(r"^https?://", value):
        return value
    return f"https://{value}"


def run_research(query: str, model: str, serper_key: str, openrouter_key: str, status_callback=None) -> dict:
    """Runs the full pipeline, calling status_callback(message) at each step."""
    def notify(msg):
        if status_callback:
            status_callback(msg)

    query = query.strip()
    website = None

    if looks_like_url(query):
        website = to_url(query)
        notify(f"Using provided website: {website}")
    else:
        notify(f'Searching the web for "{query}"\'s official website...')
        website = find_official_website(query, serper_key)
        notify(f"Found official website: {website}" if website else
               "Could not confirm an official website - continuing with search data only.")

    notify("Gathering public information from search engines...")
    try:
        general = serper_search(f"{query} company overview products services", serper_key)
    except Exception:
        general = []
    try:
        contact = serper_search(f"{query} phone number address contact", serper_key)
    except Exception:
        contact = []
    try:
        competitor_snippets = serper_search(f"{query} competitors alternatives", serper_key)
    except Exception:
        competitor_snippets = []
    search_snippets = general + contact

    crawled_pages = []
    if website:
        notify(f"Crawling {website} (home, about, products, services, contact, pricing)...")
        crawled_pages = crawl_website(website)
        notify(f"Crawled {len(crawled_pages)} page(s) from the website.")

    notify(f"Analyzing everything with {model}...")
    result = generate_research(query, website, crawled_pages, search_snippets, competitor_snippets, model, openrouter_key)

    notify("Identifying and finalizing competitors...")
    return result
