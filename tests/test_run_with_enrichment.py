"""`suMEDS-extract spec=NWICU` runs the ETL and then suMEDS enrichment, offline.

This package registers its rules in suMEDS's `sumeds.rules` entry-point group under the same name
as its MEDS-Extract spec, so `suMEDS-extract` finds them from `spec=NWICU` alone. The ontology
source is a tiny pack repository in suMEDS's `sumeds-ontologies/0.1` layout, built here with
made-up titles for the synthetic codes of ``conftest.py`` (and their ancestors), plus a synthetic
`nwicu/loinc_parents` crosswalk table, so the test reads nothing over the network and does not
depend on the published packs. Another run points at an empty pack source, which is how a site
without internet fails: the ETL still succeeds, unenriched, and `suMEDS-enrich` completes it later.
"""

import csv
import hashlib
import io
import json
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from conftest import run_command
from meds import CodeMetadataSchema, DatasetMetadataSchema

# vocabulary -> release -> code -> parent (None for a top-level code). ICD-10-CM R46.89 is
# deliberately missing, so DIAGNOSIS//ICD//10//R4689 keeps only what the ETL gave it.
PACKS = {
    "ICD10CM": (
        "fy2016-fy2027",
        {
            "E11": None,
            "E11.9": "E11",
            "I50": None,
            "I50.2": "I50",
            "I50.23": "I50.2",
        },
    ),
    "ICD9CM": (
        "v32",
        {
            "401": None,
            "401.9": "401",
            "E888": None,
            "E888.9": "E888",
        },
    ),
    # LOINC codes are terms without parents in the pack (their Parts are a separate hierarchy).
    "LOINC": ("2.83", {"2160-0": None, "8867-4": None}),
}

# itemid -> source table, LOINC code. 900002's LOINC code is not in the pack, so the crosswalk
# candidate does not validate and LAB//900002//mEq/L stays unenriched; 900003 has no row at all.
CROSSWALK = {
    "900001": ("labevents", "2160-0"),
    "900002": ("labevents", "2951-2"),
    "800001": ("chartevents", "8867-4"),
}


def title(vocabulary: str, code: str) -> str:
    return f"Synthetic {vocabulary} title {code}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _csv(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue().encode()


@pytest.fixture(scope="session")
def ontology_source(tmp_path_factory) -> Path:
    """A local `sumeds-ontologies/0.1` repository: synthetic ICD and LOINC packs, one crosswalk."""
    root = tmp_path_factory.mktemp("ontologies")
    columns = ["code", "description", "parent"]
    vocabularies = {}
    for vocabulary, (release, rows) in PACKS.items():
        directory = root / vocabulary / release
        directory.mkdir(parents=True)
        by_shard: dict[str, list[list[str]]] = {}
        for code, parent in rows.items():
            by_shard.setdefault(code[:1], []).append(
                [code, title(vocabulary, code), parent or ""]
            )
        shards = {}
        for key, shard_rows in by_shard.items():
            data = _csv([columns, *shard_rows])
            (directory / f"{key}.csv").write_bytes(data)
            shards[key] = {
                "file": f"{key}.csv",
                "rows": len(shard_rows),
                "bytes": len(data),
                "sha256": _sha256(data),
            }
        manifest = {
            "schema": "sumeds-ontology-pack/0.1",
            "vocabulary": vocabulary,
            "release": release,
            "columns": columns,
            "fields": {
                "code": "code",
                "description": "description",
                "parent": "parent",
            },
            "shard_key_length": 1,
            "rows": len(rows),
            "bytes": sum(s["bytes"] for s in shards.values()),
            "shards": shards,
        }
        manifest_bytes = json.dumps(manifest).encode()
        (directory / "manifest.json").write_bytes(manifest_bytes)
        vocabularies[vocabulary] = {
            "manifest": f"{vocabulary}/{release}/manifest.json",
            "sha256": _sha256(manifest_bytes),
            "release": release,
            "rows": manifest["rows"],
            "bytes": manifest["bytes"],
        }

    directory = root / "crosswalks" / "nwicu"
    directory.mkdir(parents=True)
    table = _csv(
        [
            ["itemid", "source_table", "loinc_code"],
            *([itemid, *row] for itemid, row in CROSSWALK.items()),
        ]
    )
    (directory / "loinc_parents.csv").write_bytes(table)
    crosswalk_manifest = json.dumps(
        {
            "schema": "sumeds-crosswalk/0.1",
            "dataset": "nwicu",
            "tables": {
                "loinc_parents": {"file": "loinc_parents.csv", "sha256": _sha256(table)}
            },
        }
    ).encode()
    (directory / "manifest.json").write_bytes(crosswalk_manifest)
    crosswalks = {
        "nwicu": {
            "manifest": "crosswalks/nwicu/manifest.json",
            "sha256": _sha256(crosswalk_manifest),
        }
    }

    index = {
        "schema": "sumeds-ontologies/0.1",
        "vocabularies": vocabularies,
        "crosswalks": crosswalks,
    }
    (root / "index.json").write_text(json.dumps(index))
    return root


