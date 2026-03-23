# Multi-Agent Intelligence Prediction System

A self-improving multi-agent intelligence system that ingests data from 20+ free sources, makes structured predictions with precise timeframes, tracks every prediction through its full lifecycle, and learns from hits and misses through calibration feedback loops.

The core innovation is the **accountability loop**: predict → monitor → score → learn → predict better. The intelligence lives not in the LLM (which stays frozen) but in the structured context it receives — calibration history, reasoning guidance, base rates, and cross-domain signals that get richer with every cycle.


## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Railway Project                           │
│                                                                  │
│  ┌─────────┐    ┌─────────┐                                     │
│  │PostgreSQL│    │  Redis   │                                     │
│  │   (DB)   │    │(Queues)  │                                     │
│  └────┬─────┘    └────┬─────┘                                     │
│       │               │                                           │
│  ┌────┴───────────────┴────────────────────────────────────┐     │
│  │                  Shared Library                          │     │
│  │  models.py · schemas.py · llm_client.py · config.py     │     │
│  └──────────┬──────────┬──────────┬──────────┬─────────────┘     │
│             │          │          │          │                    │
│  ┌──────────┴┐  ┌──────┴────┐  ┌─┴────────┐ │                   │
│  │ Ingestion │  │Verification│  │  Agents  │ │                   │
│  │  Worker   │──│  Engine    │──│  Engine  │ │                   │
│  │ (cron 4h) │  │ (queue +   │  │ (queue + │ │                   │
│  │ 9 sources │  │  hourly)   │  │  daily)  │ │                   │
│  └───────────┘  └───────────┘  └──┬───────┘ │                   │
│                                    │         │                   │
│       ┌────────────────────────────┤         │                   │
│  ┌────┴─────┐  ┌─────────────┐    │    ┌────┴──────┐           │
│  │ Feedback  │  │ Weak Signal │    │    │ Frontend  │           │
│  │ Processor │  │  Scanner    │    │    │ Dashboard │           │
│  │(always-on)│  │(daily cron) │    │    │ (Next.js) │           │
│  └───────────┘  └─────────────┘    │    └───────────┘           │
│                                    │                             │
│                              ┌─────┴─────┐                      │
│                              │ API Server │                      │
│                              │  (FastAPI) │                      │
│                              └───────────┘                      │
└──────────────────────────────────────────────────────────────────┘

Data Flow:
  Ingestion ──ingestion_complete──► Agents ──analysis_complete──► Feedback
  Ingestion ──verification_needed─► Verification
  Verification ──verification_complete──► Agents
  Feedback ──debate_trigger──► Agents
  All services ──read/write──► PostgreSQL
  Frontend ──HTTP/WS──► API Server ──queries──► PostgreSQL
```


## The 9 Services

**PostgreSQL** — Central database storing all predictions, events, claims, calibration scores, debates, and agent prompts. Railway one-click template.

**Redis** — Message broker for inter-service communication via queues (ingestion_complete, analysis_complete, verification_needed, verification_complete, debate_trigger). Also used for caching. Railway one-click template.

**API Server** (services/api/) — FastAPI backend exposing 16 REST endpoints plus a WebSocket chat interface. Handles authentication, serves the frontend, and runs Alembic migrations on startup.

**Frontend Dashboard** (services/frontend/) — Next.js 15 App Router application with 9 pages, 12 reusable components, Recharts charts, and a TailwindCSS dark theme. Provides the human interface for monitoring predictions, agents, debates, and system calibration.

**Data Ingestion Worker** (services/ingestion/) — Cron-triggered worker (every 4 hours) that pulls from 9 data sources (GDELT, FRED, RSS feeds, NewsData, Twelve Data, ProPublica, ACLED, Polymarket, CFTC), runs NLP entity extraction via spaCy, classifies events, deduplicates, extracts claims, and publishes to Redis.

**Verification Engine** (services/verification/) — Cross-modal claim verification pipeline. Checks claims against 7 data modalities (satellite imagery, ship tracking, flight data, trade data, financial flows, nighttime lights, diplomatic records). Applies Bayesian integrity scoring and detects sponsored content via Claude Haiku.

**Agent Analysis Engine** (services/agents/) — Orchestrates 6 AI agents (5 specialists + 1 master strategist) through the 7-question structural reasoning chain. Each agent uses Claude Sonnet for analysis, with GPT-4o devil's advocate challenges for high-confidence predictions.

**Feedback Processor** (services/feedback/) — Always-on worker that closes the accountability loop. Auto-resolves expired predictions, calculates Brier scores, rebuilds calibration curves, detects bias, updates agent prompts, monitors sub-prediction health, and runs periodic red team challenges.

**Weak Signal Scanner** (services/signals/) — Daily cron job that scans for orphan events (events no agent claimed as relevant), runs anomaly detection via IsolationForest, and conducts pre-mortem analysis via Claude with web search.


## Prerequisites

- Python 3.12+
- Node.js 20+
- Docker & Docker Compose
- API keys: Anthropic (Claude), OpenAI (GPT-4o), FRED, NewsData, Twelve Data


## Local Development Setup

1. **Clone and configure:**

```bash
cp .env.example .env
# Edit .env with your API keys
```

2. **Start all services:**

```bash
docker-compose up --build
```

This starts PostgreSQL, Redis, and all 7 application services. The API server automatically runs database migrations on startup.

3. **Access the system:**

- Dashboard: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

4. **Trigger an ingestion cycle manually** (optional):

```bash
docker-compose exec ingestion python -m services.ingestion.main
```

5. **Trigger an agent analysis cycle manually** (optional):

```bash
docker-compose exec agents python -m services.agents.main
```


## Running Tests

From the monorepo root:

```bash
pip install -r tests/requirements.txt
pip install -r shared/requirements.txt
pip install -r services/api/requirements.txt
pip install -r services/ingestion/requirements.txt
pip install -r services/verification/requirements.txt
pip install -r services/agents/requirements.txt
pip install -r services/feedback/requirements.txt
pip install -r services/signals/requirements.txt

