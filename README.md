# RanAPT

Portfolio Assessment Platform powered by Claude AI agents.

## What it does

RanAPT is a Streamlit app that runs three Claude agents to analyze portfolio documents, generate investment assessments, and produce PDF reports. Upload your financial documents, and the app orchestrates AI-powered analysis across multiple asset classes.

## Architecture

The assessment pipeline runs in a background thread:

1. **Scan** — Extracts text from all documents in a folder (PDF support via pdfplumber)
2. **Asset Reader** — Parses portfolio holdings, positions, and cash balances
3. **Parallel Analysis** — Real Estate Assessor and Global Financial Intelligence run concurrently, using the Asset Reader's output as context
4. **PDF Report** — Generates a formatted report with all agent outputs via ReportLab
5. **Storage** — Results are saved to SQLite for history and trend tracking

## Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| **asset-reader** | Sonnet | Extracts structured portfolio data from financial documents (brokerage statements, account summaries) |
| **real-estate-assessor** | Sonnet | Analyzes real estate holdings using German valuation methods (Vergleichswert/Ertragswert) |
| **global-financial-intelligence** | Opus | Provides macro outlook, market analysis, and portfolio-level insights |
| **scenario-analyst** | Sonnet | Analyzes hypothetical financial/economic scenarios for risks and opportunities |

## Prerequisites

- Python 3.13+
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated (`claude auth`)

## Setup

```bash
# Install dependencies
pip3 install streamlit plotly pandas python-dateutil pdfplumber reportlab openpyxl

# Bootstrap Claude Code agents (creates .claude/agents/ and .claude/agent-memory/)
./bootstrap-agents.sh

# Run the app
streamlit run app.py
```

The bootstrap script deletes any existing agents and recreates them from scratch with the correct prompts. Run it whenever you clone the repo or need to reset agent definitions.

## Project Structure

```
RanAPT/
├── app.py                     # Streamlit entry point
├── config.py                  # Paths and constants
├── db/
│   ├── schema.py              # DDL, init_db(), get_connection()
│   └── queries.py             # Typed SQL helpers
├── agents/
│   ├── loader.py              # Loads agent .md files, strips YAML front-matter
│   └── runner.py              # Invokes claude CLI via subprocess
├── ingestion/
│   ├── file_scanner.py        # Scans folders for documents
│   └── pdf_extractor.py       # pdfplumber text extraction
├── tasks/
│   └── background.py          # Background assessment pipeline
├── pdf_report/
│   └── generator.py           # ReportLab PDF generation
├── pages/
│   ├── 1_New_Assessment.py    # Folder picker, file preview, live status
│   ├── 2_History.py           # Snapshot history, results, PDF download
│   └── 3_Settings.py          # CLI status, storage info
├── bootstrap-agents.sh        # Recreates all agents from scratch
└── .claude/
    ├── agents/                # Agent system prompt definitions (.md)
    └── agent-memory/          # Persistent memory per agent
```

## Tech Stack

- **Streamlit** — UI and multi-page app framework
- **Claude CLI** — AI agent execution (no API key needed, uses CLI auth)
- **SQLite** — Assessment history and snapshots
- **ReportLab** — PDF report generation
- **pdfplumber** — PDF text extraction
- **Plotly** — Trend charts and data visualization
- **pandas** — Data handling