@pytest.fixture(scope="session")
def enriched_output(tmp_path_factory, raw_dir: Path, ontology_source: Path) -> Path:
    output_dir = tmp_path_factory.mktemp("nwicu_enriched") / "MEDS_cohort"
    run_command(
        [
            "suMEDS-extract",
            "spec=NWICU",
            f"output_dir={output_dir}",
            "do_download=false",
            f"input_dir={raw_dir}",
            "--",
            "--ontology-source",
            str(ontology_source),
            "--offline",
        ]
    )
    return output_dir


@pytest.fixture(scope="session")
def enriched_table(enriched_output: Path) -> pa.Table:
    return pq.read_table(enriched_output / "metadata" / "codes.parquet")


@pytest.fixture(scope="session")
def enriched_rows(enriched_table: pa.Table) -> dict[str, dict]:
    """Enriched rows by code. Read with pyarrow, so a names map is a list of (key, value) pairs
    whatever the installed Polars version makes of it."""
    return {row["code"]: row for row in enriched_table.to_pylist()}


def _dataset(output_dir: Path) -> dict:
    """`dataset.json`, checked to still be valid MEDS dataset metadata."""
    dataset = json.loads((output_dir / "metadata" / "dataset.json").read_text())
    DatasetMetadataSchema.validate(dataset)
    return dataset


def _names(row: dict, column: str = "parent_names") -> dict[str, str]:
    return dict(row[column] or [])


def test_codes_parquet_is_replaced_by_valid_meds_metadata(
    enriched_output: Path, enriched_table: pa.Table
):
    CodeMetadataSchema.validate(enriched_table)
    leftovers = list((enriched_output / "metadata").glob(".*enriched*"))
    assert not leftovers, "the temporary enrichment output was left behind"


def test_names_are_code_to_name_maps(enriched_table: pa.Table):
    """suMEDS 0.6 stores parent names as a map from each parent code to its name, not as a list
    aligned with `parent_codes`."""
    names = enriched_table.schema.field("parent_names").type
    assert pa.types.is_map(names), names
    assert (names.key_type, names.item_type) == (pa.string(), pa.string())


def test_data_matches_the_plain_etl(enriched_output: Path, events: pl.DataFrame):
    enriched_events = pl.concat(
        [pl.read_parquet(fp) for fp in (enriched_output / "data").rglob("*.parquet")]
    )
    key = ["subject_id", "time", "code"]
    assert enriched_events.sort(key).select(key).equals(events.sort(key).select(key))


def test_enrichment_overwrites_nothing(codes: pl.DataFrame, enriched_rows: dict):
    """Every code of the plain ETL keeps its description, and its parents stay a prefix."""
    assert set(enriched_rows) == set(codes["code"])
    for plain in codes.to_dicts():
        enriched = enriched_rows[plain["code"]]
        if plain["description"] is not None:
            assert enriched["description"] == plain["description"], plain["code"]
        existing = plain["parent_codes"] or []
        assert (enriched["parent_codes"] or [])[: len(existing)] == existing, plain[
            "code"
        ]


def test_lab_and_chart_items_get_loinc_from_the_crosswalk(enriched_rows: dict):
    for code, loinc in (
        ("LAB//900001//mg/dL", "2160-0"),  # labevents
        ("LAB//800001//bpm", "8867-4"),  # chartevents
    ):
        row = enriched_rows[code]
        assert row["vocabulary_id"] == "LOINC", code
        assert row["concept_code"] == loinc, code
        assert row["parent_codes"] == [f"LOINC//{loinc}"], code
        assert _names(row) == {f"LOINC//{loinc}": title("LOINC", loinc)}, code
    # The dictionary label from the ETL is kept.
    assert enriched_rows["LAB//900001//mg/dL"]["description"] == "Synthetic lab A"

    # A crosswalk LOINC code that is not in the pack, and an item without a crosswalk row.
    for code in ("LAB//900002//mEq/L", "LAB//900003//UNK"):
        assert not enriched_rows[code]["parent_codes"], code
        assert enriched_rows[code]["vocabulary_id"] is None, code


def test_icd_diagnoses_get_pack_ancestors_and_dataset_parents(enriched_rows: dict):
    row = enriched_rows["DIAGNOSIS//ICD//10//I5023"]
    assert (
        row["description"] == "Synthetic diagnosis title I5023"
    )  # from d_icd_diagnoses
    assert (row["vocabulary_id"], row["concept_code"]) == ("ICD10CM", "I50.23")
    # The ETL's own parent comes first and keeps its spelling; then the pack ancestors, then the
    # nearest ancestor that is itself a diagnosis code of this dataset.
    assert row["parent_codes"] == [
        "ICD10CM/I50.23",
        "ICD10CM//I50.2",
        "ICD10CM//I50",
        "DIAGNOSIS//ICD//10//I502",
    ]
    assert _names(row) == {
        "ICD10CM/I50.23": title("ICD10CM", "I50.23"),
        "ICD10CM//I50.2": title("ICD10CM", "I50.2"),
        "ICD10CM//I50": title("ICD10CM", "I50"),
    }

    row = enriched_rows["DIAGNOSIS//ICD//9//E8889"]
    assert (row["vocabulary_id"], row["concept_code"]) == ("ICD9CM", "E888.9")
    assert row["parent_codes"] == ["ICD9CM/E888.9", "ICD9CM//E888"]

    # A code that is not in the pack keeps only the ETL's parent.
    row = enriched_rows["DIAGNOSIS//ICD//10//R4689"]
    assert row["parent_codes"] == ["ICD10CM/R46.89"]
    assert row["vocabulary_id"] is None


