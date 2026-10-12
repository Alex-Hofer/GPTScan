# GPTScan

## Description

Using ChatGPT for logic vulnerability detection.

## How to Use

1. Install dependencies,

- Requires Python 3.10+
- Install Python dependencies: `pip install -r requirements.txt`
- Requires Java 17+

2. Run GPTScan

Before start, please select the correct SOLC version, by running the commands:

```shell
solc-select install 0.8.19 # just an example of 0.8.19
solc-select use 0.8.19
```

For example, if the source code is stored in the `/source` directory, run the command:

```shell
# Put your key in a .env file (recommended) and run with the default backend:
python3.10 main.py -s /sourcecode -o /sourcecode/output.json
```

3. Check the output

The output results are located at the location specified by the `-o` parameter, in the example above, it is located at `/sourcecode/output.json`.

## Choosing the LLM provider / model

GPTScan talks to a single OpenAI-compatible Chat-Completions backend per run.
Two providers ship out of the box (see `src/config.py` -> `PROVIDERS`):

| Provider   | Cheap tier (default) | Strong tier        | Key (env var)      |
|------------|----------------------|--------------------|--------------------|
| `deepseek` | `deepseek-v4-flash`  | `deepseek-v4-pro`  | `DEEPSEEK_API_KEY` |
| `openai`   | `gpt-3.5-turbo`      | `gpt-4`            | `OPENAI_API_KEY`   |

The default backend is **`deepseek` / `deepseek-v4-flash`**.

API keys are read from the environment, ideally a `.env` file (copy
`.env.example` -> `.env`; `.env` is git-ignored). `-k` still works as a one-off
override for the selected provider.

```shell
# DeepSeek (default) — key taken from .env
python3.10 main.py -s /sourcecode -o out.json

# Explicit provider + model
python3.10 main.py -s /sourcecode -o out.json --provider deepseek --model deepseek-v4-pro

# Keep using OpenAI (unchanged behaviour)
python3.10 main.py -s /sourcecode -o out.json --provider openai --model gpt-4o
```

After every scan the summary prints the provider, model, number of LLM calls,
tokens, and the estimated cost (also stored in `<output>.metadata.json`).
Adding another OpenAI-compatible provider only means adding an entry to
`PROVIDERS` (base URL, key env var, model tiers, prices).

### Estimating cost before you spend — `--dry-run`

A full scan can issue **hundreds of LLM calls per contract**. To see how many
calls and roughly how much a scan would cost **without making any network call**
(no API key needed), use `--dry-run`:

```shell
python3.10 main.py -s /sourcecode -o out.json --dry-run
```

The figures are a conservative upper bound (every scenario is assumed to match).
Optional hard guards `MAX_LLM_CALLS` / `MAX_COST_USD` in `src/config.py` stop a
live scan from issuing further calls once a limit is hit.

> The DeepSeek prices in `src/config.py` are the official rates (v4-flash
> $0.14 in / $0.28 out, v4-pro $1.74 in / $3.48 out, USD per 1M tokens).

## Supported Project Types

Currently supported project types include:
- Single file in a folder, i.e., `contract` folder with a single `example.sol` file. Use the path of folder as source (**NOT THE FILE, WHICH MAY CAUSE ERRORS.**)
- ~~Multi-file, i.e., a directory with multiple `.sol` files, without any other external dependencies~~
- Common framework projects, such as Truffle, Hardhat, Brownie, etc.

Tested frameworks include:
- Hardhad
- Truffle
- Brownie

Note that this project does not include the compilation environment, such as Node.js, which needs to be installed separately.

**NOTE**: Please also make sure that you path do not contain keywords like `external`, `openzeppelin`, `uniswap`, `pancakeswap`, `legacy`, since we are using a naive way to match the path. Find more in `src/antlr4helper/callgraph.py:__parse_all_files`. It will not have explict error messages, but will cause empty output.

## Dataset

Dataset used to evaluate GPTScan in the paper, are the following:
1. Web3Bugs: [https://github.com/MetaTrustLabs/GPTScan-Web3Bugs](https://github.com/MetaTrustLabs/GPTScan-Web3Bugs)
2. DefiHacks: [https://github.com/MetaTrustLabs/GPTScan-DefiHacks](https://github.com/MetaTrustLabs/GPTScan-DefiHacks)
3. Top200: [https://github.com/MetaTrustLabs/GPTScan-Top200](https://github.com/MetaTrustLabs/GPTScan-Top200)

## How to Cite this project

```bibtex
@inproceedings{sun2024gptscan,
    author = {Sun, Yuqiang and Wu, Daoyuan and Xue, Yue and Liu, Han and Wang, Haijun and Xu, Zhengzi and Xie, Xiaofei and Liu, Yang},
    title = {{GPTScan}: Detecting Logic Vulnerabilities in Smart Contracts by Combining GPT with Program Analysis},
    year = {2024},
    isbn = {9798400702174},
    publisher = {Association for Computing Machinery},
    address = {New York, NY, USA},
    url = {https://doi.org/10.1145/3597503.3639117},
    doi = {10.1145/3597503.3639117},
    booktitle = {Proceedings of the IEEE/ACM 46th International Conference on Software Engineering},
    articleno = {166},
    numpages = {13},
    series = {ICSE '24}
}
```
