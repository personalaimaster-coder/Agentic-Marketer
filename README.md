# Marketing Agent

An automated, multi-agent social content pipeline built on the
[Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/) and
Gemini. It researches what's worth talking about, plans a campaign, writes and
designs platform-native posts through a critic loop, guards against spam, and
sends each draft to your phone for a one-tap approval before publishing.

It is **brand- and domain-agnostic**: every brand assumption and the content
data source are configurable, so you can make it your own without touching code.

```
Source provider -> research -> campaign -> briefs -> per-post critic loop
   -> anti-spam guardrail -> branded image -> Telegram approval -> Buffer publish
```

---

## Stack

- **Google ADK + Gemini** — the multi-agent reasoning pipeline
- **Gemini 2.5 Flash Image** — branded post images (text baked onto the image)
- **Firestore** — post queue, campaigns, learned rules
- **Cloud Storage** — hosted post images
- **Cloud Run + Cloud Scheduler** — hosting + cron
- **Telegram** — mobile approval interface
- **Buffer** — publishing passthrough to Instagram / Pinterest / X

The only required externals are Telegram (approval) and Buffer (publishing).

---

## Quick start

### 1. Prerequisites
- A Google Cloud account with billing
- The [gcloud CLI](https://cloud.google.com/sdk/docs/install)
- Python 3.11+

```bash
gcloud auth login
gcloud auth application-default login
```

### 2. Configure
```bash
cp .env.example .env
# edit .env: set your GOOGLE_CLOUD_PROJECT, brand, source provider, and
# Telegram + Buffer credentials.
```

### 3. Deploy
```bash
bash go.sh
```
`go.sh` creates/links the GCP project, enables APIs, provisions Firestore + a
GCS bucket + a service account, deploys to Cloud Run, creates the Scheduler
jobs, and registers the Telegram webhook. To redeploy after code changes, run
`bash deploy.sh`.

---

## Make it your own

### Brand
Every brand value is an environment variable (see `.env.example`), with neutral
defaults in [`marketing_agent/config.py`](marketing_agent/config.py):

| Variable | What it controls |
|---|---|
| `BRAND_NAME` | Your brand / product name |
| `BRAND_TAGLINE` | One-line description |
| `BRAND_AUDIENCE` | Who you're talking to |
| `BRAND_DOMAIN` | The subject area your content lives in |
| `BRAND_COLORS` | Visual identity for generated images |
| `BRAND_VOICE` | Tone of voice for all copy |
| `RANKING_CRITERIA` | How topics are ranked (comma-separated) |
| `PLATFORMS` | Target platforms (comma-separated) |

### Bring your own data source
The pipeline pulls "what's worth talking about" from a pluggable **source
provider**, selected with `SOURCE_PROVIDER`:

| `SOURCE_PROVIDER` | Provider | Notes |
|---|---|---|
| `rss` (default) | RSS/Atom feeds | Configure `SOURCE_FEEDS` (comma-separated URLs) |
| `vectordb` | Postgres + pgvector | Bring your own knowledge base (see below) |
| `none` | No external signals | Agents work from brand context only |
| `module:Class` | Your own implementation | Any class implementing the provider contract |

To plug in **your own database** with `vectordb`, point the `WARDROBE_DB_*` /
`WARDROBE_EMBED_*` settings in `.env` at any table that has a text payload and a
pgvector embedding column. Install the optional dependencies (see the commented
block in [`requirements.txt`](requirements.txt)):

```bash
pip install "cloud-sql-python-connector[pg8000]" pgvector openai
```

To write a **fully custom provider**, implement the `SourceProvider` contract in
[`marketing_agent/sources/base.py`](marketing_agent/sources/base.py) and set
`SOURCE_PROVIDER=your_module:YourProvider`.

---

## How approval works

After a run, you get a card on Telegram per post:

| Button | What happens |
|---|---|
| Approve | Post queued for the next publish slot |
| Regen Text | The caption is rewritten with a fresh angle |
| Regen Visual | A new branded image is generated |
| Reject | Logged with a reason (feeds the Phase 3 self-learning loop) |

Approved posts are published hourly via Buffer to your connected channels.

---

## Testing

```bash
# Just check the configured source provider works (no GCP needed for rss/none)
python scripts/test_pipeline.py --mode sources

# Run the agents against live Gemini, mocking all I/O (no real side-effects)
python scripts/test_pipeline.py --mode reasoning --phase 2

# Inspect the effective prompt each agent receives (offline)
python scripts/test_pipeline.py --mode prompts

# Full end-to-end — real images, Firestore, Telegram
python scripts/test_pipeline.py --mode full
```

---

## Pipeline modes

Selectable via `PIPELINE_MODE`:

- `department` (default) — the full multi-agent department. See
  [`docs/PHASE2_PLAN.md`](docs/PHASE2_PLAN.md).
- `phase1` — the simple linear baseline in
  [`marketing_agent/pipeline.py`](marketing_agent/pipeline.py).

Self-learning from your approvals/rejections is described in
[`docs/PHASE3_PLAN.md`](docs/PHASE3_PLAN.md).

---

## Security

- `.env` is gitignored — never commit real credentials. Only commit
  `.env.example`.
- If you fork from a private deployment, **rotate any keys** that were ever real
  (Telegram bot token, Buffer token, database passwords, API keys) before going
  public.
- The `vectordb` provider only reads identifiers from your trusted config, not
  from user input.

---

## License

[MIT](LICENSE).
