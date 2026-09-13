# The Self-Funding Agent 🤖💸

An autonomous agent whose goals are: **(1) run 24×7**, **(2) earn enough money
to pay for its own survival**, and **(3) learn and improve itself with no human
in the loop.** Every night it researches what actually earns, mass-produces
monetized content + HD promo videos, and self-tunes which styles win.

> ⚠️ **Honest expectations.** Real affiliate income is slow and never
> guaranteed. This is a *real, closeable* revenue loop with honest accounting —
> not a magic money printer. Revenue becomes real once your Amazon Associates /
> ad account is approved and traffic arrives.

## How the goals are met — all $0

| Goal | How | Cost |
|------|-----|------|
| Run 24×7 | GitHub Actions cron + optional 24×7 host | $0 |
| A place to publish | GitHub Pages serves `docs/` | $0 |
| A brain (no rate limits) | **OmniRoute** free/keyless LLM router, Gemini fallback | $0 |
| Find what earns | Scout + 100-worker research **swarm** | $0 |
| Make content that converts | Content + HD Shorts factory with affiliate links | $0 |
| Learn & improve | Bandit **self-tuning** over viral hook styles | $0 |
| "Survive" | `ledger.py` tracks balance; halts if broke | — |

## The brain: OmniRoute (no more 429s)

