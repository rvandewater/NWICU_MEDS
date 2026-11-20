"""A code's unit segment is the row's unit stripped, and `UNK` when it is missing or blank.

MEDS-Extract compares units stripped and drops blank ones when it writes `codes.parquet`, so a
code that kept the whitespace would split one unit over several codes (` mg`, `mg`, `mg `), and a
blank one would give a code ending in whitespace (or in `//`) with no unit. The expressions are
evaluated straight from the shipped config with dftly, as MEDS-Extract evaluates them.
"""

from pathlib import Path

import polars as pl
import pytest
import yaml
from dftly import Parser

CONFIG_FP = Path(__file__).parents[1] / "src" / "NWICU_MEDS" / "messy.yaml"

UNITS = ["mg", " mg", "mg ", "\tmg\n", "mL / h", "  ", "", None]
EXPECTED = ["mg", "mg", "mg", "mg", "mL / h", "UNK", "UNK", "UNK"]

# (table, event, unit helper, raw unit column, other code columns, code prefix)
CASES = [
    (
        "data/nw_hosp/labevents",
        "lab",
        "_value_unit",
        "valueuom",
        {"itemid": "900001"},
        "LAB//900001//",
    ),
    (
        "data/nw_icu/chartevents",
        "event",
        "_value_unit",
        "valueuom",
        {"itemid": "800001"},
        "LAB//800001//",
    ),
    (
        "data/nw_hosp/prescriptions",
        "prescription_start",
        "_dose_unit",
        "dose_unit_rx",
        # The route is not a unit and is kept as recorded.
        {"drug": "Drug A", "route": " PO"},
        "MEDICATION//START//Drug A// PO//",
    ),
]


@pytest.mark.parametrize("table,event,helper,column,other,prefix", CASES)
def test_unit_segment_is_stripped_and_blank_is_unk(
    table, event, helper, column, other, prefix
):
    block = yaml.safe_load(CONFIG_FP.read_text())[table]
    raw = pl.DataFrame(
        {column: UNITS, **{k: [v] * len(UNITS) for k, v in other.items()}},
        schema_overrides={column: pl.String},
    )
    with_cols = raw.with_columns(
        **Parser.to_polars({helper: block["_table"]["cols"][helper]})
    )
    codes = with_cols.select(**Parser.to_polars({"code": block[event]["code"]}))[
        "code"
    ].to_list()
    assert codes == [prefix + unit for unit in EXPECTED]
    # `unit` stays the raw column; MEDS-Extract strips it when it writes `codes.parquet`.
    assert block[event]["_metadata"]["_self"]["unit"] == f"${column}"
