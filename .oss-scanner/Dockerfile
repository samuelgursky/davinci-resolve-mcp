# Mirrors .github/workflows/ci.yml: Python 3.11 + Node 22 + ffmpeg, then the offline test suites.
# DaVinci Resolve itself is proprietary and not installed; the Python suite stubs DaVinciResolveScript.
FROM node:22-bookworm
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CI=true
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git build-essential python3 python3-venv python3-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# scanner contract: the checkout lives inside the image, at /src
COPY . /src
WORKDIR /src

# Python: requirements.txt plus what the test suite imports (same set as CI). On PATH for the agent.
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN pip install --no-cache-dir "mcp[cli]" -r requirements.txt \
    && pip install --no-cache-dir pytest pyflakes numpy pillow requests

# Node: root package (npm bootstrapper bins) and the advanced server (offline .drp/.drt/.drx/AAF codecs).
# Optional deps included so the SQLite (better-sqlite3) and image (sharp) paths are exercisable offline.
RUN npm ci --no-audit --no-fund \
    && cd resolve-advanced && npm ci --no-audit --no-fund

# Cheap tests so the image is known-good; failures warn, they do not abort the build.
RUN python -m pytest tests -q -p no:cacheprovider \
    || echo "WARNING: Python offline suite reported failures"
RUN cd resolve-advanced && (npm test || echo "WARNING: advanced-server node suite reported failures")
RUN node bin/davinci-resolve-mcp.mjs --version && node bin/davinci-resolve-advanced-mcp.mjs --version