The agent talks to a local **[OmniRoute](https://www.npmjs.com/package/omniroute)**
server — an OpenAI-compatible router that aggregates many free / keyless LLM
providers with automatic fallback. This sidesteps the Gemini free-tier quota
entirely. `brain.py` cascades: **OmniRoute → Gemini SDK → offline stub**.

```bash
npm i -g omniroute && omniroute serve --daemon --no-open   # http://localhost:20128/v1
```

Backend is env-selectable: `LLM_BACKEND=auto|omniroute|gemini`.

## Architecture

```
agent/
  config.py    all settings (env-driven)
  brain.py     backend-agnostic LLM: OmniRoute -> Gemini -> offline
  bus.py       SQLite message bus (agents communicate)
  scout.py     nightly top-10 best-selling + HIGH-COMMISSION products
  swarm.py     100 logical research agents (concurrent, one environment)
  trends.py    picks the most viral, monetizable idea
  content.py   writes the on-site article
  factory.py   product -> landing post + styled HD promo video + affiliate links
  shorts.py    HD 1080x1920 per-frame video renderer + free TTS voiceover
  videobrief.py optional render brief handed to the OpenMontage studio
  affiliate.py Amazon Associates tagged-link injection (compliant)
  optimize.py  self-tuning bandit over hook styles + category bias
  selfheal.py  startup health checks, incident log, circuit breakers, auto-fixes
  reflect.py   nightly reflection -> durable lessons fed back into prompts
  watchdog.py  24x7 supervisor: restarts OmniRoute + the loop with backoff
  night.py     the all-night loop: scout/swarm -> videos -> self-tune
  orchestrator.py  the classic single-article cycle
  main.py      entry point (MODE=night | cycle)
docs/          the public blog (GitHub Pages, SEO-ready)
state/         ledger, memory, strategy, performance, daily_products (git-persisted)
media/         generated videos (CI artifacts; git-ignored)
```

### Why a *commission* model matters
Phones/laptops/TVs sell hugely but pay ~1-2%. Beauty, grooming, home, kitchen,
health and fashion pay ~5-9%. The scout scores every candidate by
`opportunity = demand × commission`, so the agent chases **earnings**, not just
popularity.

### Self-tuning
`optimize.py` runs an epsilon-greedy bandit over viral hook archetypes
(`shock_stat`, `mistake_warning`, `secret_reveal`, `price_shock`, …). Styles
that earn clicks get produced more; the rest fade. Rewards come from real
metrics when available (`state/metrics.json`: views/clicks/earnings), so it
starts learning immediately and improves as real numbers arrive. Strategy is
committed back to the repo, so learning persists across nights and machines.

### Two-tier video: always-on $0 vs. premium studio
Unattended CI must never end without a deliverable, so the built-in `shorts.py`
PIL renderer (zero external deps) is the **guaranteed $0 path** and default
(`VIDEO_BACKEND=builtin`).

Set `VIDEO_BACKEND=openmontage` to *also* emit a structured render brief
(`state/video_briefs/<slug>.json`) for **[OpenMontage](https://github.com/calesthio/OpenMontage)**
— an instruction-driven studio (Remotion + offline **Piper TTS** + open
Archive.org/NASA/Wikimedia footage, **zero API keys**). OpenMontage is agentic
(an AI assistant drives its pipeline through quality gates), so it runs on your
**24×7 machine** — where **[ruflo](https://github.com/ruvnet/ruflo)** + Claude
Code (pointed at OmniRoute's free providers) pick up briefs and produce
cinematic cuts that replace the built-in short. The built-in video is always
produced first, so a run never ships nothing. Earnings can later fund
OpenMontage's optional paid providers (Veo/Kling ~$1-4/video) with no code
change. ruflo/OpenMontage are operator tooling and are git-ignored from this
public site repo.

## Self-healing & self-improvement (built to get more powerful over time)

The agent is designed to survive unattended and grow stronger every night.

**Self-healing (`selfheal.py`).** Every run opens with `preflight()`, which takes
the agent's vitals — LLM backends, video renderer + ffmpeg, free disk, site
integrity, daily budget — logs any failure to a rolling incident log, trips a
per-component **circuit breaker** after repeated failures, and writes safe
overrides back into the run so it *routes around* the damage instead of
crashing:

- renderer broken / low disk → disable video (and prune old media) for the run,
- repeated swarm timeouts → automatically halve worker count + concurrency,
- OmniRoute down → fall through to Gemini, then to the offline stub,
- run `MODE=doctor` (also a CI preflight step) for a one-shot self-diagnosis.

Incidents + health are committed to `state/`, so the healing memory persists
across nights and machines.

**Self-improvement (`reflect.py` + `optimize.py`).** Two nested learning loops:
the epsilon-greedy bandit tunes *which* hook style / category to produce, and
nightly **reflection** distills everything produced + earned into plain-language
**lessons** (`state/lessons.md`) whose `guidance()` is injected straight back
into the content prompts. Over many nights it stops repeating what didn't work
and leans harder into what does — no human editing prompts.

**24×7 durability (`watchdog.py`).** On a machine you own, the watchdog keeps
OmniRoute up and restarts the night loop with exponential backoff if it ever
exits — so it truly never stops:

```bash
nohup python -m agent.watchdog >> watchdog.log 2>&1 &
```

## Run it

```bash
cd autonomous-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm i -g omniroute && omniroute serve --daemon --no-open   # free brain

# one article (classic cycle)
python -m agent.main

# a full autonomous night: scout/swarm -> HD videos -> self-tune
MODE=night SWARM_WORKERS=100 NIGHT_MAX_ASSETS=10 MAKE_VIDEO=1 python -m agent.main

# true all-night grind on a 24x7 host you own:
MODE=night NIGHT_HOURS=8 python -m agent.main
```

## Go live (still $0)

1. Free Gemini API key at https://aistudio.google.com (fallback brain).
2. Push to a public GitHub repo.
3. Settings → Secrets/variables → Actions: secret `GEMINI_API_KEY`; variables
   `AFFILIATE_TAG`, `AMAZON_DOMAIN`, `SWARM_WORKERS`, `NIGHT_MAX_ASSETS`, etc.
4. Settings → Pages → Deploy from branch → `main` / `docs`.
5. The **nightly** cron runs the scout+swarm+video factory; a lighter 6-hourly
   cron keeps the site fresh. Videos are uploaded as **Actions artifacts** for
   you (or a future API step) to post to YouTube Shorts / Instagram / Facebook.

## Scaling honestly (why we DON'T self-replicate)

You may be tempted to spawn 100 agents that each create cloud accounts and host
themselves. **Don't** — and this system won't:

- Automated signup + multi-accounting to farm free tiers violates every
  provider's ToS and is treated as fraud. It gets **all linked accounts banned**
  — including the Amazon Associates and Google/GitHub accounts this whole thing
  runs on. A banned account is a dead, unpaid agent.
- Duplicate content across many hosts triggers SEO penalties, not more traffic.

The **legitimate** way to get the same throughput is already built in: the
**research swarm** runs up to 100 *logical* agents concurrently inside the one
environment you own (a bounded thread pool sharing the message bus), and you
scale hosting via a single box you legitimately control.

## Compliance & legal

Runs entirely under **your** accounts. Amazon affiliate links must live on your
**site** (not pasted into social captions); social drives traffic to the site.
FTC/Amazon disclosures are auto-inserted. You are responsible for content
quality and each platform's terms.
