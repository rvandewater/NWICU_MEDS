"""Code metadata: every code family is described, and the LOINC parent table stays sourced.

The config tests need no data. ``test_built_codes_metadata`` checks a finished extraction and runs
only when ``NWICU_MEDS_OUTPUT_DIR`` points at one (the synthetic-ETL workflow sets it).
"""

import csv
import os
import re
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml
from meds import CodeMetadataSchema

from NWICU_MEDS import MESSY_CFG

LOINC_CSV = Path(str(MESSY_CFG)).parent / "metadata" / "loinc_parents.csv"
# The dictionary block of each event whose codes get an inferred LOINC parent, by the CSV's
# `source_table` value.
LOINC_BLOCKS = {
    "labevents": ("data/nw_hosp/labevents", "lab", "data/nw_hosp/d_labitems"),
    "chartevents": ("data/nw_icu/chartevents", "event", "data/nw_icu/d_items"),
}
LOINC_BRANCH = re.compile(r'"LOINC/([0-9]{1,5}-[0-9])" if \$itemid::str == "([0-9]+)"')


@pytest.fixture(scope="module")
def raw_cfg() -> dict:
    return yaml.safe_load(Path(str(MESSY_CFG)).read_text())


@pytest.fixture(scope="module")
def loinc_rows() -> list[dict]:
    with LOINC_CSV.open(newline="") as f:
        return list(csv.DictReader(f))


def _events(raw_cfg: dict):
    for table, body in raw_cfg.items():
        if table in ("sources", "etl", "_defaults"):
            continue
        for name, event in body.items():
            if not name.startswith("_"):
                yield table, name, event


def _family(table_body: dict, code: str) -> str:
    """The constant part of a code expression: the f-string prefix, or the literal it emits."""
    code = code.strip()
    if m := re.fullmatch(r"\$(\w+)", code):  # a constant `_table.cols` column
        code = table_body["_table"]["cols"][m.group(1)]
    if m := re.match(r"""f?["']([A-Z_]+)""", code):
        return m.group(1)
    return code


def test_every_code_family_is_described(raw_cfg: dict):
    """Each family the config emits is described by at least one event's metadata block."""
    families, described = set(), set()
    for table, _name, event in _events(raw_cfg):
        family = _family(raw_cfg[table], str(event["code"]))
        families.add(family)
        if any("description" in block for block in event.get("_metadata", {}).values()):
            described.add(family)
    assert {"MEDICATION", "LAB", "MEDS_BIRTH", "MEDS_DEATH", "ED_OUT"} <= families
    assert families == described, (
        f"undescribed code families: {sorted(families - described)}"
    )


def test_loinc_table_is_complete_and_sourced(loinc_rows: list[dict]):
    assert loinc_rows
    keys = [(r["source_table"], r["itemid"]) for r in loinc_rows]
    assert len(keys) == len(set(keys))
    for r in loinc_rows:
        assert r["source_table"] in LOINC_BLOCKS, r
        assert re.fullmatch(r"[0-9]+", r["itemid"]), r
        assert re.fullmatch(r"[0-9]{1,5}-[0-9]", r["loinc_code"]), r
        # Every parent is a bridge across two curated mappings, so it must say so.
        assert r["source"].startswith("inferred: weavehr:"), r
        assert r["source_detail"], r


def test_loinc_expressions_match_the_table(raw_cfg: dict, loinc_rows: list[dict]):
    for source_table, (prefix, event, dictionary) in LOINC_BLOCKS.items():
        expr = raw_cfg[prefix][event]["_metadata"][dictionary]["parent_codes"]
        branches = LOINC_BRANCH.findall(expr)
        assert len(branches) == expr.count(" if "), (
            f"unparsed branch in the {prefix} parent_codes"
        )
        expected = [
            (r["loinc_code"], r["itemid"])
            for r in loinc_rows
            if r["source_table"] == source_table
        ]
        assert branches == expected, prefix


@pytest.mark.skipif(
    "NWICU_MEDS_OUTPUT_DIR" not in os.environ, reason="no finished extraction to check"
)
def test_built_codes_metadata():
    """A finished extraction is valid MEDS code metadata with every code described.

    Failure messages report counts only, never codes, so this is safe to run on a credentialed build.
    """
    codes_fp = Path(os.environ["NWICU_MEDS_OUTPUT_DIR"]) / "metadata" / "codes.parquet"
    table = pq.read_table(codes_fp)
    CodeMetadataSchema.validate(table)
    df = table.to_pydict()
    assert df["code"], "codes.parquet is empty"
    n_undescribed = sum(not d for d in df["description"])
    assert n_undescribed == 0, (
        f"{n_undescribed} of {len(df['code'])} codes have no description"
    )
    # `<vocabulary>/<code>`; the vocabulary is not pinned, since synthetic data feeds it arbitrary values.
    n_malformed = sum(
        not re.fullmatch(r"\w+/\S+", p) for ps in df["parent_codes"] if ps for p in ps
    )
    assert n_malformed == 0, (
        f"{n_malformed} parent codes are not of the form <vocabulary>/<code>"
    )