def test_gender_codes_are_tagged(enriched_rows: dict):
    """Gender has no pack, so the OMOP Gender code is added as an unvalidated, unnamed tag."""
    for sex in ("F", "M"):
        row = enriched_rows[f"GENDER//{sex}"]
        assert row["parent_codes"] == [f"Gender//{sex}"]
        assert not _names(row)
        assert row["description"] == f"Patient sex: {sex} (NWICU patients.gender)"


def test_codes_without_a_rule_are_left_alone(enriched_rows: dict):
    # NDC has no pack, so the ETL's NDC parent is neither validated nor extended.
    row = enriched_rows["MEDICATION//START//Synthetic drug A//PO//mg"]
    assert row["parent_codes"] == ["NDC/12345678901"]
    assert row["vocabulary_id"] is None
    for code in ("MEDS_BIRTH", "HOSPITAL_DISCHARGE//HOME", "PROCEDURE//START//800002"):
        assert not enriched_rows[code]["parent_codes"], code
        assert enriched_rows[code]["vocabulary_id"] is None, code


def test_dataset_json_records_the_enrichment(
    enriched_output: Path, meds_output: Path, codes: pl.DataFrame, enriched_rows: dict
):
    """`metadata/dataset.json` says the build is enriched, with which rules, and what it added."""
    dataset, plain = _dataset(enriched_output), _dataset(meds_output)
    assert "sumeds_enrichment" not in plain
    assert set(dataset) == {*plain, "sumeds_enrichment"}
    record = dataset["sumeds_enrichment"]
    assert record["enriched"] is True
    assert record["rules"] == "NWICU"
    assert record["ontology_source"] == "local"
    assert record["athena"] is False

    def filled(rows: list[dict], column: str) -> int:
        return sum(row.get(column) is not None for row in rows)

    plain_rows, rows = codes.to_dicts(), list(enriched_rows.values())
    assert record["coverage"] == {
        "codes": len(rows),
        "described": [filled(plain_rows, "description"), filled(rows, "description")],
        "with_parent_codes": [
            filled(plain_rows, "parent_codes"),
            filled(rows, "parent_codes"),
        ],
    }
    before, after = record["coverage"]["with_parent_codes"]
    assert after > before


def test_enrichment_soft_fails_and_suMEDS_enrich_completes_it_later(
    tmp_path: Path,
    raw_dir: Path,
    ontology_source: Path,
    meds_output: Path,
    enriched_output: Path,
    enriched_table: pa.Table,
):
    """With no usable pack source (as on a site without internet), the ETL still succeeds:
    `codes.parquet` is left exactly as the plain ETL writes it, `dataset.json` records that it is
    not enriched and how to retry, and `suMEDS-enrich <OUT>` then gives the same table as a run
    that enriched directly."""
    empty_source = tmp_path / "no_packs"
    empty_source.mkdir()
    output_dir = tmp_path / "MEDS_cohort"
    stderr = run_command(
        [
            "suMEDS-extract",
            "spec=NWICU",
            f"output_dir={output_dir}",
            "do_download=false",
            f"input_dir={raw_dir}",
            "--",
            "--ontology-source",
            str(empty_source),
            "--offline",
        ]
    )
    assert "enrichment failed" in stderr
    assert f"suMEDS-enrich {output_dir} --ontology-source {empty_source}" in stderr

    codes_path = output_dir / "metadata" / "codes.parquet"
    plain_codes = meds_output / "metadata" / "codes.parquet"
    assert codes_path.read_bytes() == plain_codes.read_bytes()
    record = _dataset(output_dir)["sumeds_enrichment"]
    assert record["enriched"] is False
    assert record["rules"] == "NWICU"
    assert record["error"].startswith("OntologyPackError")
    assert record["retry"] == "suMEDS-enrich <MEDS_ROOT> --ontology-source <PACKS_DIR>"

    run_command(
        [
            "suMEDS-enrich",
            str(output_dir),
            "--ontology-source",
            str(ontology_source),
            "--offline",
        ]
    )
    record = _dataset(output_dir)["sumeds_enrichment"]
    direct = _dataset(enriched_output)["sumeds_enrichment"]
    assert record["enriched"] is True
    assert {k: v for k, v in record.items() if k != "enriched_at"} == {
        k: v for k, v in direct.items() if k != "enriched_at"
    }
    assert pq.read_table(codes_path).equals(enriched_table)
