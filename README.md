# 🔎 AI Company Research Assistant

An AI-powered company research application built with **Streamlit** that researches a company from either its **name or website URL**.

The application discovers the official website, gathers information using **Serper.dev**, crawls relevant company pages, analyzes the collected information using a selectable **OpenRouter AI model**, identifies competitors, highlights potential business pain points, and generates a downloadable **PDF research report**.

It also includes an optional **Discord integration** for automatically delivering the generated report to a Discord channel.

## 🚀 Live Demo

**Streamlit App:**  
https://ai-powered-company-research-assistant-dve4bmgj8ep5awhevbegje.streamlit.app/

**GitHub Repository:**  
https://github.com/AshutoshNeekhra/AI-powered-company-research-assistant

---

## ✨ Features

### 🔍 Company Discovery
- Accepts a company name or website URL.
- Automatically searches for the company's likely official website when a name is provided.
- Uses Serper.dev for supporting web research.

### 🌐 Website Crawling
- Crawls the company's website for relevant information.
- Targets important pages such as:
  - Home
  - About
  - Products
  - Services
  - Solutions
  - Contact
  - Pricing
- Skips duplicate URLs, login pages, irrelevant pages, and unsupported files.
- Handles websites that restrict direct crawling by falling back to search-engine research.

### 🤖 AI-Powered Analysis
Uses OpenRouter to analyze the collected information and generate:

- Company summary
- Products and services
- Potential business/operational pain points
- Relevant competitors
- Competitor websites

The application supports multiple OpenRouter models and also provides a custom model option.

### 📊 Competitor Analysis
Competitors are identified based on factors such as:

- Industry
- Products and services
- Market relevance
- Geographic relevance where available

### 📄 PDF Reports
Generate and download a professional PDF containing:

- Company information
- Website
- Summary
- Products/services
- AI-generated pain points
- Competitor analysis

PDF generation is handled using `fpdf2`.

### 💬 Discord Integration — Bonus
Optional Discord integration allows the generated report to be sent to a Discord channel.

The user can provide:

- Discord Bot Token
- Discord Channel ID
- Applicant Name
- Applicant Email

Discord information is stored only for the current Streamlit session and is not persisted in a database.

---

## 🏗️ Architecture

```text
                    ┌─────────────────────┐
                    │    User Input       │
                    │ Company Name / URL  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │    Serper.dev       │
                    │ Official Website    │
                    │ Web Research        │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Website Crawler     │
                    │ Requests + BS4      │
                    │ Key Pages           │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Research Context   │
                    │ Crawled Text +      │
                    │ Search Results      │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │     OpenRouter      │
                    │   AI Analysis       │
                    └──────────┬──────────┘
                               │
                               ▼
              ┌─────────────────────────────────┐
              │       Research Results          │
              │                                 │
              │ • Company Summary               │
              │ • Products / Services           │
              │ • Pain Points                   │
              │ • Competitors                   │
              └───────────────┬─────────────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
             ┌─────────────┐     ┌──────────────┐
             │ PDF Report  │     │ Discord      │
             │ Download    │     │ Integration  │
             └─────────────┘     └──────────────┘
