# News Intelligence Platform

A modern news aggregation and intelligence platform that ingests from multiple sources (RSS, Hacker News, Reddit), deduplicates content, scores signals, and generates daily briefings.

## Features

- **Multi-source ingestion**: RSS feeds, Hacker News API, Reddit API
- **Intelligent deduplication**: Exact matching + semantic similarity using embeddings
- **Signal scoring**: Relevance, velocity, cross-source validation, novelty
- **AI briefings**: Automated summaries for top signals using Claude/GPT
- **Observability**: Structured logging and metrics from day one

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.12+
- API keys (optional): OpenAI, Anthropic, Reddit

### Local Development

1. **Clone and setup**
   ```bash
   git clone <repo-url>
   cd news-bot
   cp backend/.env.example backend/.env
   # Edit .env with your API keys
   ```

2. **Start services**
   ```bash
   docker-compose up -d
   ```

3. **Seed initial sources**
   ```bash
   docker-compose exec api python -m scripts.seed_sources
   ```

4. **Access the API**
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs
   - Health: http://localhost:8000/health

### Manual ingestion

```bash
# Trigger ingestion manually
docker-compose exec api python -c "
import asyncio
from app.services.ingestion import IngestionService
asyncio.run(IngestionService().ingest_all())
"
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   RSS Feeds     │     │  Hacker News    │     │     Reddit      │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    Ingestion Layer      │
                    │   (Celery Workers)      │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    Processing Layer     │
                    │ • Content extraction    │
                    │ • Deduplication         │
                    │ • Embedding generation  │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   Intelligence Layer    │
                    │ • Relevance scoring     │
                    │ • Signal scoring        │
                    │ • Briefing generation   │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │     Delivery Layer      │
                    │ • REST API              │
                    │ • Email briefings       │
                    └─────────────────────────┘
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check |
| `/health/ready` | GET | Readiness check (DB + Redis) |
| `/health/metrics` | GET | Application metrics |
| `/api/v1/sources` | GET | List all sources |
| `/api/v1/sources` | POST | Add a new source |
| `/api/v1/feed` | GET | Get ranked signal feed |

## Configuration

Key environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | - |
| `REDIS_URL` | Redis connection string | - |
| `OPENAI_API_KEY` | OpenAI API key for embeddings | - |
| `ANTHROPIC_API_KEY` | Claude API key for briefings | - |
| `INGESTION_INTERVAL_MINUTES` | How often to fetch sources | 30 |
| `MAX_EMBEDDINGS_PER_HOUR` | Rate limit for embeddings | 1000 |

## Development Phases

- [x] **Phase 0**: Foundations (repo, DB, API skeleton)
- [ ] **Phase 1**: Collection layer (RSS, HN, Reddit ingestion)
- [ ] **Phase 2**: Cleaning layer (extraction, dedup)
- [ ] **Phase 3**: Intelligence layer (scoring, briefings)
- [ ] **Phase 4**: Delivery layer (frontend, email)
- [ ] **Phase 5**: Hardening and launch

## License

MIT
