"""Validate the bundled MESSY config against the installed MEDS-Extract.

These tests need no raw data and no credentials, so they run in CI on every push. They are the
regression net for the 0.7 migration: a MESSY file that stops parsing (a bad dftly expression, a
stray 0.6.x key, an `etl:` option MEDS-Extract does not accept) fails here rather than several
stages into a multi-hour extraction run.
"""

import pytest

from MEDS_extract.config import MessyConfig

from NWICU_MEDS import MESSY_CFG, PIPELINE_NAME

EXPECTED_TABLES = {
    "nw_hosp/admissions": {"ed_registration", "ed_out", "admission", "discharge"},
    "nw_hosp/diagnoses_icd": {"diagnosis"},
    "nw_hosp/emar": {"medication"},
    "nw_hosp/labevents": {"lab"},
    "nw_hosp/patients": {"gender", "dob", "death"},
    "nw_icu/icustays": {"icu_admission", "icu_discharge"},
    "nw_icu/chartevents": {"event"},
    "nw_icu/procedureevents": {"start", "end"},
}


@pytest.fixture(scope="module")
def cfg() -> MessyConfig:
    return MessyConfig.load(MESSY_CFG)


@pytest.fixture(scope="module")
def by_prefix(cfg: MessyConfig) -> dict:
    return {t.input_prefix: t for t in cfg.event_tables}


def events(table) -> dict:
    return {e.name: e for e in table.events}


def test_messy_config_parses(cfg: MessyConfig):
    """Every event table, code expression, and time cast in the config is valid dftly."""
    tables = cfg.event_tables
    assert tables, "MESSY config declares no event tables."
    for table in tables:
        assert table.events, f"Table {table.input_prefix!r} declares no events."


def test_expected_tables_and_events(by_prefix: dict):
    """The migrated config covers exactly the tables the 0.6.x event config covered."""
    assert {p: {e.name for e in t.events} for p, t in by_prefix.items()} == EXPECTED_TABLES


def test_subject_id_is_subject_id(cfg: MessyConfig):
    """Every table inherits the global `_defaults.subject_id`."""
    for table in cfg.event_tables:
        assert table.subject_id_node is not None, table.input_prefix
        assert table.subject_id_node.referenced_columns == {"subject_id"}


def test_extra_output_columns_are_column_reads(by_prefix: dict):
    """Non-code output columns read raw columns, not bare-string literals.

    The 0.6.x config wrote `insurance: insurance`, meaning "read the `insurance` column". A bare
    string is a LITERAL in dftly, so these must all carry a `$`. Getting this wrong stamps a
    constant string into every row rather than raising, so it is worth pinning.
    """
    admission = events(by_prefix["nw_hosp/admissions"])["admission"]
    assert {"insurance", "language", "marital_status", "race", "hadm_id"} <= (
        admission.referenced_columns
    )

    lab = events(by_prefix["nw_hosp/labevents"])["lab"]
    assert {"valuenum", "value", "priority"} <= lab.referenced_columns


def test_multi_format_death_time_is_a_coalesce(by_prefix: dict):
    """The 0.6.x list-valued `time_format` becomes a coalesce of lenient parses.

    Each row takes the first format that matches; rows matching none are dropped and counted in
    the extraction logs rather than leaking a null time downstream.
    """
    death = events(by_prefix["nw_hosp/patients"])["death"]
    assert death.referenced_columns == {"dod"}


def test_metadata_blocks_produce_their_join_keys(by_prefix: dict):
    """Each `_metadata` block explicitly produces the code components it joins on.

    0.6.x inferred join keys implicitly from the code expression; 0.7.0 requires them to be
    produced by the block, and a block producing no component-named column is a config error.
    """
    dx = events(by_prefix["nw_hosp/diagnoses_icd"])["diagnosis"]
    dx_md = dx.metadata["nw_hosp/d_icd_diagnoses"]
    assert {"icd_version", "icd_code"} <= set(dx_md)
    assert "description" in dx_md
    assert "parent_codes" in dx_md

    # Partial matches: only `itemid` of the code's (itemid, valueuom) components is produced, so
    # the label broadcasts across every unit variant.
    for prefix, event_name, source in (
        ("nw_hosp/labevents", "lab", "nw_hosp/d_labitems"),
        ("nw_icu/chartevents", "event", "nw_icu/d_items"),
        ("nw_icu/procedureevents", "start", "nw_icu/d_items"),
        ("nw_icu/procedureevents", "end", "nw_icu/d_items"),
    ):
        md = events(by_prefix[prefix])[event_name].metadata[source]
        assert "itemid" in md, (prefix, event_name)
        assert "description" in md, (prefix, event_name)


def test_no_match_on_keys_remain(cfg: MessyConfig):
    """`_match_on` was removed in 0.7.0; a leftover key raises at config load."""
    for table in cfg.event_tables:
        for event in table.events:
            for source, block in (event.metadata or {}).items():
                assert "_match_on" not in block, (table.input_prefix, event.name, source)


def test_etl_block(cfg: MessyConfig):
    """The reserved `etl:` block carries the dataset identity and stage options."""
    assert cfg.etl.dataset_name == "NWICU"
    assert cfg.etl.stage_options["n_subjects_per_shard"] == 1000


def test_sources_declare_dataset_version(cfg: MessyConfig):
    """`sources.dataset_version` is what stamps `etl_metadata.dataset_version` on the output."""
    assert cfg.sources_version == "0.1.0"


def test_registered_pipeline_name_resolves():
    """The `MEDS_extract.pipelines` entry point resolves to the bundled MESSY file.

    This is what makes `meds-extract-run spec=NWICU output_dir=...` work.
    """
    cfg = MessyConfig.load(PIPELINE_NAME)
    assert cfg.registered_name == PIPELINE_NAME
    assert [t.input_prefix for t in cfg.event_tables]
