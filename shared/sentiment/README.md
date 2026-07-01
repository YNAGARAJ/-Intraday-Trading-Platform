# M10 — Sentiment & News Agent

Pre-market sentiment aggregator for NSE and ASX. Scrapes RSS feeds, scores
headlines via Groq LLM (batched, max 20 per call), caches scores using
GPTCache semantic dedup (cosine similarity ≥ 0.95 → cache hit), and fetches
India VIX, FII/DII flows, and put-call ratio.

## Public API

```python
from shared.sentiment.agent import SentimentAgent
from shared.sentiment.models import MarketSentiment

agent = SentimentAgent(
    model="groq/llama-3.1-8b-instant",  # default
    api_key=None,                         # uses GROQ_API_KEY env var
    redis_client=redis_client,            # None → in-memory cache
)
result: MarketSentiment = agent.run("NSE")

print(result.aggregate_score)   # confidence-weighted mean, [-1.0, 1.0]
print(result.cache_hit_rate)    # fraction served from cache
print(result.total_cost_usd)    # estimated LLM spend this run
```

## VERIFY scenario

```python
headlines = [f"Headline {i}" for i in range(20)]

# First run — all misses, LLM called
r1 = agent.run("NSE", custom_headlines=headlines)
assert r1.cache_misses == 20 and r1.cache_hits == 0

# Second run — all hits, LLM not called
r2 = agent.run("NSE", custom_headlines=headlines)
assert r2.cache_hits == 20 and r2.total_cost_usd == 0.0
```

## CLI

```bash
# Score NSE headlines (uses Redis cache if REDIS_URL set)
APP_ID=test python -m shared.sentiment --exchange NSE

# Score custom headlines without cache
APP_ID=test python -m shared.sentiment \
    --exchange NSE --no-cache \
    --headlines "NIFTY rises 1%" "RBI holds rates"

# Print daily LLM cost total
APP_ID=test python -m shared.sentiment --cost-report

# JSON output
APP_ID=test python -m shared.sentiment --exchange NSE --output-json
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | For live scoring | — | Groq API key |
| `REDIS_URL` | No | — | Redis URL; skips cache if unset |
| `APP_ID` | Yes (Settings) | — | Application identifier |

## Data flow

```
RSS feeds (ET, MC, NSE, ASX)
        ↓
fetch_all_feeds()           ← deduplicated, capped at 100 headlines
        ↓
SentimentCache.get()        ← GPTCache cosine similarity (threshold 0.95)
  hit  → SentimentScore (from_cache=True, tokens=0)
  miss → score_headlines_batch()  ← LiteLLM batched Groq 8B (max 20/call)
             ↓
         SentimentCache.put()     ← store embedding + score in Redis
             ↓
CostTracker.record()        ← Redis incrbyfloat, warns at $1/day
        ↓
fetch_india_vix()           ← NSE API, fail-open
fetch_fii_dii()             ← NSE API, fail-open
        ↓
MarketSentiment             ← consumed by M11 Gate 8
```

## Design decisions

- **GPTCache via embedding only** (not LLM adapter): avoids complex
  initialization; uses `gptcache.embedding.Onnx` (all-MiniLM-L6-v2, 384-dim)
  with custom NumPy cosine similarity and Redis list storage. See ADR-016.
- **LiteLLM at module level**: `import litellm` is module-level (not deferred)
  to enable `@patch("shared.sentiment.scorer.litellm")` in unit tests. The
  mypy config skips litellm's inline stubs via `follow_imports = "skip"` to
  avoid an upstream mypy AssertionError.
- **Fail-open**: all market indicator scrapers (`fetch_india_vix`,
  `fetch_fii_dii`) return `None` on failure; the agent proceeds with
  `aggregate_score` from headlines alone.
- **SentScore = 0.0 until M10 wired to M11**: M09 reserved `β_Sent = 0.10`
  in the alpha scoring weights; M11 reads `MarketSentiment.aggregate_score`.
