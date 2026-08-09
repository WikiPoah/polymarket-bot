<!-- File-Version: 1.3.2 -->
# Polymarket Bot

Polymarket Bot is a Python backend for researching geopolitical prediction
markets. It retrieves active Polymarket markets, gathers external intelligence,
classifies and matches relevant events, estimates probabilities, applies risk
rules, and records paper-trading decisions for review and historical analysis.

The project is under active development. It does **not** place live orders or
control real funds.

## What the bot focuses on

The bot is focused on **geopolitical prediction markets**, not exclusively oil.
Oil and energy disruption are important parts of that scope because conflicts,
sanctions, shipping constraints, and supply decisions can affect energy-related
markets.

The current classification system covers:

- oil, natural gas, OPEC, and energy disruption;
- military strikes, invasions, exercises, and escalation;
- sanctions and economic policy;
- shipping disruption and strategic waterways such as the Red Sea and Strait
  of Hormuz;
- leadership changes and elections;
- nuclear, diplomatic, and terrorism-related events.

The bot evaluates Polymarket contracts connected to these events. It does not
trade oil futures, commodities, or securities.

Precision is favored over broad keyword matching. An intelligence event must
provide evidence for the market's actual proposition before it can become a
trading opportunity.

## How it works

```text
Polymarket active markets
  -> geopolitical market filtering
  -> market classification and query building
  -> GDELT, RSS, and ReliefWeb intelligence
  -> event and outcome classification
  -> relevance filtering and evidence scoring
  -> market matching
  -> probability, expected-value, and risk evaluation
  -> paper-trading records and dashboard
```

The repository also contains resumable historical collectors and a
timestamp-aware replay path. Historical evaluation is designed to expose only
information available at each replay timestamp.

## Requirements

- Python 3.10 or newer
- Internet access for live market and intelligence retrieval
- A GDELT Cloud API key for the GDELT provider
- A ReliefWeb-approved application name for ReliefWeb access

The dashboard demo does not require API credentials or internet access.

## Installation

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

For a runtime-only installation without test and lint tools, install
`requirements.txt` instead.

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

All commands below assume they are run from the repository root. They use the
virtual environment's Python directly, so activation is optional.

## Show the dashboard with demo data

This is the quickest way to demonstrate the project. It creates a separate demo
history file and does not contact Polymarket or any intelligence provider.

### 1. Generate demo paper-trading history

```bash
.venv/bin/python -m src.dashboard.demo
```

The command writes:

```text
data/demo_paper_trading_history.json
```

### 2. Start the dashboard

```bash
.venv/bin/python -m src.dashboard \
  --history data/demo_paper_trading_history.json
```

The server listens on the local machine at:

```text
http://127.0.0.1:8080
```

Open that address in a browser. The dashboard shows:

- system health and provider freshness;
- a funnel from evaluated opportunities to accepted, rejected, and ignored
  decisions;
- accepted paper-trade ideas with the bot estimate, market probability, edge,
  confidence, catalyst, sources, and rationale;
- settled paper-trading performance when outcomes become available;
- recent activity;
- expandable ignored and portfolio-risk-rejected decisions.

Demo history contains trading decisions but no live runner status, so system
health can display `UNKNOWN`. That is expected.

### How to read the dashboard

The decision funnel separates candidate evaluation from paper-trade acceptance:

- **Evaluated** is every market-and-event opportunity considered by the
  strategy.
- **Accepted** is a `BUY YES` or `BUY NO` paper-trade idea that passed the
  strategy and portfolio-risk checks.
- **Risk rejected** is an otherwise actionable idea blocked by portfolio-level
  controls such as exposure, confidence, or position limits.
- **Ignored** is an opportunity that did not pass the strategy thresholds.
- **Settled** is an accepted paper trade whose market outcome is known.

An accepted idea is not evidence that the bot was correct. The dashboard shows
win rate and realized paper profit/loss only after accepted trades settle.
Until then, use the bot estimate, market probability, edge, confidence,
intelligence catalyst, sources, and rationale to review why the idea was
accepted.

Press `Ctrl+C` in the terminal to stop the server.

### Use another port

```bash
.venv/bin/python -m src.dashboard \
  --history data/demo_paper_trading_history.json \
  --port 8090
```

Then open `http://127.0.0.1:8090`.

The dashboard binds to `127.0.0.1` by default. Keep that default unless you
specifically intend to expose it to another machine on a trusted network.

## Configuration

Configuration is loaded from `.env`. Never commit the populated `.env` file.

