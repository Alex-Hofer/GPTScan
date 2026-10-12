"""Central LLM backend abstraction for GPTScan.

GPTScan talks to exactly one OpenAI-compatible Chat-Completions backend per run
(OpenAI or DeepSeek today; any other compatible provider is one entry in
``config.PROVIDERS``). This module is the single source of truth for:

* which provider / model / base-url / API key the current run uses,
* per-token pricing and cost estimation,
* the ``--dry-run`` flag and the sentinel answers it feeds back into the
  pipeline so a scan can be costed without making any network calls,
* the optional hard budget guards.

Why route the selection through environment variables instead of plain module
globals: GPTScan executes every real LLM call inside a ``multiprocessing.Pool``
worker (see ``analyze_pipeline.ask_with_timeout``). On Linux (fork) globals are
inherited, but on Windows (spawn) the worker re-imports this module from
scratch. Environment variables are inherited by the child in BOTH cases, so the
parent sets them once (``configure_from_args``) and every process — parent and
worker — reads the same configuration.
"""

import os
import time
from typing import Optional

import config as global_config

# Environment variables used to carry the run configuration across the
# parent/worker process boundary.
ENV_PROVIDER = "GPTSCAN_PROVIDER"
ENV_MODEL = "GPTSCAN_MODEL"
ENV_DRY_RUN = "GPTSCAN_DRY_RUN"
ENV_BASE_URL = "GPTSCAN_BASE_URL"


# ---------------------------------------------------------------------------
# Run configuration (read from the environment, cached per process)
# ---------------------------------------------------------------------------

def configure_from_args(provider: Optional[str], model: Optional[str],
                        dry_run: bool) -> None:
    """Persist the chosen backend into the environment (call in the parent).

    Must run before the analysis pipeline spawns any worker process.
    """
    os.environ[ENV_PROVIDER] = provider or global_config.DEFAULT_PROVIDER
    if model:
        os.environ[ENV_MODEL] = model
    else:
        os.environ.pop(ENV_MODEL, None)
    os.environ[ENV_DRY_RUN] = "1" if dry_run else "0"


def active_provider() -> str:
    """Name of the provider this process should use.

    Raises rather than falling back to the default when the name is unknown: a
    silent fallback would bill a different backend than the one the run was
    started with, and the mistake would only surface in the cost figures.
    """
    name = os.environ.get(ENV_PROVIDER) or global_config.DEFAULT_PROVIDER
    if name not in global_config.PROVIDERS:
        raise ValueError(
            f"Unknown provider '{name}'. Known: {', '.join(global_config.PROVIDERS)}")
    return name


def provider_config() -> dict:
    """The ``config.PROVIDERS`` entry of the active provider."""
    return global_config.PROVIDERS[active_provider()]


def model_override() -> Optional[str]:
    """Model id given via ``--model``, or None to use the provider's tiers."""
    return os.environ.get(ENV_MODEL) or None


def is_dry_run() -> bool:
    """Is this run costing the pipeline out without making any call?"""
    return os.environ.get(ENV_DRY_RUN) == "1"


def resolve_model(gpt4: bool = False) -> str:
    """Model id for a call. An explicit --model overrides both tiers."""
    override = model_override()
    if override:
        return override
    tier = "strong" if gpt4 else "cheap"
    return provider_config()["models"][tier]


def base_url() -> Optional[str]:
    """Chat-Completions endpoint of the active provider.

    None for OpenAI itself, whose endpoint is the SDK default --- see
    :func:`configure_sdk`, which leaves ``api_base`` untouched in that case.

    The "custom" provider has no fixed address and reads GPTSCAN_BASE_URL
    instead. The override is deliberately confined to that provider: it must be
    impossible to redirect a real, paid backend by setting a variable.
    """
    config = provider_config()
    if active_provider() == "custom":
        return os.environ.get(ENV_BASE_URL) or config.get("base_url")
    return config.get("base_url")


def api_key() -> str:
    """Read the API key for the active provider from its env var."""
    env_name = provider_config()["api_key_env"]
    key = os.environ.get(env_name)
    if not key:
        raise RuntimeError(
            f"No API key found in environment variable '{env_name}'. "
            f"Set it in your .env file (see .env.example) or pass -k.")
    return key


def configure_sdk(openai_module) -> str:
    """Point the (v0.x) openai SDK at the active provider. Returns the model id.

    Called inside the worker process right before the Chat-Completions request.
    """
    openai_module.api_key = api_key()
    url = base_url()
    # Only override api_base when the provider defines one; leaving it untouched
    # preserves the SDK default for OpenAI.
    if url:
        openai_module.api_base = url
    return resolve_model(gpt4=False)


# ---------------------------------------------------------------------------
# Pricing / cost
# ---------------------------------------------------------------------------

