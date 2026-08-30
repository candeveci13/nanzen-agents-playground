# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make install               # uv sync
make style                  # ruff format + ruff check --fix (src/, tests/)
make test                   # uv run pytest -v
make run                    # run all tasks
make run ARGS="--task billing_summary"   # run a single task
make run ARGS="--list"      # list available task names
make run ARGS="--parallel"  # run all tasks concurrently (thread per task)

# Single test:
uv run pytest tests/test_tools.py::TestCSVReader::test_read_billing -v
```

`MODEL_ID` must be set before `make run` (any OpenAI-compatible endpoint —
Fireworks, Together, OpenRouter, Ollama, llama.cpp). `API_KEY`/`API_BASE` are
optional. See `.env.example`; load with `set -a && source .env && set +a`.

## Architecture

This is a multi-agent system where each **task** spawns its own **ActorAgent**
(`src/challenge/agent.py`), a thin wrapper around a `smolagents.CodeAgent` that
writes and executes Python to call tools. There is no shared agent state across
tasks — agents are cheap, stateless, and rebuilt per run; the only thing shared
across them is the on-disk data in `data/`.

Data flow: `runner.py` reads `TASKS` from `tasks.py` → builds one `ActorAgent`
per task → each agent's `CodeAgent` loop calls `CSVReaderTool.read_context` to
pull rows from `data/*.csv` (optionally filtered by `account_id`) → the agent
reasons over the data in its Python sandbox → calls `PDFReportTool.create_report`
to render a PDF into `output/`. `runner.py` collects a `{task, agent, status,
result}` dict per task and prints a summary; `--parallel` runs tasks in a
`ThreadPoolExecutor`, one thread per task, each creating its own model client.

Key extension points:
- **Adding a task**: append a dict to `TASKS` in `tasks.py` (name, agent_name,
  role, prompt). No other wiring needed — `runner.py` picks it up automatically.
- **Adding a data source**: register it in `DATA_SOURCES` in
  `tools/csv_reader.py` and add the CSV under `data/`. Sources are looked up by
  key, not by filename, and are described to agents in `agent.py`'s
  `INSTRUCTIONS_TEMPLATE` — update that list too so agents know it exists.
- **Adding a tool**: subclass `smolagents.Tool` (see `csv_reader.py` /
  `pdf_report.py` for the shape: `name`, `description`, `inputs`, `output_type`,
  `forward()`), then pass it via `ActorAgent(..., tools=[...])` — it's merged
  with the default `[CSVReaderTool(), PDFReportTool()]`.
- **PDF content model**: `PDFReportTool` takes a JSON array of typed sections
  (`heading`, `paragraph`, `table`, `chart`) rather than freeform markup —
  agents assemble this JSON themselves. Charts are rendered via matplotlib to
  PNG bytes, then embedded as an `Image` flowable (see `_render_chart` in
  `tools/pdf_report.py` for supported `chart_type`s: bar/line/pie).

`DATA_DIR` and `OUTPUT_DIR` are resolved as `Path(__file__).resolve().parents[3]`
relative to the tool module — i.e. always the repo root's `data/` and `output/`,
regardless of where the code is invoked from.

## Data model

All CSVs key off `account_id` (e.g. `MERID-001`) and share a naming convention
of `<PREFIX>-<NNNN>` for row IDs (`BIL-`, `CTR-`, `CRM-`, `EM-`, `TKT-`,
`PO-`, `INT-`). `contracts.csv` and `purchase_orders.csv` link via
`contract_reference`/`po_number`; `support_tickets.csv` has both an
`interaction_id` (one row per message) and a `ticket_id` (groups messages into
a thread). `CSVReaderTool.forward` truncates to `limit` (default 50) and only
filters by `account_id` when that column exists on the source — check a
source's columns before assuming a filter took effect.
