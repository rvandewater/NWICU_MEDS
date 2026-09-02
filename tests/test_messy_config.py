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
    "data/nw_hosp/admissions": {
        "admission",
        "death_untimed",
        "discharge",
        "ed_out",
        "ed_registration",
        "insurance",
        "language",
        "marital_status",
        "race",
    },
    "data/nw_hosp/diagnoses_icd": {"diagnosis"},
    "data/nw_hosp/emar": {"medication"},
    "data/nw_hosp/labevents": {"lab"},
    "data/nw_hosp/patients": {"death", "dob", "gender"},
    "data/nw_hosp/prescriptions": {"prescription_start", "prescription_stop"},
    "data/nw_icu/icustays": {"icu_admission", "icu_discharge"},
    "data/nw_icu/chartevents": {"event"},
    "data/nw_icu/procedureevents": {"end", "start"},
}


@pytest.fixture(scope="module")
def cfg() -> MessyConfig:
    return MessyConfig.load(MESSY_CFG)


@pytest.fixture(scope="module")
def by_prefix(cfg: MessyConfig) -> dict:
    return {t.input_prefix: t for t in cfg.event_tables}


@pytest.fixture
def dummy_credentials(monkeypatch):
    """Satisfy the `${oc.env:...}` interpolations in the `sources:` block.

    `selected_sources()` resolves interpolations for the selected bucket, so inspecting the
    declared sources needs the credential vars to exist. The values are never used -- nothing here
    touches the network -- but without this the test only passes on a machine that happens to have
    real credentials exported.
    """
    monkeypatch.setenv("DATASET_DOWNLOAD_USERNAME", "not-a-real-user")
    monkeypatch.setenv("DATASET_DOWNLOAD_PASSWORD", "not-a-real-password")


def test_messy_config_parses(cfg: MessyConfig):
    """Every event table, code expression, and time cast in the config is valid dftly."""
    tables = cfg.event_tables
    assert tables, "MESSY config declares no event tables."
    for table in tables:
        assert table.events, f"Table {table.input_prefix!r} declares no events."


def test_expected_tables_and_events(by_prefix: dict):
    """The config covers NWICU 0.1.0's hospital and ICU event tables."""
    assert {
        p: {e.name for e in t.events} for p, t in by_prefix.items()
    } == EXPECTED_TABLES


def test_subject_id_is_nwicu_subject_id(cfg: MessyConfig):
    """Every NWICU table inherits the global `_defaults.subject_id`."""
    for table in cfg.event_tables:
        assert table.subject_id_node is not None, table.input_prefix
        assert table.subject_id_node.referenced_columns == {"subject_id"}


def test_value_columns_are_column_reads(by_prefix: dict):
    """`numeric_value`/`text_value` read columns, not bare-string literals.

    A bare string is a LITERAL in dftly, so every raw-column read must carry a `$` prefix. This
    fails silently (wrong data, no error) rather than loudly, so it is worth pinning.
    """
    lab = by_prefix["data/nw_hosp/labevents"].events[0].referenced_columns
    assert {"valuenum", "value"} <= lab

    chart_event = by_prefix["data/nw_icu/chartevents"].events[0].referenced_columns
    assert {"valuenum", "value"} <= chart_event


def test_physionet_source_targets_nwicu_release(cfg: MessyConfig, dummy_credentials):
    """The download source is NWICU 0.1.0, not a MIMIC release."""
    sources = cfg.selected_sources("dataset")
    assert len(sources) == 1
    assert getattr(sources[0], "_base_url", None) == (
        "https://physionet.org/files/nwicu-northwestern-icu/0.1.0/"
    )


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
