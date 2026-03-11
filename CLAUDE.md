# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Two things coexist here:

1. **Claude Code agent workspace** (`.claude/agents/`) — three sub-agent definitions that Claude Code routes user requests to interactively
2. **RanAPT Streamlit app** (`Home.py`, `pages/`, `db/`, `agents/`, etc.) — a Python app that runs those same agents locally via the `claude` CLI to perform batch portfolio assessments

## Running the app

```bash
streamlit run Home.py
```

Install dependencies first if needed:
```bash
pip3 install streamlit plotly pandas python-dateutil pdfplumber reportlab openpyxl
```

Prerequisite: the `claude` CLI must be installed and authenticated (`claude auth`).


## Streamlit app architecture

The app is a multi-page Streamlit app with a background-execution pipeline:

**Execution flow** (`tasks/background.py`):
1. Scan folder → extract text from all docs
2. `asset-reader` runs first (sequential) — its markdown output becomes portfolio context for step 3
3. `real-estate-assessor` + `global-financial-intelligence` run in parallel (ThreadPoolExecutor)
4. PDF report generated via ReportLab
5. DB snapshot status → `completed`

**Key design decisions:**
- Each background thread opens its own SQLite connection (`check_same_thread=False`) — DB is at `~/.ranapt/ranapt.db`
- Streamlit polls thread liveness with `time.sleep(2)` + `st.rerun()` in `pages/1_New_Assessment.py`
- Agent `.md` files are loaded by `agents/loader.py` which strips YAML front-matter (splits on `^---\s*$`, takes `parts[2]`)
- `agents/runner.py` invokes the `claude` CLI in print mode (`claude -p --output-format json --system-prompt ...`) via subprocess; concatenates extracted file text with `=== FILE: name ===` headers as stdin; passes `extra_context` string for chaining asset-reader output to global-financial-intelligence

## Claude Code agents (`.claude/agents/`)

The three `.md` files define sub-agents for **interactive Claude Code sessions** (not the Streamlit app). Format:

```
---
name: agent-name
description: "Trigger description with <example> blocks"
model: sonnet
color: blue
memory: project
---
[System prompt]
```

The `description` field controls routing — keep examples specific. The YAML block is Claude Code metadata only; `agents/loader.py` strips it before sending to the API.

## Agent memory

Each agent has `.claude/agent-memory/<agent-name>/MEMORY.md` for durable institutional knowledge. Convention:
- `MEMORY.md` = stable patterns (≤200 lines, loaded into system prompt)
- Dated files (e.g., `portfolio-analysis-march-2026.md`) = session artifacts
- Append new learnings; don't replace existing entries

## Known quirks

**Revolut Securities Europe UAB PDFs**: 3-page structure — Page 1 = USD account (often empty), Page 2 = EUR holdings, Page 3 = legal footer. The "Cash value" line always shows €0 — ignore it. `pdfplumber` works well for extraction.

**Berlin real estate**: Acquisition costs ~10.5–12.5% above purchase price (6% Grunderwerbsteuer + ~2% notary/Grundbuch + ~2.975–3.57% broker). Primary valuation method: Vergleichswertverfahren; cross-check with Ertragswertverfahren.

**Web research in agents**: WSJ/NYT are paywalled — use WebSearch, not WebFetch, for those sources.
