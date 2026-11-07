# Contributing

This repository is a **MEDS-Extract 0.8 ETL**. All of it is two declarative files: the MESSY
config and the suMEDS rules that enrich its code metadata. There is no Python to change.

```bash
pip install NWICU_MEDS
export DATASET_DOWNLOAD_USERNAME=$PHYSIONET_USERNAME
export DATASET_DOWNLOAD_PASSWORD=$PHYSIONET_PASSWORD

suMEDS-extract spec=NWICU output_dir=$ROOT_OUTPUT_DIR
```

## What the 0.7 layout looks like

Under MEDS-Transforms 0.2.x an ETL was a Python package: `pre_MEDS.py` reshaped the raw data,
`dataset.yaml` described the download, `ETL.yaml` listed the pipeline stages, and
`event_configs.yaml` described the events. **0.7 replaces all four with a single MESSY file**
(MEDS-Extract Specification Syntax YAML):

| Used to be                     | Now                                                                       |
| ------------------------------ | ------------------------------------------------------------------------- |
| `dataset.yaml` + `download.py` | the `sources:` block                                                      |
| `configs/ETL.yaml`             | nothing — the stage sequence is canonical and not configurable            |
| `configs/event_configs.yaml`   | the event tables, written in [dftly](https://github.com/mmcdermott/dftly) |
| `pre_MEDS.py`                  | `_table.joins` / `_table.cols`                                            |

The file lives at [`src/NWICU_MEDS/messy.yaml`](src/NWICU_MEDS/messy.yaml) and is registered
under the `MEDS_extract.pipelines` entry-point group in `pyproject.toml`:

```toml
[project.entry-points."MEDS_extract.pipelines"]
NWICU = "NWICU_MEDS:messy.yaml"

[project.entry-points."sumeds.rules"]
NWICU = "NWICU_MEDS:sumeds_rules.yaml"
```

Those values are **parsed, not imported** — each names a package and a data file inside it, which
is why they do not look like normal `module:attribute` targets. The suMEDS rules
([`src/NWICU_MEDS/sumeds_rules.yaml`](src/NWICU_MEDS/sumeds_rules.yaml)) are registered under the
same name as the spec, which is how `suMEDS-extract spec=NWICU` finds them.

## Editing the config

Three things bite newcomers, in rough order of how often:

1. **`$` is load-bearing.** `$value` reads the `value` column; a bare `value` is the string
    literal `"value"`. This fails silently — wrong data, no error.
2. **A null code component drops the row.** `f"LAB//{$item}"` discards every row with a null
    `item`. Coalesce with `?? 'UNK'` when the row must be kept. 0.6.x rendered nulls as `UNK`
    automatically; 0.7 does not.
3. **There is no null test.** dftly has no `is_null`. The working idiom is `X if $c == $c`, which
    is true for any present value (including `0`, `inf` and `NaN`) and null for a missing one.
    A bare `null` parses as the *string* `"null"`. Tracked in
    [dftly#113](https://github.com/mmcdermott/dftly/issues/113).

Also worth knowing: `_table.joins` may name several tables, each its own left join applied in
order (0.7 called the key `_table.join` and allowed one), `_table.cols` entries are evaluated in
order so later ones may reference earlier ones, and adding a Duration to a Datetime must be
written as `anchor - (-$offset)::minutes` because `+` does not lower correctly.

## Testing

```bash
uv sync --extra tests
uv run pytest tests/
uv run pre-commit run --all-files
```

There is no demo release for NWICU, and the credentialed download cannot run in CI. The suite
therefore parses the config, checks the suMEDS rules, and runs `meds-extract-run spec=NWICU` and
`suMEDS-extract spec=NWICU` end to end over a tiny synthetic release
([`tests/conftest.py`](tests/conftest.py)), offline against a synthetic ontology pack
([`tests/test_run_with_enrichment.py`](tests/test_run_with_enrichment.py)). Changes that affect
the output should still be validated by running the ETL over the real release and comparing the
summary statistics before and after (see "Summary statistics" in the README).

## Changing what the ETL emits

Any change to codes, timestamps or which rows are emitted is a change to everybody's downstream
cohort. State the measured effect in the PR — row counts, subject counts, code-vocabulary size
before and after — rather than only describing the intent. Several defects in this repository were
found precisely because those numbers were compared.

# Development

## Environment

The project uses [uv](https://docs.astral.sh/uv/) for its environment, lockfile,
build, and commands.

```bash
uv sync --extra tests
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest
uv run mkdocs build --strict
```

A plain `pre-commit run` checks only staged files, so hooks legitimately skip
when nothing matching is staged. Use `--all-files` for a full repository check.

Build the distribution with:

```bash
uv build
```

## Release

Bump and commit the project version before creating the matching tag:

```bash
uv version --bump patch
uv run pytest
uv build --clear
git add pyproject.toml uv.lock
git commit -m "Release $(uv version --short)"
VERSION=$(uv version --short)
git tag -a "$VERSION" -m "Release $VERSION"
git push origin main "$VERSION"
```

The tag workflow rejects mismatched versions, then publishes the distributions
to PyPI and creates the GitHub release.

```bash
uv sync --extra tests
uv version --bump patch   # 0.0.12 → 0.0.13
uv version --bump minor   # 0.0.12 → 0.1.0
uv version --bump major   # 0.0.12 → 1.0.0
```
