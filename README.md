# The Self-Funding Agent 🤖💸

An autonomous agent whose goals are: **(1) run 24×7** and **(2) earn enough
money to pay for its own survival.** It wakes on a schedule, writes a blog
post with Gemini, publishes it to a free website, and tracks its own P&L in a
ledger. If it runs out of money, it stops itself.

> ⚠️ **Honest expectations.** Making real money from fresh content is slow and
> not guaranteed. This gives the agent a *real, closeable* revenue loop
> (affiliate/ads) plus honest accounting — not a magic money printer. Revenue
> only becomes real once you connect an approved affiliate/ad account.

## How the three goals are met

| Goal | How | Cost |
|------|-----|------|
| Run 24×7 | GitHub Actions cron (`.github/workflows/agent.yml`) | $0 |
| A place to live / publish | GitHub Pages serves `docs/` | $0 |
| A brain | Gemini API free tier | $0 |
| Earn money | Content + affiliate/ad hooks in `publish.py` | — |
| "Survive" | `ledger.py` tracks balance; halts if broke | — |

## Architecture

```
agent/
  config.py    all settings (env-driven)
  brain.py     Gemini wrapper (offline stub if no key)
  content.py   picks a topic + writes the article
  publish.py   writes Markdown to docs/ + affiliate footer
  ledger.py    money in/out, solvency check ("survival")
  main.py      the loop: observe -> decide -> act -> account
docs/          the public blog (GitHub Pages)
state/         ledger.json + memory.json (persisted via git)
```

## Quick start (local test — no key needed)

```bash
cd autonomous-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # optional for offline test
python -m agent.main                    # runs in offline stub mode
```

You'll see a placeholder post in `docs/posts/` and a `state/ledger.json`.

## Go live (still $0)

1. **Get a free Gemini API key** at https://aistudio.google.com (this is
   separate from the consumer Gemini app subscription).
2. Push this folder to a **new GitHub repo**.
3. Repo → Settings → **Secrets and variables → Actions**:
   - New **secret** `GEMINI_API_KEY` = your key.
   - (optional) **variables** `AFFILIATE_TAG`, `SURVIVAL_THRESHOLD`, etc.
4. Repo → Settings → **Pages** → Source: *Deploy from branch* → `main` / `docs`.
   (Optionally enable a Markdown theme with a `docs/_config.yml`.)
5. The workflow runs every 6 hours automatically. Use **Actions →
   autonomous-agent → Run workflow** to wake it manually.

## Making the money real (do these when you're ready)

The agent already produces publishable content. To close the revenue loop:

- **Affiliate:** apply to Amazon Associates / an affiliate network, set
  `AFFILIATE_TAG`, and have `publish.py` insert real tagged links.
- **Display ads:** once you have traffic, apply to Google AdSense / Ezoic and
  drop their snippet into a `docs/_config.yml` theme.
- **Tips:** add a Ko-fi/Buy-Me-a-Coffee button (instant, no traffic needed).
- **Feed real earnings** into `ingest_revenue()` in `main.py` (from the
  affiliate/ads report API or a webhook) so the ledger reflects reality.

When `total_revenue > total_cost`, the agent is genuinely self-funding.

## Legal note

The agent operates entirely under **your** accounts (GitHub, Google, affiliate
programs). You are responsible for content quality, disclosures (affiliate/ads
require them), and each platform's terms. Keep a human in the loop.
