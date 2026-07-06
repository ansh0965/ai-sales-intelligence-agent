# Deployment Guide

Two deliverables: push the code to GitHub, then deploy the Gradio UI to a
Hugging Face Space (the "deployability" competition requirement, shown live
in the video).

---

## 1. GitHub

Already wired to `https://github.com/ansh0965/ai-sales-intelligence-agent.git`.

Pre-push safety check — this must print **nothing**:

```bash
git status --porcelain | grep -E "\.env$|credentials|\.history"
```

`.env`, `credentials.json`, `*credentials*.json`, `.history/`, and
`__pycache__/` are all covered by `.gitignore`. Never commit them; the
Gemini/Serper keys and the service-account JSON exist only in `.env` +
`credentials.json` locally and as Space secrets in production.

---

## 2. Hugging Face Space (Gradio)

### Create the Space

1. huggingface.co → **New Space**
2. Name: `ai-sales-intelligence-agent` · SDK: **Gradio** · Hardware: CPU basic (free)

### Space configuration

Hugging Face reads the Space's `README.md` YAML front matter. After cloning
the Space repo (or in the web editor), make its `README.md` start with:

```yaml
---
title: AI Sales Intelligence Agent
emoji: 🤖
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: "6.19.0"
app_file: ui/app.py
pinned: false
---
```

(Keep the rest of the project README below the front matter — HF renders it
as the Space description.)

### Secrets (Space → Settings → Variables and secrets)

| Secret | Value |
|--------|-------|
| `GEMINI_API_KEY` | your Tier-1 key |
| `SERPER_API_KEY` | your Serper key |
| `GEMINI_MAX_CALLS_PER_MINUTE` | `30` |

Do **not** upload `credentials.json` — without `GOOGLE_SHEETS_ID` the CRM
step logs "skipped" gracefully, which is fine for the public demo (and keeps
the service account private). If you want CRM live in the demo, run the UI
locally during the video instead.

### Push the code to the Space

```bash
git remote add space https://huggingface.co/spaces/<your-username>/ai-sales-intelligence-agent
git push space main
```

(Authenticate with a HF access token when prompted; or upload files via the
web UI.)

### Verify

- Space builds (watch the build logs), then open the app URL
- Run "Stripe" end-to-end; confirm the activity log streams and the three
  tabs populate
- Expect CRM status "skipped (no Sheet ID)" unless you configured Sheets

### Troubleshooting

- **Build fails on gradio version** — make sure `sdk_version` in the Space
  README matches a released Gradio 6.x, and `requirements.txt` says
  `gradio>=6.0`
- **429 errors on the Space** — the key added as a secret is a free-tier
  key; use the billing-project key and keep `GEMINI_MAX_CALLS_PER_MINUTE`
  as a safety net
- **App starts but pipeline errors immediately** — a secret name is
  misspelled; names must match `.env.example` exactly
