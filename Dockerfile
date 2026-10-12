# GPTScan image for the SmartBugs integration.
# Build (from the root of this repository):
#   docker build -t smartbugs/gptscan:29a1747 .
#
# The image bundles GPTScan + its runtime (Python 3.10, Java 17, a fallback
# solc). It does NOT contain any API key; the key is injected at run time via
# the DEEPSEEK_API_KEY / OPENAI_API_KEY environment variable (forwarded into the
# container by SmartBugs, see tools/gptscan/config.yaml there). SmartBugs overrides the
# entrypoint with tools/gptscan/scripts/do_solidity.sh at run time.
FROM python:3.10-bookworm

# System deps: Java 17 (GPTScan requirement) and git (falcon-analyzer git install).
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/gptscan

# Python deps (curated; see requirements-docker.txt for why not requirements.txt).
COPY requirements-docker.txt ./requirements-docker.txt
RUN pip install --no-cache-dir -r requirements-docker.txt

# Pre-cache the tiktoken encoding so a scan never depends on a network fetch.
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

# A default solc as a standalone fallback. Under SmartBugs the matching solc is
# provided via the mount (config.yaml: solc: yes) and takes precedence on PATH.
RUN pip install --no-cache-dir solc-select \
    && solc-select install 0.8.19 \
    && solc-select use 0.8.19

# GPTScan source (last, so dependency layers stay cached across code edits).
COPY . /opt/gptscan

# GPTScan reads rules/, tasks/, jars/ relative to the working directory.
WORKDIR /opt/gptscan/src