def price_per_token(model: str, direction: str) -> float:
    """USD per single token for ``direction`` in {"in", "out"}."""
    prices = provider_config()["prices"].get(model) or global_config.UNKNOWN_MODEL_PRICE
    return prices[direction] / 1_000_000.0


def estimate_cost(tokens_sent: float, tokens_received: float,
                  tokens_sent_gpt4: float = 0.0,
                  tokens_received_gpt4: float = 0.0) -> float:
    """USD cost for the four GPTScan token counters under the active backend.

    The cheap-tier counters (tokens_sent/received) are priced with the cheap
    model (or the --model override); the gpt4 counters with the strong model.
    """
    cheap = resolve_model(gpt4=False)
    strong = resolve_model(gpt4=True)
    return (tokens_sent * price_per_token(cheap, "in")
            + tokens_received * price_per_token(cheap, "out")
            + tokens_sent_gpt4 * price_per_token(strong, "in")
            + tokens_received_gpt4 * price_per_token(strong, "out"))


# ---------------------------------------------------------------------------
# Dry-run support
# ---------------------------------------------------------------------------

# How many scenarios a multiple-choice sentinel claims to match. The pipeline
# ignores indices beyond the real scenario count, so any generous number works.
_DRY_CHOICES = 30

AVG_COMPLETION_TOKENS = global_config.DRY_RUN_AVG_COMPLETION_TOKENS


def dry_sentinel(kind: Optional[str]) -> str:
    """Canned answer returned in --dry-run so the pipeline keeps traversing.

    ``kind`` identifies the call site so the sentinel drives an upper-bound walk
    of the pipeline (every scenario "matches" and "confirms"), maximising the
    estimated call count:

    * "choices" -> a JSON map ``{"1":"yes",...}`` for the multiple-choice stage
    * "yesno"   -> ``"yes"`` for the single yes/no confirmation stage
    * anything else (static-analysis prompts) -> ``"{}"``, which the static
      parsers consume quietly without raising.
    """
    if kind == "choices":
        return "{" + ", ".join(f'"{i}": "yes"' for i in range(1, _DRY_CHOICES + 1)) + "}"
    if kind == "yesno":
        return "yes"
    return "{}"


# ---------------------------------------------------------------------------
# Budget guards
# ---------------------------------------------------------------------------

def budget_exceeded(num_calls: int, cost_usd: float) -> Optional[str]:
    """Return a human-readable reason if a configured hard limit is reached."""
    max_calls = global_config.MAX_LLM_CALLS
    if max_calls is not None and num_calls >= max_calls:
        return f"MAX_LLM_CALLS ({max_calls}) reached"
    max_cost = global_config.MAX_COST_USD
    if max_cost is not None and cost_usd >= max_cost:
        return f"MAX_COST_USD (${max_cost:.2f}) reached"
    return None


# ---------------------------------------------------------------------------
# Deadline guard (SmartBugs --timeout)
# ---------------------------------------------------------------------------

# Absolute wall-clock deadline in Unix seconds, exported by the SmartBugs
# entrypoint. Absolute rather than a remaining duration because every real LLM
# call runs in a multiprocessing worker: an absolute instant means the same
# thing in parent and child, a remaining duration does not.
ENV_DEADLINE = "SB_DEADLINE_EPOCH"


def deadline_exceeded() -> Optional[str]:
    """Return a human-readable reason once the run's deadline has passed.

    Returns None when no deadline is configured, when it lies in the future, or
    when the value cannot be read as a number. That last case is deliberate: a
    malformed variable must never cut a paid run short --- it disables the
    guard, exactly as an unset variable does.
    """
    raw = os.environ.get(ENV_DEADLINE)
    if not raw:
        return None
    try:
        deadline = float(raw)
    except (TypeError, ValueError):
        return None
    overdue = time.time() - deadline
    if overdue < 0:
        return None
    return (f"SmartBugs deadline reached ({ENV_DEADLINE}={int(deadline)}, "
            f"{overdue:.0f}s over)")


def deadline_sentinel(kind: Optional[str]) -> str:
    """Neutral answer fed back once the SmartBugs deadline has passed.

    Deliberately NOT ``dry_sentinel``: that one is an upper-bound probe for
    --dry-run and answers "yes" to everything, which after the deadline would
    let the pipeline advance on the strength of an answer nobody gave. For a
    call that was never made the truthful stance is "no information", so every
    call site gets ``"{}"``:

    * "choices" -> ``json.loads(res.split("}")[0] + "}")`` yields an empty map,
      so no scenario is marked as matching
    * "yesno"   -> does not start with "yes", so the confirmation counts as a no
    * static prompts -> unchanged; ``"{}"`` is what they received before

    ``kind`` is kept in the signature to mirror ``dry_sentinel`` and to leave
    room for a per-stage answer should one ever be needed. The consequence of
    answering neutrally is the one the marker promises: a run cut short reports
    a subset of what a full run would report, never something extra.
    """
    return "{}"
