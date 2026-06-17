# Architecture — Cladlygo Marketing Agent

> **Your daily effort: < 5 minutes.** The rest is fully automated.

This document is the single authoritative reference for the system's design, data flow, infrastructure choices, and internal decisions. For setup instructions, see the [README](../README.md).

---

## Contents

1. [System at a Glance](#1-system-at-a-glance)
2. [Stage 1 — Strategy Pipeline](#2-stage-1--strategy-pipeline)
3. [Stage 2 — Content Teams (Parallel)](#3-stage-2--content-teams-parallel)
4. [Stage 2.5 — Anti-Spam Guardrail](#4-stage-25--anti-spam-guardrail)
5. [Stage 3 — Image Generation & Approval](#5-stage-3--image-generation--approval)
6. [Stage 4 — Publishing & Durable Retry](#6-stage-4--publishing--durable-retry)
7. [Stage 5 — Engagement Tracking](#7-stage-5--engagement-tracking)
8. [Stage 6 — Self-Learning Reflector](#8-stage-6--self-learning-reflector)
9. [Infrastructure & Stack](#9-infrastructure--stack)
10. [Firestore Data Model](#10-firestore-data-model)
11. [HTTP API Reference](#11-http-api-reference)
12. [File Map](#12-file-map)
13. [Models & Cost](#13-models--cost)
14. [Architecture Decisions](#14-architecture-decisions)

---

## 1. System at a Glance

The entire system is triggered by a single Telegram message and runs without further human input until approval cards arrive on your phone.

```mermaid
flowchart TD
    classDef user      fill:#3B82F6,stroke:#1D4ED8,color:#fff,rx:12
    classDef infra     fill:#F59E0B,stroke:#B45309,color:#000
    classDef pipeline  fill:#8B5CF6,stroke:#5B21B6,color:#fff
    classDef stage     fill:#6366F1,stroke:#3730A3,color:#fff
    classDef storage   fill:#10B981,stroke:#047857,color:#fff
    classDef notify    fill:#EC4899,stroke:#9D174D,color:#fff
    classDef publish   fill:#06B6D4,stroke:#0E7490,color:#fff
    classDef learn     fill:#F97316,stroke:#C2410C,color:#fff

    YOU(["👤 You · Telegram"]):::user

    subgraph TRIGGER ["  🚀 Trigger Layer  "]
        direction LR
        TG["⚡ /telegram\nWebhook"]:::infra
        CT["☁️ Cloud Tasks\none-time"]:::infra
        CR["🏃 Cloud Run\ncladlygo-agent"]:::infra
    end

    subgraph PIPELINE ["  🔄 Campaign Pipeline  "]
        S1["📋 Stage 1\nStrategy"]:::stage
        S2["✍️ Stage 2\nContent Teams"]:::stage
        GR["🛡️ Stage 2.5\nAnti-Spam Gate"]:::stage
        IMG["🎨 Stage 3\nImage Generation"]:::stage
    end

    subgraph APPROVAL ["  📱 Approval  "]
        CARD["📲 Telegram Card\n✅ ✍️ 🖼 ❌"]:::notify
    end

    subgraph PUBLISH_LOOP ["  📤 Publish Loop  "]
        PUB["Buffer\nGraphQL"]:::publish
        MET["📊 Metrics\n+48h / +96h"]:::publish
    end

    subgraph LEARN ["  🧠 Self-Learning  "]
        REF["Reflector\nAgent"]:::learn
        RULES["📚 Learned Rules\nFirestore"]:::learn
    end

    YOU -->|"campaign: …"| TG
    TG --> CT --> CR --> S1
    S1 --> S2 --> GR --> IMG --> CARD

    CARD -->|"✅ Approve"| PUB
    CARD -->|"✍️ / 🖼 Regen"| S2
    CARD -->|"❌ Reject"| RULES

    PUB --> MET --> REF
    YOU -->|"reflect"| REF
    REF --> RULES
    RULES -->|"injected next run"| S1
```

---

## 2. Stage 1 — Strategy Pipeline

One `SequentialAgent` session. All three sub-agents share state through ADK's output keys — the research dossier flows directly into the campaign plan, and the campaign plan flows into the briefs.

```mermaid
flowchart LR
    classDef source  fill:#0EA5E9,stroke:#0369A1,color:#fff
    classDef agent   fill:#8B5CF6,stroke:#4C1D95,color:#fff
    classDef output  fill:#10B981,stroke:#047857,color:#fff

    SRC(["📂 Source Provider\nRSS · VectorDB · None"]):::source
    RULES(["📚 Learned Rules\nFirestore"]):::source

    RA["🔍 Research Agent\ngemini-2.5-flash\nresearch.py"]:::agent
    CA["🗺️ Campaign Strategist\ngemini-2.5-flash\ncampaign.py"]:::agent
    BA["📝 Brief Agent\ngemini-2.5-flash\ncampaign.py"]:::agent

    DOC["ResearchDossier\ntrends · signals · ranked topics"]:::output
    PLAN["Campaign Plan\nbig idea · narrative arc · hashtags"]:::output
    BRIEFS["Briefs\nN topics × 3 platforms"]:::output

    SRC --> RA
    RULES -->|"build_instruction()"| RA
    RA --> DOC --> CA --> PLAN --> BA --> BRIEFS
```

**What each agent produces:**

| Agent | Output | Key fields |
|---|---|---|
| Research | `ResearchDossier` | trend signals, audience values, do/avoid, ranked topics |
| Campaign Strategist | `CampaignPlan` | big idea, narrative arc, hashtag rotation, anti-spam guidance |
| Brief | `Brief` × (N×3) | hook, angle, key points, visual concept, eyebrow, headline, CTA |

---

## 3. Stage 2 — Content Teams (Parallel)

Each brief gets its own isolated `LoopAgent` running in its own `InMemoryRunner` session, fanned out via `asyncio.gather`. Isolation means one failing post cannot corrupt the others and avoids ADK state-key collisions.

```mermaid
flowchart TD
    classDef brief  fill:#0EA5E9,stroke:#0369A1,color:#fff
    classDef agent  fill:#8B5CF6,stroke:#4C1D95,color:#fff
    classDef critic fill:#EF4444,stroke:#991B1B,color:#fff
    classDef done   fill:#10B981,stroke:#047857,color:#fff

    BRIEFS(["📝 N Briefs"]):::brief

    BRIEFS -->|"asyncio.gather\none session per post"| CT1 & CT2 & CTN

    subgraph CT1 ["Content Team · Post 1"]
        CW1["✍️ Copywriter\nFlash"]:::agent
        AD1["🎨 Art Director\nFlash-Lite"]:::agent
        QC1{{"🔎 Quality Critic\nFlash\nscore 1–5"}}:::critic
        CW1 --> AD1 --> QC1
        QC1 -->|"score < 4\nfeedback injected"| CW1
    end

    subgraph CT2 ["Content Team · Post 2"]
        CW2["✍️ Copywriter"]:::agent
        AD2["🎨 Art Director"]:::agent
        QC2{{"🔎 Quality Critic"}}:::critic
        CW2 --> AD2 --> QC2
        QC2 -->|revise| CW2
    end

    subgraph CTN ["Content Team · Post N"]
        CWN["✍️ …"]:::agent
        ADN["🎨 …"]:::agent
        QCN{{"🔎 …"}}:::critic
        CWN --> ADN --> QCN
        QCN -->|revise| CWN
    end

    CT1 & CT2 & CTN --> DONE["✅ Refined Posts\ncaption + image prompt"]:::done
```

**Loop mechanics:**

| Step | Agent | Description |
|---|---|---|
| 1 | Copywriter | Writes the caption. On iterations 2+ reads critic feedback from state. |
| 2 | Art Director | Writes the image-generation prompt for the visual concept. |
| 3 | Quality Critic | Scores 1–5 against brief, brand voice, platform fit. Calls `exit_loop` when score ≥ `CRITIC_PASS_SCORE` (default 4). Uses plain-text output because it calls a tool (`output_schema` incompatible). |

Max iterations: `CRITIC_MAX_ITERATIONS` (default 3).

---

## 4. Stage 2.5 — Anti-Spam Guardrail

A two-stage gate applied to every post before image generation. Fails open on LLM errors (the deterministic check always runs).

```mermaid
flowchart LR
    classDef input  fill:#0EA5E9,stroke:#0369A1,color:#fff
    classDef det    fill:#F59E0B,stroke:#B45309,color:#000
    classDef llm    fill:#8B5CF6,stroke:#4C1D95,color:#fff
    classDef block  fill:#EF4444,stroke:#991B1B,color:#fff
    classDef pass   fill:#10B981,stroke:#047857,color:#fff
    classDef warn   fill:#EC4899,stroke:#9D174D,color:#fff

    POST(["📄 Refined Post"]):::input

    DET["⚡ Deterministic Check\n• spam-trigger phrases\n• hashtag count vs platform limit\n• link / CTA count\n• near-duplicate difflib check"]:::det

    LLM["🤖 LLM Tone Check\ngemini-2.5-flash-lite\nfails open on error"]:::llm

    REGEN["🔄 One Regeneration\nanti-spam instructions injected"]:::block

    RECHECK["⚡ Re-check"]:::det

    FLAG(["⚠️ Warning Flag\non Telegram card\nnever silent"]):::warn

    OK(["✅ Proceed to\nImage Generation"]):::pass

    POST --> DET
    DET -->|"✅ pass"| LLM
    DET -->|"❌ block"| REGEN --> RECHECK
    RECHECK -->|"✅ pass"| LLM
    RECHECK -->|"❌ still blocked"| FLAG
    LLM -->|"✅ ok"| OK
    LLM -->|"⚠️ flag"| FLAG
```

---

## 5. Stage 3 — Image Generation & Approval

`Gemini 2.5 Flash Image` renders the headline text directly onto the generated scene in a single API call. No external compositor or separate text-overlay service is needed.

```mermaid
flowchart LR
    classDef input   fill:#0EA5E9,stroke:#0369A1,color:#fff
    classDef gen     fill:#8B5CF6,stroke:#4C1D95,color:#fff
    classDef store   fill:#10B981,stroke:#047857,color:#fff
    classDef db      fill:#F59E0B,stroke:#B45309,color:#000
    classDef notify  fill:#EC4899,stroke:#9D174D,color:#fff
    classDef action  fill:#6366F1,stroke:#3730A3,color:#fff

    POST(["📄 Post\ncaption · image prompt · headline"]):::input

    GEN["🎨 Gemini 2.5 Flash Image\n'Nano Banana'\n1:1 card · headline baked in"]:::gen
    GCS["🪣 Cloud Storage\npublic image URL"]:::store
    FS["🔥 Firestore\nstatus: pending_approval"]:::db
    CARD["📲 Telegram Approval Card"]:::notify

    POST --> GEN --> GCS --> FS --> CARD

    CARD --> A1["✅ Approve\nnext open slot"]:::action
    CARD --> A2["✍️ Regen Text\nFlash rewrites caption"]:::action
    CARD --> A3["🖼 Regen Visual\nnew image generated"]:::action
    CARD --> A4["❌ Reject\nlog reason to Firestore"]:::action
```

**Approval slots** (configurable): 9 AM · 12 PM · 3 PM · 6 PM · 9 PM IST

| Button | Firestore update |
|---|---|
| ✅ Approve | `status → pending_publish`, `scheduled_at → next slot` |
| ✍️ Regen Text | Caption rewritten with current learned rules, card refreshed |
| 🖼 Regen Visual | New image generated, new card sent |
| ❌ Reject | `status → rejected`, `reason` logged to `rejections` collection |

---

## 6. Stage 4 — Publishing & Durable Retry

Publishing is just-in-time: a one-time Cloud Task fires at each post's scheduled slot. Buffer's `shareNow` mode publishes immediately across all connected platforms.

```mermaid
flowchart LR
    classDef trigger  fill:#F59E0B,stroke:#B45309,color:#000
    classDef pub      fill:#06B6D4,stroke:#0E7490,color:#fff
    classDef platform fill:#10B981,stroke:#047857,color:#fff
    classDef fail     fill:#EF4444,stroke:#991B1B,color:#fff
    classDef retry    fill:#F97316,stroke:#C2410C,color:#fff
    classDef alert    fill:#EC4899,stroke:#9D174D,color:#fff

    SLOT(["⏰ Publish Slot\none-time Cloud Task"]):::trigger

    PUB["📤 POST /run/publish\nbuffer_post_id saved"]:::pub

    IG(["📸 Instagram"]):::platform
    PI(["📌 Pinterest"]):::platform
    X(["𝕏 X · Twitter"]):::platform

    RETRY["🔄 Durable Retry\nretry_at = now+15min\none-time Cloud Task"]:::retry
    RETRY2["🔄 POST /run/retry\none more attempt"]:::retry
    ALERT(["🚨 Telegram Alert\nstatus: failed"]):::alert

    SLOT --> PUB
    PUB -->|"Buffer GraphQL\nshareNow"| IG & PI & X
    PUB -->|"❌ failure"| RETRY --> RETRY2
    RETRY2 -->|"❌ still fails"| ALERT
```

---

## 7. Stage 5 — Engagement Tracking

Buffer normalises engagement metrics across all three platforms. Two snapshots are taken per campaign because Buffer refreshes ~once daily and very fresh posts return empty metrics.

```mermaid
flowchart LR
    classDef trigger  fill:#F59E0B,stroke:#B45309,color:#000
    classDef fetch    fill:#06B6D4,stroke:#0E7490,color:#fff
    classDef norm     fill:#8B5CF6,stroke:#4C1D95,color:#fff
    classDef store    fill:#10B981,stroke:#047857,color:#fff
    classDef digest   fill:#EC4899,stroke:#9D174D,color:#fff

    CAMP(["✅ Campaign Published"]):::trigger

    M1["📊 POST /run/metrics\n+48h Cloud Task"]:::trigger
    M2["📊 POST /run/metrics\n+96h Cloud Task"]:::trigger

    FETCH["🔌 Buffer GraphQL\nfetch_metrics(buffer_post_id)\npost.metrics + metricsUpdatedAt"]:::fetch

    NORM["📐 Normalise\nreactions · comments · shares\nreposts · impressions · reach\nsaves · engagementRate"]:::norm

    SAVE["💾 save_metrics()\nupdates post doc\nappends post_metrics row"]:::store

    DIGEST["📋 Daily Monitor Digest\n📊 published / failed counts\n🏆 top post this week"]:::digest

    CAMP --> M1 & M2
    M1 & M2 --> FETCH --> NORM --> SAVE --> DIGEST
```

---

## 8. Stage 6 — Self-Learning Reflector

The reflector is an autonomous `LlmAgent` — it decides which tools to call; you don't define the workflow. Guardrails live inside the `write_rule` tool, not in the prompt, so a chatty model cannot bypass them.

```mermaid
flowchart TD
    classDef user    fill:#3B82F6,stroke:#1D4ED8,color:#fff
    classDef trigger fill:#F59E0B,stroke:#B45309,color:#000
    classDef agent   fill:#8B5CF6,stroke:#4C1D95,color:#fff
    classDef data    fill:#0EA5E9,stroke:#0369A1,color:#fff
    classDef guard   fill:#EF4444,stroke:#991B1B,color:#fff
    classDef store   fill:#10B981,stroke:#047857,color:#fff
    classDef out     fill:#EC4899,stroke:#9D174D,color:#fff

    YOU(["👤 You: 'reflect'"]):::user
    CT["☁️ one-time Cloud Task"]:::trigger
    AG["🧠 Reflector LlmAgent\ngemini-2.5-flash\n3 function tools"]:::agent

    DATA["📂 read_feedback()\nFirestore aggregate:\n• rejections + reasons\n• regen counts\n• publish outcomes\n• engagement performance\n• active rules + ids"]:::data

    GUARD["🔒 write_rule() guardrails\n• role ∈ topic/brief/caption/image\n• evidence length check\n• max 20 rules per role\n• difflib dedup ≥ 0.85"]:::guard

    WRITE["📝 add_rule()\nlearned_rules Firestore"]:::store
    RETIRE["🗑️ retire_rule(rule_id)\nactive: false"]:::store
    LOG["🗂️ log_prompt_version()\naudit trail"]:::store
    DIGEST["📲 Telegram Digest\n🧠 summary + new rules"]:::out
    INJECT["🔄 Next Pipeline Run\nbuild_instruction(role, rules)\nrule spliced into agent instruction"]:::out

    YOU --> CT --> AG
    AG -->|"1"| DATA
    AG -->|"2"| GUARD --> WRITE
    AG -->|"3"| RETIRE
    AG -->|"after all tools"| LOG --> DIGEST
    WRITE --> INJECT
```

**Human override commands:**

| Telegram message | What happens |
|---|---|
| `reflect` | Triggers the self-learning reflector |
| `rules` | Lists all active learned rules with IDs |
| `forget <id>` | Retires a specific rule immediately |

---

## 9. Infrastructure & Stack

```mermaid
flowchart LR
    classDef ext   fill:#3B82F6,stroke:#1D4ED8,color:#fff
    classDef gcp   fill:#10B981,stroke:#047857,color:#fff
    classDef ai    fill:#8B5CF6,stroke:#4C1D95,color:#fff
    classDef app   fill:#F59E0B,stroke:#B45309,color:#000

    subgraph GCP ["  Google Cloud Platform  "]
        CR["☁️ Cloud Run\nscale-to-zero compute"]:::gcp
        CT["⏱️ Cloud Tasks\none-time scheduling"]:::gcp
        FS["🔥 Firestore\nschema-free database"]:::gcp
        GCS["🪣 Cloud Storage\nimage hosting"]:::gcp
        VA["🤖 Vertex AI\nGemini API"]:::ai
    end

    subgraph EXT ["  External Services  "]
        TG["📲 Telegram Bot\napproval UI"]:::ext
        BUF["📤 Buffer\npublishing + metrics"]:::ext
        PG["🐘 Postgres + pgvector\noptional wardrobe DB"]:::ext
    end

    subgraph APP ["  Application  "]
        FA["⚡ FastAPI\nserver.py"]:::app
        ADK["🧩 Google ADK 2.x\nagent runtime"]:::app
    end

    FA --> CT & FS & GCS & VA & TG & BUF & PG
    ADK --> VA
```

| Layer | Technology | Reason |
|---|---|---|
| Agent runtime | Google ADK 2.x | Sequential, Loop, and Parallel agent primitives |
| LLM | Gemini 2.5 Flash / Flash-Lite / Flash Image | Single ecosystem; lowest per-token cost at each task tier |
| Image generation | Gemini 2.5 Flash Image ("Nano Banana") | Text-on-image in one call, no compositor needed |
| Database | Firestore | Schema-free, serverless, zero-maintenance |
| Object storage | Cloud Storage | Public-URL image hosting for Buffer |
| Compute | Cloud Run | Scale-to-zero, one-command deploy |
| Scheduling | Cloud Tasks (one-time per campaign) | No wasted recurring runs |
| Approval UI | Telegram bot | No app to install, instant mobile delivery |
| Publishing | Buffer GraphQL API | Single token for Instagram + Pinterest + X |
| Engagement | Buffer metrics API | Normalised across platforms, no extra OAuth |

**Monthly cost: ~$13–15** — image generation dominates (~$10.50); all text agents together are ~$3–5.

---

## 10. Firestore Data Model

```mermaid
erDiagram
    posts {
        string id PK
        string campaign_id FK
        string platform
        string caption
        string image_url
        string buffer_post_id
        string status
        timestamp scheduled_at
        timestamp published_at
        map metrics
    }

    campaigns {
        string id PK
        string brief
        string big_idea
        string narrative_arc
        timestamp created_at
    }

    rejections {
        string id PK
        string post_id FK
        string reason
        timestamp created_at
    }

    publish_outcomes {
        string id PK
        string post_id FK
        bool success
        string error
        timestamp attempted_at
    }

    post_metrics {
        string id PK
        string post_id FK
        int reactions
        int comments
        int shares
        int impressions
        int reach
        int saves
        float engagementRate
        timestamp snapshot_at
    }

    learned_rules {
        string id PK
        string role
        string rule
        string evidence
        bool active
        timestamp created_at
    }

    prompt_versions {
        string id PK
        string role
        string full_instruction
        timestamp created_at
    }

    telegram_media_groups {
        string media_group_id PK
        list photo_file_ids
        timestamp last_update
    }

    posts }o--|| campaigns : "belongs to"
    rejections }o--|| posts : "references"
    publish_outcomes }o--|| posts : "references"
    post_metrics }o--|| posts : "references"
```

| Collection | Written by | Read by | Purpose |
|---|---|---|---|
| `posts` | pipeline, approval handler | publisher, reflector | Post queue + approval state machine |
| `campaigns` | orchestrator | — | Campaign plan archive |
| `rejections` | approval handler | reflector | Human rejection reasons |
| `publish_outcomes` | publisher, retry handler | reflector, monitor | Publish success/failure log |
| `post_metrics` | metrics sweep | reflector, monitor | Buffer engagement time-series |
| `learned_rules` | reflector | all pipeline agents | Active prompt guidelines |
| `prompt_versions` | reflector | audit | Audit trail of every reflection |
| `telegram_media_groups` | approval handler | campaign intake | Multi-image debounce buffer |

---

## 11. HTTP API Reference

All `/run/*` endpoints require `X-Scheduler-Token: <SCHEDULER_SECRET>` in the request header.

| Endpoint | Trigger | Action |
|---|---|---|
| `GET /` | Cloud Run health probe | Returns `{"status": "ok"}` |
| `POST /telegram` | Telegram webhook | Routes updates: campaign intake · button taps · `reflect` / `rules` / `forget` commands |
| `POST /run/campaign` | Cloud Task (per campaign) | Runs the full content pipeline for one campaign brief |
| `POST /run/publish` | Cloud Task (per slot) | Publishes all approved posts whose scheduled slot has arrived |
| `POST /run/retry` | Cloud Task (per failure) | One durable retry for a failed publish (+15 minutes) |
| `POST /run/monitor` | Cloud Task (per campaign, +24h) | Sends a Telegram digest of publish outcomes |
| `POST /run/metrics` | Cloud Task (per campaign, +48h / +96h) | Pulls Buffer engagement metrics for recently published posts |
| `POST /run/reflect` | Cloud Task (on `reflect` command) | Runs the self-learning reflector agent |

---

## 12. File Map

```
server.py                           ← FastAPI entry point (all HTTP endpoints)
│
marketing_agent/
├── config.py                       ← All config, env vars, and defaults
├── prompts.py                      ← Base prompts + build_instruction()
├── schemas.py                      ← Pydantic models for all agent I/O
├── orchestrator.py                 ← Department pipeline (Phase 2, default)
├── pipeline.py                     ← Linear pipeline baseline (Phase 1)
├── guardrails.py                   ← Anti-spam gate (deterministic + LLM)
├── approval.py                     ← Telegram webhook handler + commands
├── publish_runner.py               ← JIT publisher + durable retry
├── sub_agents.py                   ← Phase 1 agent factories
│
├── agents/
│   ├── research.py                 ← Research lead  →  ResearchDossier
│   ├── campaign.py                 ← Campaign strategist + brief agent
│   ├── content_team.py             ← Per-post LoopAgent (copy → art → critic)
│   ├── critic.py                   ← Quality critic (evaluator-optimizer)
│   └── monitor.py                  ← Publish outcomes + engagement digest
│
├── tools/
│   ├── firestore_store.py          ← All Firestore reads/writes
│   ├── publisher.py                ← Buffer GraphQL: publish + fetch_metrics
│   ├── imagen.py                   ← Gemini Flash Image card generation
│   ├── telegram.py                 ← Telegram messaging helpers
│   ├── tasks.py                    ← Cloud Tasks enqueueing
│   ├── gcs.py                      ← Cloud Storage upload
│   ├── llm.py                      ← One-shot Gemini text calls
│   └── sources.py                  ← Source provider dispatch
│
└── sources/
    ├── base.py                     ← SourceProvider abstract contract
    ├── rss.py                      ← RSS/Atom feed reader (default)
    ├── vectordb.py                 ← Postgres + pgvector retrieval
    └── none.py                     ← No-op (brand context only)
│
docs/
└── ARCHITECTURE.md                 ← This file
│
scripts/
├── test_pipeline.py                ← Test runner (sources/reasoning/prompts/reflect/full)
└── discover_wardrobe_db.py         ← Inspect wardrobe DB schema + embedding dimension
│
infra/
└── setup.sh                        ← GCP resource provisioning (called by go.sh)
│
go.sh                               ← First-time full setup (one command)
deploy.sh                           ← Redeploy after code changes
```

---

## 13. Models & Cost

| Model | Used for | Approx. cost |
|---|---|---|
| `gemini-2.5-flash-lite` | Topic ranking, anti-spam tone check, image prompt writing | ~$0.10 / M tokens |
| `gemini-2.5-flash` | Research, campaign planning, copywriting, critic loop, reflection | ~$0.30 / M input · $2.50 / M output |
| `gemini-2.5-flash-image` | Branded card generation (~270 images / month) | ~$0.039 / image |

**Monthly total: ~$13–15**

```
Image generation  ████████████████████████░░░  ~$10.50  (70%)
Text agents       ████████░░░░░░░░░░░░░░░░░░░  ~$3–5    (25%)
Infrastructure    ██░░░░░░░░░░░░░░░░░░░░░░░░░  ~$0–1    (5%)
```

---

## 14. Architecture Decisions

### Google ADK over LangChain / LlamaIndex

ADK's `SequentialAgent`, `LoopAgent`, and `InMemoryRunner` give first-class session state and tool execution without boilerplate. The evaluator-optimizer critic loop (`LoopAgent` + `exit_loop` tool) maps directly to an ADK primitive. LangChain was evaluated but the ADK abstractions aligned better with the multi-stage, multi-role structure needed here.

### Gemini exclusively (no cross-cloud)

Everything runs in one Google ecosystem: Vertex AI → Cloud Run → Firestore → Cloud Tasks → Cloud Storage. No cross-cloud authentication, no extra billing accounts. Flash-Lite for cheap structured ranking; Flash for brand copywriting and reflection; Flash Image ("Nano Banana") bakes the headline directly onto the generated image — replacing two old vendors (Replicate + HCTI) with one API call.

### Cloud Tasks (one-time) over Cloud Scheduler (recurring crons)

Campaigns are Telegram-initiated, not time-scheduled. Each campaign enqueues its own one-time downstream tasks (publish sweeps, monitor, metrics sweeps). The service scales to zero between campaigns, there are no wasted runs when nothing is queued, and scheduling is deterministic per campaign rather than global.

### Buffer over native platform APIs

Buffer brokers all three platforms (Instagram, Pinterest, X) with a single bearer token. X's native API has no free tier as of 2026 ($0.005/read); Instagram and Pinterest both require separate OAuth apps. Buffer normalises the GraphQL publish + engagement metrics interfaces across all three, so one code path handles all platforms.

### Firestore over Postgres / Supabase

Schema-free documents match the varied shapes of posts, campaigns, rules, and time-series metrics without migrations. The serverless scaling and zero-maintenance story fits a system running on Cloud Run (scales to zero). Real-time capabilities aren't used here but cost nothing extra.

### Isolated sessions per post (Stage 2)

An ADK agent can only have one parent. Sharing one session for parallel fan-out causes state-key collisions. One `InMemoryRunner` per post means one post failing doesn't kill the others, and each critic loop runs against its own brief's context only.

### Guardrails inside tools, not prompts

The `write_rule` guardrails (role validation, evidence length, max rules, dedup) live inside the tool function, not in the system prompt. A chatty or misaligned model cannot bypass them by rephrasing. The same principle applies to `build_instruction()` — rules are spliced in at build time, keeping the base prompt auditable and version-controlled.
