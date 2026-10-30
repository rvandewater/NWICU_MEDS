"""Code metadata: every code family is described, and vocabulary links stay out of the ETL.

The config tests need no data. ``test_built_codes_metadata`` checks a finished extraction and runs
only when ``NWICU_MEDS_OUTPUT_DIR`` points at one (the synthetic-ETL workflow sets it).
"""

import os
import re
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml
from meds import CodeMetadataSchema

from NWICU_MEDS import MESSY_CFG

# The dictionary blocks of the two events that emit `LAB//{itemid}//{unit}` codes.
LAB_BLOCKS = {
    "data/nw_hosp/labevents": ("lab", "data/nw_hosp/d_labitems"),
    "data/nw_icu/chartevents": ("event", "data/nw_icu/d_items"),
}


@pytest.fixture(scope="module")
def raw_cfg() -> dict:
    return yaml.safe_load(Path(str(MESSY_CFG)).read_text())


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


def test_lab_codes_get_no_vocabulary_parents_from_the_etl(raw_cfg: dict):
    """NWICU records no LOINC code; the itemid -> LOINC crosswalk is applied by suMEDS.

    The rules are in ``sumeds_rules.yaml`` (crosswalk ``nwicu/loinc_parents``), so the
    dictionary blocks carry descriptions only.
    """
    for prefix, (event, dictionary) in LAB_BLOCKS.items():
        block = raw_cfg[prefix][event]["_metadata"][dictionary]
        assert block["description"] == "$label"
        assert "parent_codes" not in block, prefix


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
