# GPTScan + SmartBugs integration

This document describes how GPTScan is packaged as a [SmartBugs](https://github.com/smartbugs/smartbugs)
analysis tool, how to switch the LLM provider/model, how the weakness mapping
is built, and how to produce a scan and a report. Its structure follows the
SmartBugs wiki page *"Adding new analysis tools"*.

## 1. Overview

GPTScan detects **DeFi logic vulnerabilities** by combining an LLM with light
program analysis. It is wired into SmartBugs like any other tool, with one
peculiarity: it needs network access and an API key at run time, because the
"analysis engine" is a remote OpenAI-compatible LLM (OpenAI or **DeepSeek**).

A scan flows like this:

```
smartbugs -t gptscan -f Contract.sol
        │
        ├─ SmartBugs copies Contract.sol + tools/gptscan/scripts into a temp dir,
        │  mounts it at /sb, picks a matching solc, and starts the container
        │  (image smartbugs/gptscan:29a1747, network: bridge).
        │  SmartBugs forwards DEEPSEEK_API_KEY / OPENAI_API_KEY /
        │  GPTSCAN_* from the host into the container's environment.
        │
        ├─ entrypoint  tools/gptscan/scripts/do_solidity.sh
        │     copies the .sol into /work/input, runs
        │     `python3 main.py -s /work/input -o /output.json --provider … --format json`
        │
        ├─ GPTScan calls the LLM backend, writes /output.json (+ .metadata.json),
        │  prints a `GPTSCAN_META {…}` line with tokens/cost.
        │
        └─ SmartBugs retrieves /output.json (config `output:`), and
           tools/gptscan/parser.py converts it into SmartBugs findings,
           attaching SWC/DASP labels from tools/gptscan/findings.yaml.
```

## 2. The tool directory

`smartbugs/tools/gptscan/` mirrors the standard SmartBugs tool layout:

| File | Purpose |
| --- | --- |
| `config.yaml` | Docker image, `bin`, `output: /output.json`, **`network: bridge`** (the LLM needs outbound access; SmartBugs defaults tools to `network: none`), solidity `entrypoint` + `solc: yes`. |
| `scripts/do_solidity.sh` | Entrypoint: prepares a clean source folder, selects provider/model from the environment, runs GPTScan, emits the cost line, guarantees `/output.json` exists. |
| `parser.py` | `parse(exit_code, log, output)` → `(findings, infos, errors, fails)`. Untars `/output.json`, maps each result to a SmartBugs finding (`name` = GPTScan `output.title`), records the cost line in `infos`. |
| `findings.yaml` | Maps each finding name to its taxonomy (`classification`), severity and descriptions. Copy of `taxonomy/findings.yaml` in this repository. |

### The one core patch

SmartBugs does not forward host environment variables into tool containers and
rejects unknown `config.yaml` fields, so the API key cannot be passed the usual
way. The tool's `config.yaml` therefore declares an allow-list in a new `env:`
field — `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `GPTSCAN_PROVIDER`,
`GPTSCAN_MODEL`, `GPTSCAN_DRY_RUN`, `GPTSCAN_BASE_URL`, `GPTSCAN_API_KEY`.
SmartBugs forwards the listed variables into the container when they are
set on the host (`sb/docker.py`). Before the Docker arguments are persisted
into `smartbugs.json`, the forwarded values are replaced by `<redacted>`.
The key is never baked into the image.

## 3. Building the image

From the root of this repository:

```shell
docker build -t smartbugs/gptscan:29a1747 .
```

The image bundles Python 3.10, Java 17, a fallback solc, and GPTScan with a
**curated** dependency set (`requirements-docker.txt`). The repo's
`requirements.txt` is a full `pip freeze` containing OS packages
(`dbus-python`, `launchpadlib`, …) that are not GPTScan dependencies and break a
clean container build, so the image does not use it. No API key is included
(`.dockerignore` excludes `.env`).

## 4. Running a scan

```shell
# from the smartbugs/ checkout, with the venv active (or via .venv/bin/python -m sb)
export DEEPSEEK_API_KEY=sk-...            # forwarded into the container
smartbugs -t gptscan -f samples/0.8.24/SimpleDAO.sol --json --timeout 600
```

Useful environment variables (all forwarded into the container):

| Variable | Effect |
| --- | --- |
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` | API key for the selected provider. |
| `GPTSCAN_PROVIDER` | `deepseek` (default), `openai` or `custom`. |
| `GPTSCAN_MODEL` | Override the model (e.g. `deepseek-v4-pro`). |
| `GPTSCAN_DRY_RUN=1` | Estimate calls/cost without any network request (no key needed). |
| `GPTSCAN_BASE_URL` | Endpoint of an OpenAI-compatible server; only used with `GPTSCAN_PROVIDER=custom`. |
| `GPTSCAN_API_KEY` | API key for the `custom` provider; only used with `GPTSCAN_PROVIDER=custom`. |

The parsed result (`result.json`) lists the findings; the `infos` field carries
a one-line cost summary, e.g.
`GPTScan run: backend=deepseek/deepseek-v4-flash, llm_calls=3, est_cost_usd=0.0006`.

## 5. Switching provider / model

Provider/model selection is identical to standalone GPTScan (see the main
[README](../README.md#choosing-the-llm-provider--model)). Under SmartBugs, set
`GPTSCAN_PROVIDER` / `GPTSCAN_MODEL` on the host; standalone, pass
`--provider` / `--model`. The default backend is **`deepseek` /
`deepseek-v4-flash`**; OpenAI remains fully supported via `--provider openai`.

## 6. Weakness mapping

GPTScan's 10 detectors (`src/rules/*.yml`, MWE-200..209) are mapped to the SWC
Registry / DASP Top 10 in `taxonomy/findings.yaml`, with the rationale
in `taxonomy/mapping.md`. Only **Front Running** (SWC-114 / DASP-7) and
**Unauthorized Transfer** (DASP-2) map cleanly; the other eight are DeFi
business-logic bugs with no faithful registry entry and are explicitly marked
`BUSINESS-LOGIC (no SWC/DASP)` rather than force-fitted. The same file is copied
to `tools/gptscan/findings.yaml`, where SmartBugs uses it to enrich findings.

## 7. Producing a report

* **JSON** (default) — `-o out.json` writes GPTScan's native JSON plus
  `out.json.metadata.json` (tokens, cost, per-stage counts).
* **Markdown** — `--format md` (or `both`) writes `out.md`: per-contract
  findings (severity, affected lines, GPTScan category, mapped SWC/DASP, model)
  and an aggregated summary (findings per category and per contract, total
  cost). Implemented in `src/report_md.py`.

Under SmartBugs the per-task report is `result.json`; an aggregated
cross-contract Markdown summary for a whole run is produced separately from the
collected `result.json` files.

## 8. Cost control

A scan can issue hundreds of LLM calls per contract. Two safeguards:

* **`--dry-run`** (host: `GPTSCAN_DRY_RUN=1`) projects calls/tokens/cost without
  spending anything — run it before any batch.
* **`MAX_LLM_CALLS` / `MAX_COST_USD`** in `src/config.py` are hard guards: once a
  limit is hit, the scan stops issuing calls (it does not crash), logs a
  warning, and records `budget_exceeded` in the metadata.

Cost uses the API's reported token `usage` when available — important for
reasoning models such as `deepseek-v4-flash`, whose completion includes
reasoning tokens that are not present in the response text. DeepSeek prices in
`src/config.py` are the official rates.

## 9. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Every LLM call fails / times out | Container has no network. Ensure `config.yaml` has `network: bridge` and the host can reach the API. |
| `No API key for provider …` | Set `DEEPSEEK_API_KEY` (or `OPENAI_API_KEY`) on the host; SmartBugs forwards it (`env:` in `config.yaml`). |
| Empty output / no findings on a contract | GPTScan silently produces nothing if the path contains `external/openzeppelin/uniswap/pancakeswap/legacy/test`; the entrypoint already copies into the safe `/work/input`. Also, static confirmation is strict — minimal hand-written contracts may not confirm. |
| `model not found` / call hangs | The model id is wrong for the provider. Verify with a one-off call before a batch (a wrong model makes GPTScan's retry loop spin until the task timeout). |
