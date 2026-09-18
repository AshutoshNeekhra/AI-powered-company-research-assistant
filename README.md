# Company Research Assistant (Streamlit)

A single-stack Python app — no Node/npm, no build step — that researches
any company from a **name** or **website URL**: it finds the official
site, crawls the key pages, searches the web for supporting facts, runs
everything through an OpenRouter-hosted AI model, identifies competitors,
and produces a downloadable **PDF report**, with optional automatic
delivery to a **Discord channel**.

## Files

```
app.py            Streamlit chat UI
utils.py          Search (Serper.dev) + crawler (requests/bs4) + AI (OpenRouter)
                  + PDF (fpdf2) + Discord (Bot API) — all the actual logic
requirements.txt  pip dependencies
.streamlit/secrets.toml.example   template for your API keys
```

## 1. Install

```bash
pip install -r requirements.txt
```

## 2. Configure your API keys

Copy the example secrets file and fill in your keys:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

```toml
SERPER_API_KEY = "..."          # https://serper.dev
OPENROUTER_API_KEY = "..."      # https://openrouter.ai/keys
OPENROUTER_DEFAULT_MODEL = "openai/gpt-4o-mini"
```

(Env vars `SERPER_API_KEY` / `OPENROUTER_API_KEY` also work if you'd rather
not use `secrets.toml`.)

Discord Bot Token / Channel ID / applicant name & email are entered in the
app's **sidebar** at runtime — kept only in that browser session, no
database, per the "no auth / no persistence" requirement.

## 3. Run

```bash
streamlit run app.py
```

## 4. Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repo.
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app** →
   point it at `app.py` in your repo.
3. Under **Advanced settings → Secrets**, paste the same two keys as TOML
   (same format as `secrets.toml.example`).
4. Deploy — you'll get a public URL automatically.

## How it works

1. You type a company name or URL into the chat box.
2. If it's a name, Serper.dev finds the likely official website.
3. Three Serper.dev searches run for company overview, contact info, and
   competitors.
4. The site is crawled (home + up to 5 more pages: about/products/services/
   contact/pricing), skipping duplicates, logins, and binary files.
5. Crawled text + search snippets go to your chosen OpenRouter model with a
   strict JSON-output prompt → summary, products, pain points, competitors.
6. A PDF report is generated with `fpdf2` (pure Python, no system deps —
   works out of the box on Streamlit Cloud).
7. Optionally, one click posts the applicant info, company info, and the
   PDF to a Discord channel via the Discord Bot API.

## Notes

- No database, accounts, or auth — everything lives in the Streamlit
  session for the current visit.
- The AI model dropdown covers a few popular OpenRouter models plus a
  "Custom..." option for any other model slug.
- If a site blocks scraping, the assistant still produces a result from
  search-engine snippets alone — just with less detail.
