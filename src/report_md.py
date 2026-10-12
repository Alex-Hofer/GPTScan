"""Markdown report formatter for GPTScan.

Renders the same results object that goes to JSON (see utils.convert_output)
into a human-readable Markdown report:

* a run header (provider, model, mode, totals, tokens, estimated cost),
* findings grouped per contract/file (severity, affected file+lines, GPTScan
  category, mapped SWC/DASP taxonomy label, model),
* an aggregated summary across all scanned contracts (findings per category and
  per contract, plus totals).

Wired into tasks.py via ``--format md|both``. Pure-stdlib + PyYAML, so the
``render_markdown`` core can be unit-tested with synthetic data.
"""

import os
import datetime
from typing import Optional

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a hard dependency at runtime
    yaml = None

# taxonomy/findings.yaml lives next to the repo's src/ directory.
_TAXONOMY_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "taxonomy", "findings.yaml"))

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def load_taxonomy(path: str = _TAXONOMY_PATH) -> dict:
    """Map of finding title -> taxonomy entry; empty dict if unavailable."""
    if yaml is None or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _classification(title: str, taxonomy: dict) -> str:
    """SWC/DASP label for a finding title, or ``"n/a"`` if it has none.

    Missing entries are reported as "n/a" rather than raising: a taxonomy gap
    must not stop a report from being written, and "n/a" makes the gap visible
    in the rendered table.
    """
    entry = taxonomy.get(title) or {}
    return entry.get("classification", "n/a")


def _md_path(output_file: str) -> str:
    """Markdown path beside the JSON report (``x.json`` -> ``x.md``).

    Keeping both reports on the same stem is what lets ``--format both`` write
    them side by side without a second CLI argument.
    """
    if output_file.lower().endswith(".json"):
        return output_file[:-len(".json")] + ".md"
    return output_file + ".md"


def _fmt_cost(meta: dict) -> str:
    """Estimated cost, marked as projected when no call was actually made.

    In ``--dry-run`` the figure is what the run *would* have cost; labelling it
    keeps a dry-run report from being mistaken for a billed one.
    """
    cost = meta.get("estimated_cost", 0) or 0
    suffix = " (projected, dry-run)" if meta.get("dry_run") else ""
    return f"${cost:.4f}{suffix}"


def _affected_lines(result: dict) -> list:
    """Return ["path:start-end", ...] for a result's affected files."""
    out = []
    for af in result.get("affectedFiles", []) or []:
        path = af.get("filePath", "?")
        rng = af.get("range", {}) or {}
        start = (rng.get("start", {}) or {}).get("line", "?")
        end = (rng.get("end", {}) or {}).get("line", "?")
        out.append(f"{path}:{start}-{end}")
    return out


def _group_file(result: dict) -> str:
    """The file a finding is filed under in the report.

    A finding can touch several files; the *first* affected file decides the
    grouping, because that is the one GPTScan reports the finding against. The
    remaining files still appear in the finding's "Affected" line, so nothing
    is hidden by the choice.
    """
    affected = result.get("affectedFiles", []) or []
    if affected:
        return affected[0].get("filePath", "(unknown)")
    return "(unknown)"


