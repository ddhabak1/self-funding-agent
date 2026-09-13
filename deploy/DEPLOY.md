# Deploying the Self-Funding Agent (where to run it 24×7)

The agent has two honest deployment tiers. **You already have Tier 1 running for
free.** Add Tier 2 when you want a truly continuous machine.

| Option | Cost | Runs continuously? | Setup effort | Best for |
|---|---|---|---|---|
| **GitHub Actions** (already live) | **$0, unlimited** (public repo) | Scheduled batches (nightly + every 6h) | **None — done** | The default. Zero signup. |
| **Oracle Cloud Always Free** VM | **$0 forever** | ✅ True 24×7 | Medium | Best free continuous box |
| **Fly.io** | Free allowance (card req.) | ✅ (small VM) | Low | Quick container deploy |
| **Any VPS / old laptop / Raspberry Pi** | your hardware | ✅ | Low | You already have a box |

---

## Tier 1 — GitHub Actions (already deployed, $0, nothing to do)

Because `ddhabak1/self-funding-agent` is **public**, GitHub gives it **unlimited
free Actions minutes**. The workflow `.github/workflows/agent.yml` already runs:

- `0 19 * * *` — nightly heavy run (scout + swarm + videos), and
- `0 */6 * * *` — a lighter refresh every 6 hours.

It scouts products, generates posts + videos, self-tunes, self-heals, and
commits the site back to GitHub Pages — all for free. **This is a real, live
deployment.** Trigger one now to confirm:

```bash
gh workflow run autonomous-agent -f mode=night      # or mode=cycle
gh run watch
```

Limitation: Actions caps a single job at ~6h, so this is *batches*, not a
continuous process. For an always-on grind, add Tier 2.

---

## Tier 2 — Oracle Cloud Always Free VM (recommended for true 24×7)

Oracle's **Always Free** tier gives an Ampere ARM VM (up to 4 cores / 24 GB RAM)
that runs **free forever** — more than enough for ffmpeg video renders +
OmniRoute + the watchdog.

1. **Create the VM.** Sign up at cloud.oracle.com → Compute → Instances →
   Create. Pick **Ampere (VM.Standard.A1.Flex)**, shape ~2 OCPU / 12 GB, image
   **Ubuntu 22.04**. Download the SSH key. (Card needed for identity; the
   Always Free shape is never billed.)

2. **SSH in and install deps:**
   ```bash
   sudo apt update && sudo apt install -y python3-venv python3-pip ffmpeg git
   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
   sudo apt install -y nodejs
   npm install -g omniroute        # free keyless LLM router
   ```

3. **Clone + set up the agent:**
   ```bash
   git clone https://github.com/ddhabak1/self-funding-agent.git
   cd self-funding-agent
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   cp .env.example .env            # then edit — see "Configuration" below
   ```

4. **Run it 24×7 under systemd:**
   ```bash
   sudo cp deploy/self-funding-agent.service /etc/systemd/system/
   # edit User=/WorkingDirectory=/EnvironmentFile= in that file if not 'ubuntu'
   sudo systemctl daemon-reload
   sudo systemctl enable --now self-funding-agent
   journalctl -u self-funding-agent -f      # watch it earn
   ```

The `watchdog` keeps OmniRoute up and restarts the night loop forever; systemd
restarts the watchdog itself if the box reboots.

---

## Tier 2 (alt) — Docker on any host (VPS, home server, Fly.io)

Everything is bundled in the `Dockerfile`. On any Docker host:

```bash
cp .env.example .env    # fill it in
docker compose up -d --build
docker compose logs -f
```

State (`state/`, `docs/`, `media/`) is volume-mounted so learning + the site
survive restarts.

**Fly.io:** `fly launch --no-deploy` (a `fly.toml` is included), then
`fly secrets set GH_PAT=... AFFILIATE_TAG=... GEMINI_API_KEY=...` and
`fly deploy`. Keep `NIGHT_MAX_ASSETS` low on the free VM.

---

## Configuration (the `.env`)

| Var | Needed? | What it does |
|---|---|---|
| `AFFILIATE_TAG` | yes (to earn) | Your Amazon tag, e.g. `dipankarsstor-21` |
| `AUTO_PUSH` | yes for VM/Docker | `1` = commit + push the new site each run (see below) |
| `GEMINI_API_KEY` | optional | Fallback brain if OmniRoute is down |
| `MODE` | `night` for 24×7 | `night` (grind) / `cycle` (1 article) / `doctor` (health) |
| `NIGHT_HOURS` | `8` on a real box | Hours to grind before looping (`0` = single batch) |
| `MAKE_VIDEO`, `NIGHT_MAX_ASSETS`, `SWARM_WORKERS` | optional | Throughput tuning |

### Letting a VM publish to GitHub Pages (git push auth)

In Actions, GitHub pushes for you. On your own box you need push credentials so
`AUTO_PUSH=1` can publish. Create a **fine-grained PAT** (repo `Contents:
read/write` on `self-funding-agent`) and point the remote at it **once**:

```bash
git remote set-url origin https://ddhabak1:<GH_PAT>@github.com/ddhabak1/self-funding-agent.git
```

Then every night run auto-commits `docs/` + `state/` and pushes — GitHub Pages
redeploys automatically. (Prefer not to embed the token? Use
`gh auth login` + `gh auth setup-git`, or a credential helper.)

---

## Which should you pick?

- **Want it working right now, $0, no signup?** You already have it — GitHub
  Actions. Just let the crons run (or trigger one).
- **Want a genuine always-on machine that never sleeps?** Stand up the **Oracle
  Always Free VM** with the systemd unit — free forever and strong enough for
  video. This is the recommended home for the 24×7 watchdog.

Both can run at once: Actions as a reliable free heartbeat, the VM as the
continuous worker. They share state through the same repo, so they cooperate
rather than conflict.
