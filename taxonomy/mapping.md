# GPTScan weakness taxonomy mapping

GPTScan detects **DeFi logic vulnerabilities**, a class largely outside the
classic bytecode-level weakness registries. This document records which of its
detectors map onto an established taxonomy (the [SWC Registry](https://swcregistry.io)
and the [DASP Top 10](https://dasp.co)) and which are intentionally left as
business-logic findings.

The machine-readable mapping is [`findings.yaml`](./findings.yaml) (SmartBugs
format). The SmartBugs tool integration copies it to `tools/gptscan/findings.yaml`,
where `parser.py` emits finding names equal to GPTScan's `output.title`
(`MWE-200: ...`) and SmartBugs merges in the `classification`, `severity`, and
descriptions from this file.

## The 10 detectors

GPTScan ships exactly 10 rules (`src/rules/*.yml`), labelled MWE-200..209. Each
rule is a *scenario* (a natural-language property the LLM matches against a
function) plus a *static-analysis confirmation* step.

| MWE | GPTScan code | Title | Classification | Static check |
|-----|--------------|-------|----------------|--------------|
| 200 | price-manipulation | Insecure LP Token Value Calculation | BUSINESS-LOGIC | find_data_dependency |
| 201 | insecure-vote-calculation | Insecure Vote Calculation | BUSINESS-LOGIC | find_data_dependency |
| 202 | insecure-buying-behavior | Insecure Token Buying Behavior | BUSINESS-LOGIC (rel. DASP-7/SWC-114) | in_code |
| 203 | approval-not-clear | Approval Not Revoked | BUSINESS-LOGIC | check_require |
| 204 | first-deposit | Unsafe First Deposit | BUSINESS-LOGIC | first_deposit_check |
| 205 | front-running | Front Running | **SWC-114, DASP-7** | call_arg_check |
| 206 | no-slippage-limit-check | No Slippage Limit Check | BUSINESS-LOGIC (rel. DASP-7/SWC-114) | has_min_check |
| 207 | unauthorized-transfer | Unauthorized Transfer | **DASP-2** | has_eq_check |
| 208 | wrong-order-checkpoint | Wrong Order for Checkpoint | BUSINESS-LOGIC | order_first_b |
| 209 | wrong-order-interest | Wrong Order for Interest/ExchangeRate | BUSINESS-LOGIC | order_first_b |

## Mapping rationale

**Cleanly mapped (2):**

- **MWE-205 Front Running -> SWC-114 (Transaction Order Dependence) + DASP-7
  (Front-Running).** Assigning a minted/collected benefit to a caller-controlled
  address with no sender check is the textbook transaction-ordering weakness.
- **MWE-207 Unauthorized Transfer -> DASP-2 (Access Control).** Pulling tokens
  from an address other than `msg.sender` without an allowance check is a
  missing-authorization (access-control) flaw. There is no exact SWC entry for a
  missing ERC20 allowance check, so only DASP is assigned.

**Deliberately business-logic (8).** Flash-loan price/vote manipulation
(200, 201), AMM buy/slippage sandwich exposure (202, 206), ERC20 approval
lifecycle (203), ERC4626 first-deposit inflation (204), and intra-function
state-update ordering (208, 209) describe *protocol economic logic*, not a
bytecode-level weakness. SWC/DASP have no faithful entry for them, so they are
marked `BUSINESS-LOGIC (no SWC/DASP)` rather than force-fitted. For 202 and 206
a `related:` note records the loose link to transaction-ordering (DASP-7 /
SWC-114) without claiming the label.

This honesty is the point of the exercise: GPTScan's value is exactly the
business-logic class that signature/bytecode tools in SmartBugs do **not**
cover, so the mapping must make that gap explicit instead of hiding it behind an
approximate SWC id.

## Severity

GPTScan itself reports every finding as `HIGH`. In `findings.yaml` we refine
this into an impact-based split: direct fund-loss / critical detectors
(200, 201, 204, 205, 207) are `high`; the conditional or lower-impact ones
(202, 203, 206, 208, 209) are `medium`. The parser can still pass through
GPTScan's own severity if preferred.