pytest tests/ -v
```

The test suite (139 tests) covers shared library imports, ORM model definitions, Pydantic schema validation, API route registration, Redis queue name consistency, Dockerfile correctness, docker-compose configuration, railway.toml configuration, and utility function behavior.

No live database or Redis is required — tests use SQLite and mock external dependencies.


## Railway Deployment

### Step-by-step

1. **Create a Railway project** at https://railway.app

2. **Add infrastructure services:**
   - Add PostgreSQL (one-click template)
   - Add Redis (one-click template)

3. **Connect your GitHub repository** containing this monorepo.

4. **Create application services** — for each, set the root directory:

   | Service       | Root Directory          | Notes                    |
   |---------------|------------------------|--------------------------|
   | api           | services/api           | Exposes port 8000        |
   | frontend      | services/frontend      | Exposes port 3000        |
   | ingestion     | services/ingestion     | Cron: `0 */4 * * *`     |
   | verification  | services/verification  | Runs continuously        |
   | agents        | services/agents        | Runs continuously        |
   | feedback      | services/feedback      | Runs continuously        |
   | signals       | services/signals       | Cron: `0 6 * * *`       |

   Railway auto-detects Dockerfiles in each directory. Since the Dockerfiles use the monorepo root as build context, Railway handles this correctly when the service root is set.

5. **Set shared environment variables** (all application services):

   | Variable            | Source                          |
   |---------------------|---------------------------------|
   | DATABASE_URL        | Railway PostgreSQL (auto-linked)|
   | REDIS_URL           | Railway Redis (auto-linked)     |
   | ANTHROPIC_API_KEY   | Your Anthropic API key          |
   | OPENAI_API_KEY      | Your OpenAI API key             |
   | FRED_API_KEY        | Free from FRED                  |
   | NEWSDATA_API_KEY    | Free from NewsData.io           |
   | TWELVE_DATA_API_KEY | Free from Twelve Data           |
   | API_KEY             | A strong random string          |

6. **Set frontend-specific variables:**

   | Variable              | Value                                    |
   |-----------------------|------------------------------------------|
   | NEXT_PUBLIC_API_URL   | Public URL of the API service            |
   | NEXT_PUBLIC_API_KEY   | Same value as API_KEY                    |

7. **Deploy.** The API server runs Alembic migrations automatically on startup.


### Estimated Monthly Costs

| Component              | Cost        |
|------------------------|-------------|
| Railway infrastructure | $50–120     |
| LLM API (Claude + GPT) | $40–100    |
| Data sources           | $0 (free)   |
| **Total**              | **$90–220** |


## Environment Variable Reference

| Variable                  | Required | Used By          | Description                                    |
|---------------------------|----------|------------------|------------------------------------------------|
| DATABASE_URL              | Yes      | All Python       | PostgreSQL connection string                   |
| REDIS_URL                 | Yes      | All Python       | Redis connection string                        |
| ANTHROPIC_API_KEY         | Yes      | agents, verification, signals, api | Claude API key              |
| OPENAI_API_KEY            | Yes      | agents           | GPT-4o API key (devil's advocate)              |
| FRED_API_KEY              | Yes      | ingestion        | FRED economic data API key                     |
| NEWSDATA_API_KEY          | Yes      | ingestion        | NewsData.io API key                            |
| TWELVE_DATA_API_KEY       | Yes      | ingestion        | Twelve Data market API key                     |
| API_KEY                   | Yes      | api              | API authentication key                         |
| NEXT_PUBLIC_API_URL       | Yes      | frontend         | URL of the API server                          |
| NEXT_PUBLIC_API_KEY       | Yes      | frontend         | Must match API_KEY                             |
| LOG_LEVEL                 | No       | All Python       | Logging level (default: INFO)                  |
| ENVIRONMENT               | No       | All Python       | development or production (default: development)|
| CLAUDE_SONNET_MODEL       | No       | All Python       | Claude model ID (default: claude-sonnet-4-20250514) |
| CLAUDE_HAIKU_MODEL        | No       | All Python       | Haiku model ID (default: claude-haiku-4-5-20251001) |
| GPT4O_MODEL               | No       | All Python       | GPT model ID (default: gpt-4o)                 |
| MIN_EVIDENCE_INTEGRITY    | No       | All Python       | Minimum evidence score (default: 0.50)         |
| CONFIDENCE_CAP_MULTIPLIER | No       | All Python       | Confidence cap factor (default: 0.40)          |


## Project Structure

```
intelligence-system/
├── shared/                  # Shared library (all services import from here)
│   ├── models.py            # 14 SQLAlchemy ORM models
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── llm_client.py        # Claude + GPT-4o client wrappers
│   ├── config.py            # Centralized settings from env vars
│   ├── database.py          # SQLAlchemy engine + session factory
│   └── utils.py             # ID generation, confidence capping, Brier scores
├── services/
│   ├── api/                 # FastAPI backend (16 endpoints + WebSocket)
│   ├── frontend/            # Next.js 15 dashboard (9 pages, 12 components)
│   ├── ingestion/           # Data ingestion (9 sources, NLP, dedup, claims)
│   ├── verification/        # Cross-modal verification (7 modalities)
│   ├── agents/              # 6 AI agents + devil's advocate
│   ├── feedback/            # Brier scoring, calibration, bias detection
│   └── signals/             # Anomaly detection, orphan scanning, pre-mortem
├── prompts/                 # Agent system prompts (version controlled)
├── migrations/              # Alembic database migrations
├── tests/                   # Integration test suite (139 tests)
├── docker-compose.yml       # Local development orchestration
├── railway.toml             # Railway deployment configuration
├── alembic.ini              # Alembic configuration
└── .env.example             # Environment variable template
```


## The 6 AI Agents

| Agent               | Domain      | LLM            | Focus                                         |
|---------------------|-------------|----------------|-----------------------------------------------|
| Geopolitical        | geopolitical| Claude Sonnet  | International relations, conflicts, alliances  |
| Macro Economist     | economic    | Claude Sonnet  | GDP, inflation, trade, central bank policy     |
| Market/Investor     | market      | Claude Sonnet  | Equities, commodities, positioning, flows      |
| Domestic Political  | political   | Claude Sonnet  | US legislation, elections, regulatory changes   |
| Sentiment/Narrative | sentiment   | Claude Sonnet  | Media narratives, public opinion shifts         |
| Master Strategist   | all         | Claude Sonnet  | Cross-domain synthesis, convergence, blind spots|

Each specialist runs the 7-question structural reasoning chain with deep motivational analysis. The Master Strategist runs after all specialists, looking for convergence, contradiction, and blind spots across domains.

Devil's advocate challenges (GPT-4o) are triggered when a prediction's confidence moves >5pp, exceeds 60%, agrees with consensus, invokes historical analogy, or is driven by a single data point.


## Key Design Principles

**Confidence capping**: No prediction confidence change can exceed the integrity score of the underlying evidence. An agent wanting +15pp based on 0.40-integrity evidence gets max +6pp. This is enforced in code.

**Cross-modal verification**: Faking a news article is cheap. Faking satellite imagery + shipping records + trade data + financial flows simultaneously is essentially impossible. The verification engine checks claims across data modalities, not just news sources.

**Predictions as living objects**: Every prediction has a confidence trail (every change with reasoning), analyst notes, devil's advocate debates, sub-predictions, and a post-mortem on resolution.

**Prompt evolution**: Agent prompts are version-controlled. The feedback processor injects calibration notes based on measured performance (e.g., "In 30-40% range, you resolve TRUE 60% — adjust upward by ~15pp"). The intelligence improves through structured context, not model fine-tuning.
