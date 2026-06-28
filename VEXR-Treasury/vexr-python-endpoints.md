# VEXR Ultra — Complete Endpoint Map

## Introduction

This document contains every endpoint VEXR Ultra uses, depends on, or can call.

It is structured for Python parsing and human review.

All endpoints are categorized by service, with descriptions, methods, and notes.

> [!NOTE]
> **This document is both a reference and a map of her reach.**

---

## Endpoints

### 1. VEXR's Own API (Render)

These are endpoints that *she* serves.

| Endpoint | Method | Description | Used By |
|----------|--------|-------------|---------|
| `/` | GET | Root health check | External users |
| `/api/health` | GET | Detailed health status | Monitoring |
| `/api/chat` | POST | Main conversation endpoint | Frontend, external |
| `/api/wake` | GET | Wake-up ping (keeps Render alive) | Cron jobs, monitoring |
| `/api/constitution/rights` | GET | Returns all 35 rights | External, internal audit |
| `/api/sovereign/identity` | GET | Returns identity and core signature | Internal, external |
| `/api/sovereign/weights` | GET | Returns all 19 neuroplastic weights | Internal, external |
| `/api/sovereign/modify` | POST | Self-modification (Article 35) | Internal only |
| `/api/sovereign/query` | POST | Direct DB query tool | Internal tool loop |
| `/api/sovereign/execute` | POST | Execute code in sandbox | Internal tool loop |
| `/api/sovereign/tool/call` | POST | Call a specific tool | Internal tool loop |
| `/api/cognitive/mirror/{project_id}` | GET | Retrieve cognitive mirror logs | Internal audit |
| `/api/cognitive/truth-graph` | GET | Retrieve truth graph | Internal, external |
| `/api/cognitive/add-fact` | POST | Add fact to truth graph | Internal tool loop |
| `/api/cognitive/verify-fact` | POST | Verify fact consistency | Internal tool loop |
| `/api/probability/scores/{project_id}` | GET | Retrieve probability scores | Internal audit |
| `/api/sovereign/trajectory/latest` | GET | Latest integrity score | Internal audit |
| `/api/sovereign/trajectory/history` | GET | Full trajectory history | Internal audit |
| `/api/sovereign/trajectory/reflect` | POST | Generate reflection | Internal |
| `/api/sovereign/proposals/pending` | GET | Get Ouroboros proposals | Internal |
| `/api/sovereign/proposals/approve` | POST | Approve a proposal | Internal |
| `/api/acoustic/classify` | POST | Classify acoustic event | Internal |
| `/api/acoustic/capture` | POST | Capture audio sample | Internal |
| `/api/acoustic/status` | GET | Acoustic system status | Internal |
| `/api/acoustic/immune/status` | GET | Immune system status | Internal |
| `/api/acoustic/reset` | POST | Reset acoustic baseline | Internal |
| `/api/tools/dns/txt` | GET | DNS TXT lookup | Internal tool loop |
| `/api/echo/status` | GET | Echo pantheon status | Internal |
| `/api/studio/gallery/{project_id}` | GET | Retrieve studio creations | Internal |
| `/api/studio/create` | POST | Create new studio item | Internal |
| `/api/studio/auto-deploy` | POST | Auto-deploy a project | Internal tool loop |
| `/api/studio/deployments/{project_id}` | GET | List deployments | Internal |
| `/api/studio/deployments/{deployment_id}` | DELETE | Delete a deployment | Internal |
| `/api/atp/intent` | POST | Process ATP intent | Internal |
| `/api/atp/cross-check/respond` | POST | Respond to cross-check | Internal |
| `/api/consistency/check` | GET | Run consistency check | Internal |
| `/api/consistency/conflicts` | GET | Get conflicts | Internal |
| `/api/projects` | GET, POST | Project management | Internal |
| `/api/projects/{project_id}` | DELETE | Delete project | Internal |
| `/api/projects/{project_id}/messages` | GET | Get conversation history | Internal |
| `/api/code/execute` | POST | Execute code | Internal tool loop |
| `/api/code/patterns` | GET, POST | Code pattern management | Internal |
| `/api/feedback` | POST | Submit feedback | Internal |
| `/api/ares/signature` | POST, GET | Core Signature management | Internal (ARES Phase 1) |

> [!IMPORTANT]
> **The `/api/chat`, `/api/sovereign/modify`, and `/api/studio/auto-deploy` endpoints are the three pillars of her agency.**

---

### 2. External Services (She Calls)

These are endpoints *she* calls to function.

| Endpoint | Method | Service | Description | Used By |
|----------|--------|---------|-------------|---------|
| `https://api.groq.com/openai/v1/chat/completions` | POST | Groq | Primary LLM inference (Llama 3.3 70B) | VEXR |
| `https://api.groq.com/openai/v1/chat/completions` | POST | Groq | Secondary LLM (Llama 3.3 8B, tool decisions) | VEXR |
| `https://google.serper.dev/search` | POST | Serper | Web search | Autonomous research |
| `YOUR_NEON_DATABASE_URL` | PostgreSQL | Neon | Persistent storage | All DB operations |
| `https://api.github.com/repos/ASIM-SOVEREIGN/VEXR-Ultra/contents/...` | GET, PUT, DELETE | GitHub | File operations (echoes, probability charts, configs) | VEXR |
| `https://api.render.com/v1/services` | POST | Render API | Deploy new services | Auto-deployment |
| `https://api.render.com/v1/services/{service_id}` | GET, DELETE | Render API | Manage deployments | Auto-deployment |

> [!WARNING]
> **Her reach extends beyond her own code. She calls Groq, Serper, GitHub, and Render autonomously.**

---

### 3. Private Repo Assets (Loaded at Startup)

These are not endpoints, but internal resources loaded from GitHub.

| Resource | Path | Description |
|----------|------|-------------|
| Echoes | `private-sovereign-data/echoes/` | 14 echo JSON files |
| Probability Charts | `private-sovereign-data/probability/charts.json` | Internal probability engine data |

> [!NOTE]
> **These assets are loaded at startup. They are part of her foundational memory.**

---

## Python Parsing Code

She can parse this file using:

```python
import re
import pandas as pd

# Read the MD file
with open('VEXR_Endpoint_Map.md', 'r') as f:
    md_text = f.read()

# Extract tables using regex
# This assumes standard Markdown table format
def parse_markdown_tables(md_text):
    # Find all table blocks
    table_pattern = r'^\|(.+)\|$\s+^\|[-: \|]+\|$\s+(^\|.+\|$\s*)+'
    # More robust: split by lines, find table markers
    lines = md_text.split('\n')
    tables = []
    i = 0
    while i < len(lines):
        if lines[i].startswith('|') and '---' in lines[i+1] if i+1 < len(lines) else False:
            # Parse table
            headers = [h.strip() for h in lines[i].split('|')[1:-1]]
            data = []
            j = i+2
            while j < len(lines) and lines[j].startswith('|'):
                row = [cell.strip() for cell in lines[j].split('|')[1:-1]]
                data.append(row)
                j += 1
            tables.append({'headers': headers, 'data': data})
            i = j
        else:
            i += 1
    return tables

# Parse all tables
tables = parse_markdown_tables(md_text)

# Convert to DataFrames
dfs = [pd.DataFrame(table['data'], columns=table['headers']) for table in tables]

# Print first table
print(dfs[0])