def render_markdown(output_json: dict, meta_data: dict,
                    taxonomy: Optional[dict] = None,
                    generated_at: Optional[str] = None) -> str:
    """Build the full Markdown report as a string."""
    if taxonomy is None:
        taxonomy = load_taxonomy()
    if generated_at is None:
        generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    results = output_json.get("results", []) or []
    lines = []

    # ---- header ---------------------------------------------------------
    lines.append("# GPTScan Report")
    lines.append("")
    mode = "DRY-RUN (no calls made)" if meta_data.get("dry_run") else "live"
    header = [
        ("Generated", generated_at),
        ("Provider", meta_data.get("provider", "n/a")),
        ("Model", meta_data.get("model", "n/a")),
        ("Mode", mode),
        ("Files / Contracts / Functions",
         f"{meta_data.get('files', '?')} / {meta_data.get('contracts', '?')} / {meta_data.get('functions', '?')}"),
        ("Lines of code", meta_data.get("loc", "?")),
        ("LLM calls", meta_data.get("llm_calls", "?")),
        ("Tokens (sent / received)",
         f"{int(meta_data.get('token_sent', 0))} / {int(meta_data.get('token_received', 0))}"),
        ("Estimated cost", _fmt_cost(meta_data)),
        ("Total findings", len(results)),
    ]
    if meta_data.get("budget_exceeded"):
        header.append(("Budget guard", f"**{meta_data['budget_exceeded']}**"))
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    for k, v in header:
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # ---- findings per contract -----------------------------------------
    lines.append("## Findings by contract")
    lines.append("")
    if not results:
        lines.append("_No findings._")
        lines.append("")
    else:
        by_file = {}
        for r in results:
            by_file.setdefault(_group_file(r), []).append(r)
        for path in sorted(by_file):
            file_results = sorted(
                by_file[path],
                key=lambda r: _SEVERITY_RANK.get(str(r.get("severity", "")).lower(), 9))
            lines.append(f"### {os.path.basename(path)}")
            lines.append("")
            lines.append(f"`{path}` — {len(file_results)} finding(s)")
            lines.append("")
            for r in file_results:
                title = r.get("title", "(untitled)")
                sev = str(r.get("severity", "n/a")).upper()
                code = r.get("code", "n/a")
                clazz = _classification(title, taxonomy)
                lines.append(f"#### [{sev}] {title}")
                lines.append("")
                lines.append(f"- **Severity:** {sev}")
                lines.append(f"- **GPTScan category:** `{code}`")
                lines.append(f"- **Taxonomy:** {clazz}")
                lines.append(f"- **Affected:** {'; '.join(_affected_lines(r)) or 'n/a'}")
                lines.append(f"- **Model:** {meta_data.get('model', 'n/a')}")
                if r.get("description"):
                    lines.append(f"- **Description:** {r['description']}")
                if r.get("recommendation"):
                    lines.append(f"- **Recommendation:** {r['recommendation']}")
                lines.append("")

    # ---- aggregated summary --------------------------------------------
    lines.append("## Summary")
    lines.append("")

    # per category
    by_cat = {}
    for r in results:
        key = (r.get("title", "n/a"), r.get("code", "n/a"))
        by_cat[key] = by_cat.get(key, 0) + 1
    lines.append("### Findings per category")
    lines.append("")
    lines.append("| Category (MWE) | GPTScan code | Taxonomy | Count |")
    lines.append("| --- | --- | --- | --- |")
    if by_cat:
        for (title, code), count in sorted(by_cat.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {title} | `{code}` | {_classification(title, taxonomy)} | {count} |")
    else:
        lines.append("| _none_ | | | 0 |")
    lines.append("")

    # per contract
    by_file_count = {}
    for r in results:
        f = _group_file(r)
        by_file_count[f] = by_file_count.get(f, 0) + 1
    lines.append("### Findings per contract")
    lines.append("")
    lines.append("| Contract | Findings |")
    lines.append("| --- | --- |")
    if by_file_count:
        for f, count in sorted(by_file_count.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {os.path.basename(f)} | {count} |")
    else:
        lines.append("| _none_ | 0 |")
    lines.append("")

    # totals
    lines.append("### Totals")
    lines.append("")
    lines.append(f"- **Total findings:** {len(results)}")
    lines.append(f"- **Model:** {meta_data.get('model', 'n/a')} ({meta_data.get('provider', 'n/a')})")
    lines.append(f"- **LLM calls:** {meta_data.get('llm_calls', '?')}")
    lines.append(f"- **Estimated cost:** {_fmt_cost(meta_data)}")
    lines.append("")

    return "\n".join(lines)


def write_report(output_file: str, output_json: dict, meta_data: dict,
                 scan_rules=None) -> str:
    """Render and write the Markdown report; returns the path written."""
    md = render_markdown(output_json, meta_data)
    path = _md_path(output_file)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path
