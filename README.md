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

| Was                                                 | Now                                                                               |
| --------------------------------------------------- | --------------------------------------------------------------------------------- |
| `fix_static_data` — earliest death time per subject | `_table.join` with `cols: {deathtime: min}`, then `dod_final: $deathtime ?? $dod` |
| DOB from `anchor_year - anchor_age`                 | `_table.cols`: `year_of_birth: ($anchor_year - $anchor_age)::str`                 |
| `add_discharge_time_by_hadm_id`                     | `_table.join` on `hadm_id` for `dischtime`                                        |
| `add_icd_diagnosis_dot`                             | inlined into the diagnosis `parent_codes` expression                              |
| Post-hoc `codes.parquet` rebuild                    | `_metadata` blocks against NWICU's own `d_labitems` / `d_items`                   |

### Demographics

`insurance`, `language`, `marital_status` and `race` are properties of the subject rather than
annotations on the admission, so each is emitted as its own event — `INSURANCE//…`,
`LANGUAGE//…`, `MARITAL_STATUS//…`, `RACE//…` — co-timed with the admission, since NWICU records
no separate timestamp for them.

Their nulls are deliberately **not** coalesced to `UNK`, unlike the composite codes elsewhere in
this config. A null code component drops the row under MEDS-Extract 0.7, so a missing
demographic produces no event at all rather than minting a `RACE//UNK` code that would read as
an observed category.

### Raw data layout

The PhysioNet release nests its tables one level down, under `data/nw_hosp/` and
`data/nw_icu/`, and the table prefixes in the config match that exactly. This matters if you
stage the raw data yourself: point `input_dir` at the directory *containing* `data/`, which is
what `meds-extract-download` writes, not at `data/` itself.

### Code metadata: descriptions and parent codes

Every code in `metadata/codes.parquet` gets a `description`, and codes from a standard
vocabulary get `parent_codes` (`ICD9CM/…`, `ICD10CM/…`, `NDC/…`, `LOINC/…`, named after the OMOP
`vocabulary_id`) so vocabulary tooling such as OHDSI Athena can resolve them. Each family gets
its metadata through a `_metadata` block in `messy.yaml`:

| Code family                                                                                                                                                       | Route                                                                                    | Source                                                                                                                                                                                                                                                                                                                                              |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DIAGNOSIS//ICD//…`                                                                                                                                               | NWICU's `d_icd_diagnoses`, joined on `icd_version` and `icd_code`                        | `long_title`; ICD-9-CM / ICD-10-CM parent with the dot restored                                                                                                                                                                                                                                                                                     |
| `LAB//…` (from `labevents` and `chartevents`), `PROCEDURE//…`                                                                                                     | NWICU's `d_labitems` / `d_items`, joined on `itemid` alone, so a label covers every unit | `label`; for 45 lab and 5 chart itemids also an inferred LOINC parent (below)                                                                                                                                                                                                                                                                       |
| `MEDICATION//START//…`, `MEDICATION//STOP//…`                                                                                                                     | `_self` template over the code's components                                              | `prescriptions.drug`, `route`, `dose_unit_rx`; NDC parent from `prescriptions.ndc` normalized to 11 digits (both start and stop codes)                                                                                                                                                                                                              |
| `MEDICATION//…` (eMAR), `HOSPITAL_ADMISSION`, `HOSPITAL_DISCHARGE`, `INSURANCE`, `LANGUAGE`, `MARITAL_STATUS`, `RACE`, `GENDER`, `ICU_ADMISSION`, `ICU_DISCHARGE` | `_self` template over the code's components                                              | the column each component comes from, with its meaning from the [MIMIC-IV documentation](https://mimic.mit.edu/docs/iv/modules/) (source: [MIT-LCP/mimic-website](https://github.com/MIT-LCP/mimic-website), MIT, 8182227), whose structure NWICU retains ([NWICU 0.1.0 project page](https://physionet.org/content/nwicu-northwestern-icu/0.1.0/)) |
| `ED_REGISTRATION`, `ED_OUT`, `MEDS_BIRTH`, `MEDS_DEATH`                                                                                                           | `_self` text, via a constant code column (below)                                         | the same documentation and this config's own time rules                                                                                                                                                                                                                                                                                             |

The item dictionaries replace a Python rebuild that existed because the MIMIC-IV crosswalks are
keyed on MIMIC itemids that never match NWICU's, a mismatch that now surfaces as a WARNING instead
of silently matching zero rows.

**LOINC parents are inferred.** NWICU ships no LOINC codes in its dictionaries. The LOINC parent of
a lab or chart itemid comes from a bridge across two public, curated mappings: the itemid is
mapped to a concept by [WeavEHR](https://github.com/aidh-ms/WeavEHR) (`configs/datasets/nwicu/0.1.0/mappings`,
MIT, 210a539), WeavEHR maps the same concept to a MIMIC-IV item (`mimic-iv/2.2/mappings`), and
[mimic-code](https://github.com/MIT-LCP/mimic-code) (`mimic-iv/concepts/concept_map/d_labitems_to_loinc.csv`
and `meas_chartevents_main.csv`, MIT, v2.4.0) gives that item's LOINC code. Only concepts whose
MIMIC-IV items share one LOINC code are used (glucose, arterial and non-invasive blood pressure,
and respiratory rate map to several, troponin I to none). The parent inherits the MIMIC-IV item's
specimen and method, which may differ from NWICU's. Every bridge, with both of its ends, is a row
of [`src/NWICU_MEDS/metadata/loinc_parents.csv`](src/NWICU_MEDS/metadata/loinc_parents.csv); the
`parent_codes` expressions in the `d_labitems` and `d_items` blocks are written out from it, and
`tests/test_code_metadata.py` checks that the two agree.

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
