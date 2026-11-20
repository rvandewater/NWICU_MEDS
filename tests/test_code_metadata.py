"""Code metadata: every code family is described, and vocabulary links stay out of the ETL.

The config tests need no data. ``test_built_codes_metadata`` checks a finished extraction and runs
only when ``NWICU_MEDS_OUTPUT_DIR`` points at one (the synthetic-ETL workflow sets it).
"""

import os
import re
from pathlib import Path

import polars as pl
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

    The one exception is by design: the row of a unit-sibling stem has no description when its
    siblings share none, even without their unit (suMEDS's `sumeds_link_unit_siblings`). That does
    not happen in the real release, but MESSY-synth gives one item id several labels, so the
    synthetic build has such stems. Each undescribed code must be one of them: a code that another
    code, itself followed by `//<unit>`, lists as its parent.

    Failure messages report counts only, never codes, so this is safe to run on a credentialed build.
    """
    codes_fp = Path(os.environ["NWICU_MEDS_OUTPUT_DIR"]) / "metadata" / "codes.parquet"
    table = pq.read_table(codes_fp)
    CodeMetadataSchema.validate(table)
    df = table.to_pydict()
    assert df["code"], "codes.parquet is empty"
    undescribed = {
        c for c, d in zip(df["code"], df["description"], strict=True) if not d
    }
    stems = {
        parent
        for code, parents in zip(df["code"], df["parent_codes"], strict=True)
        for parent in parents or ()
        if code.startswith(f"{parent}//") and "//" not in code[len(parent) + 2 :]
    }
    stems_without_description = undescribed & stems
    n_undescribed = len(undescribed - stems_without_description)
    assert n_undescribed == 0, (
        f"{n_undescribed} of {len(df['code'])} codes have no description "
        f"(not counting {len(undescribed & stems_without_description)} unit-sibling stems whose "
        "siblings share no description)"
    )
    # `<vocabulary>/<code>`; the vocabulary is not pinned, since synthetic data feeds it arbitrary values.
    # The other parents are in-dataset: the code without the unit, of codes that differ only in
    # their unit (test_unit_siblings_get_their_stem_as_parent_and_row).
    in_dataset = set(df["code"])
    n_malformed = sum(
        not re.fullmatch(r"\w+/\S+", p) and p not in in_dataset
        for ps in df["parent_codes"]
        if ps
        for p in ps
    )
    assert n_malformed == 0, (
        f"{n_malformed} parent codes are not of the form <vocabulary>/<code>"
    )


def test_numeric_codes_carry_their_recorded_unit(codes):
    """Lab, chart and prescription-start codes get a `unit` column with the unit as recorded,
    written in UCUM.

    The unit as recorded is also the code's last segment, so it is one value per code; a code whose
    unit is null (`//UNK`) gets no unit. MEDS-Extract writes it as one string per code; suMEDS's
    `sumeds_normalize_units` then writes it in UCUM and keeps the spelling as recorded in
    `unit_source_value`. The code keeps its name.
    """
    assert codes.schema["unit"] == pl.String
    units = dict(codes.select("code", "unit").iter_rows())
    recorded = dict(codes.select("code", "unit_source_value").iter_rows())
    # code -> (unit in UCUM, unit as recorded)
    expected = {
        "LAB//900001//mg/dL": ("mg/dL", "mg/dL"),  # labevents
        "LAB//900002//mEq/L": ("meq/L", "mEq/L"),
        "LAB//800001//bpm": ("{beats}/min", "bpm"),  # chartevents
        "MEDICATION//START//Synthetic drug A//PO//mg": ("mg", "mg"),  # prescriptions
        "MEDICATION//START//Synthetic drug C//IV//mL": ("mL", "mL"),
    }
    for code, unit in expected.items():
        assert (units[code], recorded[code]) == unit, code
    assert units["LAB//900003//UNK"] is None
    # Codes without a numeric value carry no unit.
    assert units["GENDER//F"] is None
    assert units["MEDICATION//END//Synthetic drug A//PO"] is None
    # Labels still come from the item dictionaries next to the `_self` unit block.
    descriptions = dict(codes.select("code", "description").iter_rows())
    assert descriptions["LAB//900001//mg/dL"] == "Synthetic lab A"
    assert descriptions["LAB//800001//bpm"] == "Synthetic chart item A"


def test_unit_siblings_get_their_stem_as_parent_and_row(codes):
    """Codes that differ only in their unit share the code without the unit as parent, and that
    code gets a row: no unit, the description its siblings share (without their unit, where that
    is the only difference) and the parents they all have."""
    rows = {row["code"]: row for row in codes.iter_rows(named=True)}
    lab = "LAB//900001"
    for code in (f"{lab}//mg/dL", f"{lab}//mmol/L"):
        assert rows[code]["parent_codes"] == [lab], code
    assert rows[lab]["unit"] is None
    assert rows[lab]["description"] == "Synthetic lab A"
    assert not rows[lab]["parent_codes"]

    drug = "MEDICATION//START//Synthetic drug A//PO"
    for code in (f"{drug}//mg", f"{drug}//mcg"):
        assert rows[code]["parent_codes"] == ["NDC/12345678901", drug], code
    assert rows[drug]["unit"] is None
    assert rows[drug]["parent_codes"] == ["NDC/12345678901"]
    assert rows[drug]["description"] == (
        "Prescription start: Synthetic drug A; route: PO; dose unit: (NWICU prescriptions.drug, "
        "route, dose_unit_rx; numeric_value is prescriptions.dose_val_rx)"
    )
    # A unit-suffixed code without a sibling gets neither.
    assert "LAB//900002" not in rows
    assert not rows["LAB//900002//mEq/L"]["parent_codes"]
