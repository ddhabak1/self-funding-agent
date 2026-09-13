# Self-Funding Agent — 24x7 container image.
# Bundles everything the agent needs to run continuously on any host that can
# run Docker: Python (the agent), Node (the free OmniRoute LLM router), ffmpeg
# (video), git (auto-publish). Entry point is the self-restarting watchdog.
FROM python:3.12-slim

# System deps: node/npm for OmniRoute, ffmpeg for video, git for auto-publish.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git curl ca-certificates gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Free, keyless LLM router (best-effort: image still works via Gemini/offline).
RUN npm install -g omniroute || echo "omniroute global install skipped"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 24x7 defaults — grind all night, publish results, keep the brain warm.
ENV MODE=night \
    NIGHT_HOURS=8 \
    AUTO_PUSH=1 \
    OMNIROUTE_URL=http://localhost:20128/v1 \
    OMNIROUTE_MODEL=auto \
    PYTHONUNBUFFERED=1

# The watchdog ensures OmniRoute is up and restarts the loop on any exit.
CMD ["python", "-m", "agent.watchdog"]
