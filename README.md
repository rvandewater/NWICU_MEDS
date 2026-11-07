# NWICU MEDS Extraction ETL

[![PyPI - Version](https://img.shields.io/pypi/v/NWICU_MEDS)](https://pypi.org/project/NWICU_MEDS/)
[![codecov](https://codecov.io/gh/rvandewater/NWICU_MEDS/graph/badge.svg?token=RW6JXHNT0W)](https://codecov.io/gh/rvandewater/NWICU_MEDS)
[![tests](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/synthetic-etl.yaml/badge.svg)](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/synthetic-etl.yaml)
[![code-quality](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/code-quality-main.yaml/badge.svg)](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/code-quality-main.yaml)
[![Documentation](https://readthedocs.org/projects/nwicu-meds/badge/?version=latest)](https://nwicu-meds.readthedocs.io/en/latest/)
![python](https://img.shields.io/badge/python-%3E%3D3.11.4%2C%20%3C3.14-blue?logo=python&logoColor=white)
[![license](https://img.shields.io/badge/License-MIT-green.svg?labelColor=gray)](https://github.com/rvandewater/NWICU_MEDS#license)
[![PRs](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/rvandewater/NWICU_MEDS/pulls)
[![contributors](https://img.shields.io/github/contributors/rvandewater/NWICU_MEDS.svg)](https://github.com/rvandewater/NWICU_MEDS/graphs/contributors)
[![DOI](https://zenodo.org/badge/913786544.svg)](https://doi.org/10.5281/zenodo.14892134)
![Static Badge](https://img.shields.io/badge/MEDS-0.4.1-blue)

Northwestern Medicine (NM) is a network of twelve hospitals located in Chicago and the surrounding area. NM originally used a variety of electronic medical record (EMR) systems across the network, but in 2018 migrated all the hospitals to the same EMR platform, Epic. As an essential element of routine medical care, the EMR collects data on patients, admissions, diagnoses, patient status, procedures, medications, and all the other aspects of patient care.

This pipeline extracts the NWICU dataset (from physionet, https://physionet.org/content/nwicu-northwestern-icu/0.1.0/) into the MEDS format.

## Usage:

With download:

```bash
pip install NWICU_MEDS
export DATASET_DOWNLOAD_USERNAME=...
export DATASET_DOWNLOAD_PASSWORD=...

meds-extract-run spec=NWICU output_dir=$OUTPUT_DIR
```

Without download (if you already have the dataset):

```bash
pip install NWICU_MEDS
meds-extract-run spec=NWICU do_download=false input_dir=$PHYSIONET_INPUT_DIR output_dir=$OUTPUT_DIR
```

## Configuration

**This package contains no ETL code.** The entire pipeline is one file,
[`src/NWICU_MEDS/messy.yaml`](src/NWICU_MEDS/messy.yaml), registered under the
`MEDS_extract.pipelines` entry-point group.

Everything the old `pre_MEDS.py` did is now config:

| Was                                                 | Now                                                                                |
| --------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `fix_static_data` — earliest death time per subject | `_table.joins` with `cols: {deathtime: min}`, then `dod_final: $deathtime ?? $dod` |
| DOB from `anchor_year - anchor_age`                 | `_table.cols`: `year_of_birth: ($anchor_year - $anchor_age)::str`                  |
| `add_discharge_time_by_hadm_id`                     | `_table.joins` on `hadm_id` for `dischtime`                                        |
| `add_icd_diagnosis_dot`                             | inlined into the diagnosis `parent_codes` expression                               |
| Post-hoc `codes.parquet` rebuild                    | `_metadata` blocks against NWICU's own `d_labitems` / `d_items`                    |

### Demographics

`insurance`, `language`, `marital_status` and `race` are properties of the subject rather than
annotations on the admission, so each is emitted as its own event — `INSURANCE//…`,
`LANGUAGE//…`, `MARITAL_STATUS//…`, `RACE//…` — co-timed with the admission, since NWICU records
no separate timestamp for them.

Their nulls are deliberately **not** coalesced to `UNK`, unlike the composite codes elsewhere in
this config. A null code component drops the row under MEDS-Extract (since 0.7), so a missing
demographic produces no event at all rather than minting a `RACE//UNK` code that would read as
an observed category.

### Raw data layout

The PhysioNet release nests its tables one level down, under `data/nw_hosp/` and
`data/nw_icu/`, and the table prefixes in the config match that exactly. This matters if you
stage the raw data yourself: point `input_dir` at the directory *containing* `data/`, which is
what `meds-extract-download` writes, not at `data/` itself.

### Code metadata: descriptions and parent codes

Every code in `metadata/codes.parquet` gets a `description`, and codes for which NWICU itself
records a standard-vocabulary code get `parent_codes` (`ICD9CM/…`, `ICD10CM/…`, `NDC/…`, named
after the OMOP `vocabulary_id`) so vocabulary tooling such as OHDSI Athena can resolve them.
Each family gets its metadata through a `_metadata` block in `messy.yaml`:

| Code family                                                                                                                                                       | Route                                                                                    | Source                                                                                                                                                                                                                                                                                                                                              |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DIAGNOSIS//ICD//…`                                                                                                                                               | NWICU's `d_icd_diagnoses`, joined on `icd_version` and `icd_code`                        | `long_title`; ICD-9-CM / ICD-10-CM parent with the dot restored                                                                                                                                                                                                                                                                                     |
| `LAB//…` (from `labevents` and `chartevents`), `PROCEDURE//…`                                                                                                     | NWICU's `d_labitems` / `d_items`, joined on `itemid` alone, so a label covers every unit | `label`; no vocabulary parent (LOINC links come from suMEDS, below)                                                                                                                                                                                                                                                                                 |
| `MEDICATION//START//…`, `MEDICATION//STOP//…`                                                                                                                     | `_self` template over the code's components                                              | `prescriptions.drug`, `route`, `dose_unit_rx`; NDC parent from `prescriptions.ndc` normalized to 11 digits (both start and stop codes)                                                                                                                                                                                                              |
| `MEDICATION//…` (eMAR), `HOSPITAL_ADMISSION`, `HOSPITAL_DISCHARGE`, `INSURANCE`, `LANGUAGE`, `MARITAL_STATUS`, `RACE`, `GENDER`, `ICU_ADMISSION`, `ICU_DISCHARGE` | `_self` template over the code's components                                              | the column each component comes from, with its meaning from the [MIMIC-IV documentation](https://mimic.mit.edu/docs/iv/modules/) (source: [MIT-LCP/mimic-website](https://github.com/MIT-LCP/mimic-website), MIT, 8182227), whose structure NWICU retains ([NWICU 0.1.0 project page](https://physionet.org/content/nwicu-northwestern-icu/0.1.0/)) |
| `ED_REGISTRATION`, `ED_OUT`, `MEDS_BIRTH`, `MEDS_DEATH`                                                                                                           | `_self` text, via a constant code column (below)                                         | the same documentation and this config's own time rules                                                                                                                                                                                                                                                                                             |

The item dictionaries replace a Python rebuild that existed because the MIMIC-IV crosswalks are
keyed on MIMIC itemids that never match NWICU's, a mismatch that now surfaces as a WARNING instead
of silently matching zero rows.

**No LOINC parents from the ETL.** NWICU ships no LOINC codes in its dictionaries, so the ETL
writes none. LOINC links for 45 lab and 5 chart itemids exist as an inferred crosswalk, which
suMEDS applies after extraction (see [Enriching code metadata with suMEDS](#enriching-code-metadata-with-sumeds)).

**Literal codes.** MEDS-Extract attaches metadata only through a code's components, so a code
written as a bare literal (`code: MEDS_BIRTH`) can never be described: the pre-existing
`codes.parquet` it documents for that case is not read by `meds-extract-run`. These four events
therefore read their code from a constant `_table.cols` column (`_code_birth: '"MEDS_BIRTH"'`,
`code: $_code_birth`), which gives the code one component for a `_self` description to attach to.
The emitted codes and events are unchanged; their `code_template` names the constant column.
`MEDS_DEATH` is described once, by the `patients` event: `death_untimed` carries no `_metadata`,
because one code may have only one code template.

The `_self` descriptions restate the code with the NWICU column each part comes from. eMAR
medication codes get no parent: `emar` has no drug code column, and mapping its drug names to
RxNorm is a job for a mapping tool, not the ETL.

## Enriching code metadata with suMEDS

The ETL writes what NWICU itself records. Links to external vocabularies that NWICU does not
record, and parents among NWICU's own codes, are added afterwards by
[suMEDS](https://github.com/rvandewater/SumMEDS) with the rules file shipped in this package,
`src/NWICU_MEDS/sumeds_rules.yaml`. The crosswalk tables and ontology packs come from suMEDS's
versioned ontology data (sumeds-ontologies, pinned release), so this repository does not ship
them, and no Athena download or LOINC account is needed:

```bash
suMEDS-enrich $MEDS_DIR/metadata/codes.parquet -o codes_enriched.parquet \
  --rules "$(python -c 'from importlib.resources import files; print(files("NWICU_MEDS") / "sumeds_rules.yaml")')"
```

This needs suMEDS 0.4 or later (`pip install "sumeds>=0.4"`), the first release with ontology
rules. The rules add:

- **LOINC for lab and chart items** (`nwicu-lab-loinc`, a crosswalk): `LAB//{itemid}//{unit}`
    gets `LOINC//<code>` in `parent_codes`, plus `vocabulary_id` and `concept_code`, for the 45
    lab and 5 chart itemids of the crosswalk table `nwicu/loinc_parents`, each validated against
    the LOINC pack. The links are **inferred**: the itemid is mapped to a concept by
    [WeavEHR](https://github.com/aidh-ms/WeavEHR) (`configs/datasets/nwicu/0.1.0/mappings`, MIT,
    210a539), WeavEHR maps the same concept to a MIMIC-IV item, and
    [mimic-code](https://github.com/MIT-LCP/mimic-code) (`d_labitems_to_loinc.csv`,
    `meas_chartevents_main.csv`, MIT, v2.4.0) gives that item's LOINC code. Only concepts whose
    MIMIC-IV items share one LOINC code are used, and each link inherits the MIMIC-IV item's
    specimen and method; the table records both ends of every bridge.
- **ICD diagnoses** (`nwicu-icd10cm-diagnoses`, `nwicu-icd9cm-diagnoses`, ontology rules): the
    dotted ICD-10-CM / ICD-9-CM code with `vocabulary_id`, `concept_code` and every ancestor in
    the pack (`ICD10CM//I50.23`, `ICD10CM//I50.2`, `ICD10CM//I50`), next to the ETL's own
    `ICD10CM/…` parent.
- **Gender** (`nwicu-gender`, an ontology rule): `GENDER//F` and `GENDER//M` get the OMOP Gender
    codes `Gender//F` and `Gender//M` (a tag: Gender has no public pack; with `--athena-csv`
    suMEDS validates them against Athena).
- **Parents among NWICU codes** (`nwicu-icd-parents-in-dataset`, a hierarchy rule): a diagnosis
    code of the table becomes the parent of another when its ICD code is the nearest ancestor
    present (`DIAGNOSIS//ICD//10//I5023` gets `DIAGNOSIS//ICD//10//I502` when both occur).

The ETL alone no longer emits the LOINC parents of lab and chart codes (earlier builds of this
branch wrote `LOINC/<code>` for the same 50 itemids), and it never emitted ICD ancestors,
Gender codes or parents among NWICU codes; suMEDS supplies them. suMEDS never removes or
rewrites the ETL's own parents (`ICD10CM/…`, `NDC/…`) or descriptions.

## Summary statistics

[`tests/regression/full_summary_stats.json`](tests/regression/full_summary_stats.json) is a
[meds_summary_stats](https://github.com/Medical-Event-Data-Standard/meds_summary_stats) fingerprint of
the MEDS dataset this ETL builds from the full NWICU 0.1.0 release: subject, event and measurement
counts, digests of the code vocabulary, per-subject, value and time distributions, code-metadata
coverage, the splits and the schema. It names no code and reports no cell of fewer than 20 subjects and
no minimum or maximum, which is what makes it safe to publish. Because it is committed next to the ETL,
its diff shows what an ETL change did to the output, and two ETL versions can be compared without
access to the data.

Regenerate it in every pull request that changes the output, from a build of that branch:

```bash
# Build the release with this checkout, then summarize it
scripts/summary_stats.sh full --input-dir $PHYSIONET_INPUT_DIR
# Or summarize a build of this checkout you already have
scripts/summary_stats.sh full --meds-dir $MEDS_OUTPUT_DIR
```

Both print how the statistics changed against the committed baseline before overwriting it. Add
`--compare` to check a build without writing anything; it exits 1 when
[`tests/regression/policy.yaml`](tests/regression/policy.yaml) flags an error. Rebuilding the same
commit reproduces the baseline exactly, so any finding is a change in the output. CI cannot rebuild the
credentialed release, so the [Summary stats workflow](.github/workflows/summary-stats.yaml) only warns
when a pull request changes `src/` without regenerating the baseline. A MEDS-Extract or polars upgrade
can also move the output, so check it with `--compare`.

## Citation

If you find our work useful, please cite the resource through the github repository (or the bibtex entry below), and cite the original dataset through PhysioNet.

This is the original dataset citation from PhysioNet:

```bibtex
@article{PhysioNet-nwicu-northwestern-icu-0.1.0,
  author = {Moukheiber, Dana and Temps, William and Molgi, Bhadrappa and Li, Yikuan and Lu, Alice and Nannapaneni, Prasanth and Chahin, Abdulrahman and Hao, Sicheng and {Torres Fabregas}, Felipe and Celi, Leo Anthony and Wong, Adrian and Lloyd, Maxwell and {Borrat Frigola}, Xavier and Lee, Hyung-Chul and Schneider, Daniel and Pollard, Tom and Luo, Yuan and Kho, Abel and Mark, Roger},
  title = {{Northwestern ICU (NWICU) database}},
  journal = {{PhysioNet}},
  year = {2024},
  month = nov,
  note = {Version 0.1.0},
  doi = {10.13026/s84w-1829},
  url = {https://doi.org/10.13026/s84w-1829}
}
```

The following is the recommended citation for this package:

```bibtex
@software{van_de_Water_NWICU_MEDS_ETL_2025,
author = {van de Water, Robin Philippus},
doi = {10.5281/zenodo.14892134},
license = {MIT},
month = feb,
title = {{NWICU\_MEDS ETL}},
url = {https://github.com/rvandewater/NWICU_MEDS},
year = {2025}
}
```

For citing MEDS in general:

```bibtex
@article{mcdermott2026meds,
  title={MEDS—An Emerging Data Standard and Ecosystem for Health AI Research},
  author={McDermott, Matthew BA and Steinberg, Ethan and Fries, Jason A and van de Water, Robin P and Pang, Chao and Rockenschaub, Patrick and Renc, Pawel and Oh, Jungwoo and Stankevi{\v{c}}i{\=u}t{\.e}, Kamil{\.e} and Xu, Justin and others},
  journal={NEJM AI},
  volume={3},
  number={6},
  pages={AIra2501253},
  year={2026},
  publisher={Massachusetts Medical Society}
}
```
