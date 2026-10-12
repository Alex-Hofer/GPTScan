import logging
import datetime

OPENAI_API_KEY = "NOT NEEDED"

OPENAI_APIS = ["NOT NEEDED"]

GPT4_API = "NOT NEEDED"


GITHUB_TOKEN = "NOT NEEDED"
LOGGING_LEVEL = logging.INFO
LOGGING_FORMAT = "%(name)s: %(message)s"
# LOGGING_TARGET = datetime.datetime.now().strftime("logs/main.py-output-%Y%m%d-%H%M%S.log")
STATEMENT_FILE = "output/statements.csv"
WRITE_STATEMENTS_INTO_FILE = True
BACKUP_STATEMENTS = True

ENABLE_STATIC_ANALYSIS = True

SEND_PRICE = 0.0015 / 1000
RECEIVE_PRICE = 0.002 / 1000

GPT4_SEND_PRICE = 0.03 / 1000
GPT4_RECEIVE_PRICE = 0.06 / 1000


# ---------------------------------------------------------------------------
# LLM provider / model abstraction
# ---------------------------------------------------------------------------
# GPTScan only ever talks to ONE backend per run. A backend is an OpenAI-style
# Chat-Completions endpoint, selected at the CLI via --provider / --model.
# Adding another OpenAI-compatible provider is just one more entry below.
#
# Prices are given in US dollars per 1,000,000 tokens for readability and are
# converted to a per-token cost by `llm_backend.price_per_token`.
#
# Each provider exposes a "cheap" and a "strong" model tier. GPTScan's pipeline
# currently issues every call on the cheap tier (the `GPT4=True` path is dead
# code today); the strong tier is kept wired for completeness / future use.
PROVIDERS = {
    "openai": {
        "base_url": None,  # None => the openai SDK default (api.openai.com)
        "api_key_env": "OPENAI_API_KEY",
        "models": {"cheap": "gpt-3.5-turbo", "strong": "gpt-4"},
        # Public OpenAI list prices (USD / 1M tokens).
        "prices": {
            "gpt-3.5-turbo": {"in": 1.50, "out": 2.00},
            "gpt-4":         {"in": 30.0, "out": 60.0},
        },
    },
    "deepseek": {
        # DeepSeek is OpenAI-compatible. The v0.x SDK appends "/chat/completions"
        # to api_base, so the bare host works; use ".../v1" if your gateway needs it.
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        # NOTE: deepseek-v4-flash / deepseek-v4-pro are the CURRENT model names.
        # The old aliases deepseek-chat / deepseek-reasoner are sunset 2026-07-24
        # and must not be used as defaults.
        "models": {"cheap": "deepseek-v4-flash", "strong": "deepseek-v4-pro"},
        # Official DeepSeek prices (USD / 1M tokens), confirmed 2026-07-01.
        "prices": {
            "deepseek-v4-flash": {"in": 0.14, "out": 0.28},
            "deepseek-v4-pro":   {"in": 1.74, "out": 3.48},
        },
    },
    "custom": {
        # An OpenAI-compatible endpoint chosen at run time, e.g. a local
        # stand-in server used for tests. The URL comes from
        # GPTSCAN_BASE_URL because a local endpoint has no fixed address.
        # Prices are zero: nothing is billed, and a cost estimate that invented
        # a figure here would poison the measurements.
        "base_url": None,
        "api_key_env": "GPTSCAN_API_KEY",
        "models": {"cheap": "custom-cheap", "strong": "custom-strong"},
        "prices": {
            "custom-cheap":  {"in": 0.0, "out": 0.0},
            "custom-strong": {"in": 0.0, "out": 0.0},
        },
    },
}

# Default backend when neither --provider nor --model is given.
# Rationale: this is the budget-friendly backend we actually have credit for,
# and v4-flash is the cheap tier. The OpenAI path stays fully functional via
# `--provider openai`.
DEFAULT_PROVIDER = "deepseek"

# Fallback price (USD / 1M tokens) used when a model has no entry in `prices`
# above (e.g. a custom --model). Conservative so estimates do not understate.
UNKNOWN_MODEL_PRICE = {"in": 1.00, "out": 2.00}

# Average completion length (tokens) assumed PER CALL in --dry-run, where the
# real response size is unknown. Only affects the dry-run cost projection.
DRY_RUN_AVG_COMPLETION_TOKENS = 250

# Optional hard budget guards enforced live, before each LLM call. None = off.
# When a limit is hit the scan stops issuing further calls (it does not crash),
# logs a warning and records `budget_exceeded` in the metadata.
MAX_LLM_CALLS = None      # e.g. 5000
MAX_COST_USD = 0.5        # per-contract hard stop (USD); guards the 10 EUR budget