| Variable | Required | Purpose |
| --- | --- | --- |
| `GDELT_API_KEY` | For live GDELT retrieval | GDELT Cloud API authentication |
| `RELIEFWEB_APPNAME` | For ReliefWeb retrieval | Exact application name approved by ReliefWeb |
| `MEDIA_CLOUD_API_KEY` | Optional | Media Cloud historical collection |
| `MEDIA_CLOUD_COLLECTION_IDS` | Optional | Comma-separated Media Cloud collection IDs |

ReliefWeb may reject arbitrary application names with HTTP 403. Use only the
exact name approved for your application; do not attempt to bypass provider
access controls.

Default RSS sources and general thresholds are defined in `src/config.py`.

## Run a live paper evaluation

The live runner retrieves the 100 highest-volume active Polymarket markets,
filters them to geopolitical markets, gathers intelligence, evaluates matching
opportunities, and records paper decisions. The bounded scan keeps each cycle
responsive while prioritizing markets with meaningful activity. It does not
submit orders.

Configure `.env`, then run one evaluation:

```bash
.venv/bin/python -m src.main
```

Normal runs show only the concise evaluation and decision summary. To inspect
provider queries, event classification, relevance filtering, scoring, and
matching, enable diagnostic logging:

```bash
.venv/bin/python -m src.main --log-level DEBUG
```

Use `--log-level INFO` for run-level pipeline progress without per-event
diagnostics. The default level is `WARNING`.

Default runtime files are:

```text
data/paper_trading_history.json
data/system_status.json
data/historical_markets.json
data/historical_intelligence.json
```

Provider failures are isolated where possible. For example, an unavailable
GDELT or ReliefWeb provider is reported while other configured providers can
still contribute intelligence.

To evaluate continuously with a fixed delay between completed runs:

```bash
.venv/bin/python -m src.main --interval 300
```

Press `Ctrl+C` to stop the runner.

To view records produced by the live runner, start the dashboard with its
default history path. Do not pass the demo-history option when reviewing live
paper-evaluation records:

```bash
.venv/bin/python -m src.dashboard
```

Then open `http://127.0.0.1:8080`.

## Run the tests

Run the full test suite from the repository root:

```bash
.venv/bin/python -m pytest -q
```

Run a focused component test while developing:

```bash
.venv/bin/python -m pytest -q tests/test_pipeline.py
```

Generate a terminal coverage report:

```bash
.venv/bin/python -m pytest -q --cov=src --cov-report=term-missing
```

Run the static checks:

```bash
.venv/bin/python -m ruff check .
```

GitHub Actions runs lint and tests on Python 3.10 and 3.13 for pushes and pull
requests.

## Historical dataset workflow

Historical collection is separate from the live paper runner. Collection is
resumable and uses checkpoints, manifests, provider partitions, and explicit
coverage validation.

Collection output is local runtime data and is ignored by Git. Preserve any
dataset needed for an experiment outside disposable working directories.

Inspect an existing collection without making network requests:

```bash
.venv/bin/python -m src.historical_dataset \
  --output-dir data/historical_selection_2026-02_to_2026-08 \
  --intelligence-status
```

Before a long collection, use a separate output directory for a short pilot:

```bash
.venv/bin/python -m src.historical_dataset \
  --start 2026-03-01T00:00:00+00:00 \
  --end 2026-03-04T00:00:00+00:00 \
  --output-dir data/historical_intelligence_pilot \
  --intelligence-only
```

Do not point experiments at a frozen production dataset. Do not start replay
until the required coverage and leakage-safety checks pass.

## Project structure

```text
src/
  main.py                 command-line entry point
  api.py                  Polymarket Gamma API client
  filters.py              geopolitical market filtering
  intelligence/           providers, classification, relevance, scoring, matching
  strategy/               probability, expected value, sizing, and risk rules
  paper_trading/          decision history, analytics, backtesting, and replay
  dashboard/              local monitoring dashboard and demo data
  historical_dataset.py   resumable historical collection and validation
  coverage_probe.py       read-only historical source coverage checks
  monitoring.py           persistent runner and provider status
  runner.py               one-shot and continuous evaluation orchestration
tests/                     automated regression tests
research/                  investigations and reproducible project records
data/                      selected fixtures, datasets, and runtime output
```

## Current limitations

- Paper trading only; there is no live order execution.
- Probability estimation and thresholds are heuristic and require calibration
  against leakage-safe historical results.
- Intelligence quality depends on provider availability, authorization, and
  coverage.
- The system supports selected geopolitical entities and event categories; it
  is not a general-purpose news trading engine.
- The dashboard is a local operational monitor, not a hardened public web
  application.

## Safety

This project is for software engineering, research, and paper-trading analysis.
Prediction markets involve financial risk. Do not treat generated decisions as
financial advice, and do not connect the system to real execution without
independent validation, controls, and legal review.
