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

## Usage

With download:

```bash
pip install NWICU_MEDS
export DATASET_DOWNLOAD_USERNAME=... # your PhysioNet username
export DATASET_DOWNLOAD_PASSWORD=... # and password

meds-extract-run spec=NWICU output_dir=$OUTPUT_DIR
```

Without download (if you already have the dataset):

```bash
pip install NWICU_MEDS
meds-extract-run spec=NWICU do_download=false input_dir=$PHYSIONET_INPUT_DIR output_dir=$OUTPUT_DIR
```

This one command runs the ETL and then enriches its code metadata with
[suMEDS](https://github.com/rvandewater/SumMEDS) (installed with this package): the spec ends with
suMEDS's `sumeds_enrich` stage, which adds LOINC codes for lab and chart items, ICD ancestors, OMOP
Gender codes and parents among NWICU's diagnosis codes to `metadata/codes.parquet`. If it cannot
(no internet, say), the ETL still succeeds, unenriched, and `suMEDS-enrich $OUTPUT_DIR` finishes it
later. Add `skip_stages=[sumeds_enrich]` for the plain ETL. See
[Enriching code metadata with suMEDS](#enriching-code-metadata-with-sumeds).

The output directory holds the MEDS dataset (`data/` and `metadata/`, per the
[MEDS standard](https://medical-event-data-standard.github.io/)), with the dataset name and
version stamped in `metadata/dataset.json`. `dataset.json` also gives the release's `license` and
PhysioNet page (`description_uri`), and lists `hadm_id`, `icustay_id`, `emar_id` and
`pharmacy_id`, the keys back to the raw tables, under `raw_source_id_columns`; MEDS-Extract lists
every other extension column under `other_extension_columns`.

Intermediate stage outputs are deleted after a successful run, by default: the spec sets
MEDS-Extract's `etl.cleanup_intermediates: true`, so a finished `$OUTPUT_DIR` holds only `data/`,
`metadata/`, `.logs/` and `.meds_extract_run/`. A failed run keeps them, so the same command resumes
where it stopped, and the same command on a finished output still does nothing. To keep them (to look
at a stage's output; `$OUTPUT_DIR/.logs/pipeline.log` keeps the stage logs either way), add
`"overrides=['cleanup_intermediates=false']"`. Cleanup never deletes raw data: a download into the
default `$OUTPUT_DIR/.meds_extract_run/raw_input` stays, and `download_dest_dir=` elsewhere lets other
output directories reuse it.

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

### Deaths

Each subject gets at most one `MEDS_DEATH`, timed by the first of these that exists:

1. the earliest `admissions.deathtime` of the subject (in-hospital death; `patients` joins it with
    `cols: {deathtime: min}`);
2. `patients.dod`, the date of death;
3. for a subject with neither, the `dischtime` of an admission discharged to a location starting
    `EXPIRED` (`death_untimed` in `admissions`).

The first two are the MIMIC-IV rule. The third exists because NWICU 0.1.0 has 108 subjects whose
in-hospital death is recorded only as the discharge location. `hospital_expire_flag` is not used: in
NWICU it is set only on rows without a `deathtime`, and it misses `EXPIRED - HOSPICE`. A discharge to
`EXPIRED` is not counted again when the admission has a `deathtime` or the subject has a `dod`.

`admissions` cannot see the `deathtime` of the subject's *other* admissions (MESSY rejects a table
joining itself), so a subject without a `dod`, with a `deathtime` on one admission and an untimed
`EXPIRED` discharge on another, would still get two deaths. On NWICU 0.1.0 no subject does: the full
build that added `death_untimed` had 5,213 subjects with a death and none with two.

### Raw data layout

The PhysioNet release nests its tables one level down, under `data/nw_hosp/` and
`data/nw_icu/`, and the table prefixes in the config match that exactly. This matters if you
stage the raw data yourself: point `input_dir` at the directory *containing* `data/`, which is
what `meds-extract-download` writes, not at `data/` itself.

### Code metadata: descriptions, parent codes and units

Every code in `metadata/codes.parquet` gets a `description`, and codes for which NWICU itself
records a standard-vocabulary code get `parent_codes` (`ICD9CM//…`, `ICD10CM//…`, `NDC//…`, named
after the OMOP `vocabulary_id`) so vocabulary tooling such as OHDSI Athena can resolve them.
Each family gets its metadata through a `_metadata` block in `messy.yaml`:

| Code family                                                                                                                                                       | Route                                                                                    | Source                                                                                                                                                                                                                                                                                                                                              |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DIAGNOSIS//ICD//{9CM,10CM}//…`                                                                                                                                   | NWICU's `d_icd_diagnoses`, joined on `icd_version` and `icd_code`                        | `long_title`; ICD-9-CM / ICD-10-CM parent with the dot restored                                                                                                                                                                                                                                                                                     |
| `LAB//…` (from `labevents` and `chartevents`), `PROCEDURE//…`                                                                                                     | NWICU's `d_labitems` / `d_items`, joined on `itemid` alone, so a label covers every unit | `label`; no vocabulary parent (LOINC links come from suMEDS, below)                                                                                                                                                                                                                                                                                 |
| `MEDICATION//START//…`, `MEDICATION//END//…`                                                                                                                      | `_self` template over the code's components                                              | `prescriptions.drug`, `route`, `dose_unit_rx`; NDC parent from `prescriptions.ndc` normalized to 11 digits (both start and end codes)                                                                                                                                                                                                               |
| `MEDICATION//…` (eMAR), `HOSPITAL_ADMISSION`, `HOSPITAL_DISCHARGE`, `INSURANCE`, `LANGUAGE`, `MARITAL_STATUS`, `RACE`, `GENDER`, `ICU_ADMISSION`, `ICU_DISCHARGE` | `_self` template over the code's components                                              | the column each component comes from, with its meaning from the [MIMIC-IV documentation](https://mimic.mit.edu/docs/iv/modules/) (source: [MIT-LCP/mimic-website](https://github.com/MIT-LCP/mimic-website), MIT, 8182227), whose structure NWICU retains ([NWICU 0.1.0 project page](https://physionet.org/content/nwicu-northwestern-icu/0.1.0/)) |
| `ED_REGISTRATION`, `ED_OUT`, `MEDS_BIRTH`, `MEDS_DEATH`                                                                                                           | `_self` text on the literal code (below)                                                 | the same documentation and this config's own time rules                                                                                                                                                                                                                                                                                             |

**Units.** Every code that carries a `numeric_value` also gets a `unit` column: a string, the unit
of the code's numeric values, one per code, written in [UCUM](https://ucum.org/) by suMEDS's
`sumeds_normalize_units` post-stage (`mEq/L` becomes `meq/L`, `bpm` becomes `{beats}/min`). The
spelling as recorded stays in `unit_source_value`, and a spelling suMEDS does not know is kept as it
is. The sources are `labevents.valueuom` and `chartevents.valueuom` for `LAB//…` (a
`_self` block next to the dictionary block) and `prescriptions.dose_unit_rx` for
`MEDICATION//START//…`. In NWICU the unit as recorded is already the code's last segment, so each code
has one unit and the codes are unchanged (`LAB//{itemid}//mEq/L` keeps its name); a code whose unit segment is `UNK` (a null unit) has a null
`unit`. The unit in a code is stripped of surrounding whitespace; missing or blank is `UNK`.
MEDS-Extract compares units the same way when it writes `unit` (stripped, blanks dropped), so
` mg/dL` and `mg/dL` give one code. `d_items.unitname` states a unit for the 13 chart codes without one, but none of their rows
has a numeric value, so it is not used; `d_labitems` has no unit column.

MEDS-Extract (since 0.9.0) writes `unit` as one string per code and fails if any code has more
than one unit. The first post-stage, suMEDS's
[`sumeds_link_unit_siblings`](https://github.com/rvandewater/suMEDS/blob/main/docs/unit_siblings.md)
(it replaced this package's own `nwicu_unit_metadata` in suMEDS 0.6.6), gives codes
that differ only in their unit (`LAB//{itemid}//mg/dL` and `…//mmol/L`) the code without the unit
(`LAB//{itemid}`) as an in-dataset parent in `parent_codes`, and adds a row for that code: no unit,
the description its siblings share (for prescription starts, whose descriptions differ only by the
dose unit, that description without it) and the vocabulary parents they all have. A code of the same
item whose unit was not recorded (`LAB//{itemid}//UNK`) joins the siblings, but two `UNK`-style codes
alone are never a group. On NWICU 0.1.0, before `UNK` codes were linked, that was 477 groups (142 lab
items, 335 drug/route pairs; 1,135 codes) and 477 added rows. With `link_single_units: true` and
`unknown_unit_prefixes: [MEDICATION//START//]`, a code ending in its unit gets its stem also when its
item has a single unit, and so does a prescription start without a recorded dose unit
(`MEDICATION//START//{drug}//{route}//UNK`), so every start pairs with its end
(`…//{drug}//{route}`) by stem.

The item dictionaries replace a Python rebuild that existed because the MIMIC-IV crosswalks are
keyed on MIMIC itemids that never match NWICU's, a mismatch that now surfaces as a WARNING instead
of silently matching zero rows.

**No LOINC parents from the ETL.** NWICU ships no LOINC codes in its dictionaries, so the ETL
writes none. LOINC links for 45 lab and 5 chart itemids exist as an inferred crosswalk, which
suMEDS applies after extraction (see [Enriching code metadata with suMEDS](#enriching-code-metadata-with-sumeds)).

**Literal codes.** `ED_REGISTRATION`, `ED_OUT`, `MEDS_BIRTH` and `MEDS_DEATH` are plain literals
(`code: MEDS_BIRTH`) with a `_self` description: MEDS-Extract 0.8.1 and later attach `_self`
metadata to literal codes ([MEDS_extract#166](https://github.com/mmcdermott/MEDS_extract/issues/166)),
and their `code_template` is the code itself.
`MEDS_DEATH` is described once, by the `patients` event: `death_untimed` carries no `_metadata`,
because one code may have only one code template.

The `_self` descriptions restate the code with the NWICU column each part comes from. eMAR
medication codes get no parent: `emar` has no drug code column, and mapping its drug names to
RxNorm is a job for a mapping tool, not the ETL.

## Enriching code metadata with suMEDS

The ETL writes what NWICU itself records. Links to external vocabularies that NWICU does not
record, and parents among NWICU's own codes, are added afterwards by
[suMEDS](https://github.com/rvandewater/SumMEDS). The package ships the rules for it,
[`src/NWICU_MEDS/sumeds_rules.yaml`](src/NWICU_MEDS/sumeds_rules.yaml), registered in suMEDS's
`sumeds.rules` entry-point group under the same name as the MEDS-Extract spec, `NWICU`, so
`--rules NWICU` works for any suMEDS command. The spec runs them as its last stage, after suMEDS's
`sumeds_link_unit_siblings` and `sumeds_normalize_units` (see **Units** above):

```yaml
etl:
  post_stages:
    - sumeds_link_unit_siblings:
        link_single_units: true
        unknown_unit_prefixes: [MEDICATION//START//]
    - sumeds_normalize_units
    - sumeds_enrich: {rules: NWICU}
```

The stage replaces `metadata/codes.parquet` only once the enriched table is complete, and it stays
valid MEDS code metadata. The crosswalk tables and ontology packs come from suMEDS's
versioned ontology data (sumeds-ontologies, pinned release), fetched from GitHub on first use and
cached, so this repository does not ship them, and no Athena download or LOINC account is needed.

`metadata/dataset.json` says whether a build is enriched: `sumeds_enrichment.enriched` is `true`
(with the rules, pack source and coverage) or `false` (with the error and the `retry` command).

```bash
jq .sumeds_enrichment.enriched $OUTPUT_DIR/metadata/dataset.json
```

Enrichment soft-fails: if it cannot run (a server without internet, for example), the ETL still
succeeds with `metadata/codes.parquet` left exactly as MEDS-Extract writes it, and `dataset.json`
records `"enriched": false`. The warning, with the command that finishes the enrichment, is in
`$OUTPUT_DIR/.logs/pipeline.log`, not on the console. MEDS-Extract marks the stage done either
way, so running `meds-extract-run` again does not retry it. Enrich the build afterwards, with the
rules and options of the failed run:

```bash
suMEDS-enrich $OUTPUT_DIR
# Air-gapped: from a copy of the sumeds-ontologies packs directory
suMEDS-enrich $OUTPUT_DIR --ontology-source /path/to/sumeds-ontologies/ontologies --offline
```

For the plain, unenriched ETL, leave the stage out with `skip_stages=[sumeds_enrich]`:

```bash
meds-extract-run spec=NWICU output_dir=$OUTPUT_DIR skip_stages=[sumeds_enrich]
```

The stage takes the `suMEDS-enrich` options, spelled with underscores. Set them for one run with
`overrides=`, as `++stage_cfg.<option>` (the override reaches every stage of the pipeline, and only
this one declares the option, hence the `++`):

```bash
# Make a failed enrichment fail the run (exit code 1):
meds-extract-run spec=NWICU output_dir=$OUTPUT_DIR "overrides=['++stage_cfg.strict=true']"
# Also look codes up in your own OHDSI Athena download:
meds-extract-run spec=NWICU output_dir=$OUTPUT_DIR "overrides=['++stage_cfg.athena_csv=/path/to/athena']"
# Read the packs from a local copy (or set SUMEDS_ONTOLOGY_SOURCE=/path/to/ontologies):
meds-extract-run spec=NWICU output_dir=$OUTPUT_DIR "overrides=['++stage_cfg.ontology_source=/path/to/ontologies']"
```

On a cluster whose compute nodes have no internet access, fill a cache on shared storage once from
a login node, then run with `offline`, so nothing tries the network:

```bash
# The same cache on the login node and the compute nodes:
export XDG_CACHE_HOME=/shared/project/cache
# On the login node, download the pinned pack release (about 30 MB):
suMEDS-enrich --prefetch --rules NWICU
# On a compute node:
meds-extract-run spec=NWICU output_dir=$OUTPUT_DIR "overrides=['++stage_cfg.offline=true']"
```

The rules add:

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
    dotted ICD-10-CM / ICD-9-CM code is validated against the pack and gives `vocabulary_id`,
    `concept_code` and every ancestor in the pack. The ETL's own parent stays first and suMEDS does
    not add it again, and the ancestors follow it (`DIAGNOSIS//ICD//10CM//I5023` gets
    `ICD10CM//I50.23`, `ICD10CM//I50.2`, `ICD10CM//I50`).
- **Gender** (`nwicu-gender`, an ontology rule): `GENDER//F` and `GENDER//M` get the OMOP Gender
    codes `Gender//F` and `Gender//M` (a tag: Gender has no public pack; with `--athena-csv`
    suMEDS validates them against Athena).
- **Parents among NWICU codes** (`nwicu-icd-parents-in-dataset`, a hierarchy rule): a diagnosis
    code of the table becomes the parent of another when its ICD code is the nearest ancestor
    present (`DIAGNOSIS//ICD//10CM//I5023` gets `DIAGNOSIS//ICD//10CM//I502` when both occur).

Every parent that a pack (or Athena) knows is named in `parent_names`, a map from the parent
code to its name (`map<string, string>` in parquet; suMEDS 0.6 replaced the earlier list aligned
with `parent_codes`). Tags and parents among NWICU codes have no entry; the latter are described
in their own rows.

The ETL alone no longer emits the LOINC parents of lab and chart codes (earlier builds wrote
`LOINC/<code>` for the same 50 itemids), and it never emitted ICD ancestors, Gender codes or
parents among NWICU codes; suMEDS supplies them. suMEDS never removes or rewrites the ETL's own
parents (`ICD10CM//…`, `NDC//…`) or descriptions: it only fills empty fields and appends parents.

## Summary statistics

[`tests/regression/full_summary_stats.json`](tests/regression/full_summary_stats.json) is a
[meds_summary_stats](https://github.com/Medical-Event-Data-Standard/meds_summary_stats) fingerprint of
the MEDS dataset this ETL builds from the full NWICU 0.1.0 release. `scripts/summary_stats.sh` builds
it with `meds-extract-run spec=NWICU`, so its code-metadata coverage includes the suMEDS enrichment. It
covers subject, event and measurement counts, digests of the code vocabulary, per-subject, value and
time distributions, code-metadata coverage, the splits and the schema. It names no code and reports no cell of fewer than 20 subjects and
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

Both print how the statistics changed against the committed baseline before overwriting it, and
refuse a build whose enrichment failed (finish it with `suMEDS-enrich` first). Add
`--compare` to check a build without writing anything; it exits 1 when
[`tests/regression/policy.yaml`](tests/regression/policy.yaml) flags an error. Rebuilding the same
commit reproduces the baseline exactly, so any finding is a change in the output. CI cannot rebuild the
credentialed release, so the [Summary stats workflow](.github/workflows/summary-stats.yaml) only warns
when a pull request changes `src/` (the config or the suMEDS rules) without regenerating the baseline. A
MEDS-Extract, suMEDS or polars upgrade can also move the output, so check it with `--compare`.

## Breaking changes

### Unreleased

- **Vocabulary parents are spelled `VOCABULARY//CODE`.** The `parent_codes` the ETL writes itself
    (`ICD9CM`, `ICD10CM`, `NDC`) used one slash, `NDC/12345678901`; they now use two,
    `NDC//12345678901`, the spelling suMEDS already writes for the parents it adds. Codes and events
    are unchanged. To migrate, respell old parents with the regex `^([^/]+)/(?!/)` → `\1//`. suMEDS
    and alignEHR already read both spellings as the same parent.

- **ICD codes name the vocabulary and its edition apart, `ICD//<edition>//<code>`.** Diagnoses
    `DIAGNOSIS//ICD//9//<code>` and `DIAGNOSIS//ICD//10//<code>` are now `DIAGNOSIS//ICD//9CM//<code>`
    and `DIAGNOSIS//ICD//10CM//<code>`: NWICU's `icd_version` 9 and 10 are the US billing editions
    ICD-9-CM and ICD-10-CM, as the ETL's `ICD9CM`/`ICD10CM` parents already said. Every MEDS ETL of
    this family now uses this layout (`ICD//10PCS`, `ICD//10GM`, `ICD//10CN`, ...). The code after
    the edition is unchanged (undotted, as NWICU records it), and so are its parents. A missing
    version is still `UNK`. To migrate, rename codes with the regex
    `^DIAGNOSIS//ICD//(9|10)//` → `DIAGNOSIS//ICD//\1CM//`.

- **Prescription end codes use `END`, not `STOP`** ([alignEHR#53](https://github.com/rvandewater/alignEHR/issues/53)):
    `MEDICATION//STOP//<drug>//<route>` is now `MEDICATION//END//<drug>//<route>`, the spelling all MEDS ETLs
    move to for the two ends of an interval, `<FAMILY>//START//…` and `<FAMILY>//END//…`. The start code, the events and the code
    metadata are otherwise unchanged. The end code keeps the route, which says which order it is; only the start
    ends in the dose unit, the unit of its value. To pair a start with its end, drop the start's last part and swap
    `START` for `END`.

    | Old                                 | New                                |
    | ----------------------------------- | ---------------------------------- |
    | `MEDICATION//STOP//<drug>//<route>` | `MEDICATION//END//<drug>//<route>` |

    To migrate, rewrite old codes with the regex `^MEDICATION//STOP//` → `MEDICATION//END//`.

- The unit in `LAB//{itemid}//{unit}` (labevents and chartevents) and
    `MEDICATION//START//{drug}//{route}//{dose unit}` is stripped of surrounding whitespace, and a
    blank one is `UNK`. Before, the unit was copied as recorded: a padded unit (` mg`) gave a code of
    its own, and a blank or empty one gave a code ending in whitespace or in `//`, with no `unit`. No
    output change on the synthetic data; codes change only where a unit was padded or blank. The
    route is unchanged. To migrate, strip the last segment of an old code and write `UNK` for an
    empty one: `^(.*//)\s*(\S(?:.*\S)?)?\s*$` → `\1\2`, then an empty last segment → `UNK`.

- **Intermediate stage outputs are no longer kept.** Up to 1.1.0, a run left each stage's output in
    `<output_dir>/<stage>/` (`convert_to_parquet/`, `convert_to_MEDS_events/`, `sumeds_enrich/`, …). The spec now sets MEDS-Extract's
    `etl.cleanup_intermediates: true`, so a successful run deletes those directories and keeps only
    `data/`, `metadata/`, `.logs/` and `.meds_extract_run/`. The MEDS data and metadata are
    unchanged. To migrate, add `"overrides=['cleanup_intermediates=false']"` to `meds-extract-run`
    wherever you read a stage directory after the run.

- **`codes.parquet` gains unit-free stem rows and stem parents for single-unit codes**
    ([#20](https://github.com/rvandewater/NWICU_MEDS/pull/20)). suMEDS's `sumeds_link_unit_siblings` now runs with `link_single_units: true`:
    every code that ends in its unit gets the code without the unit (its stem) as its last
    `parent_codes` entry, and the stem gets a row of its own (no unit, no events), also when the
    item has a single unit (`LAB//{itemid}//{unit}` gets `LAB//{itemid}`, `MEDICATION//START//{drug}//{route}//{unit}` gets `MEDICATION//START//{drug}//{route}`). Before, only items recorded in two or more units did. A prescription start without a recorded dose unit (`MEDICATION//START//{drug}//{route}//UNK`) gets its stem too (`unknown_unit_prefixes`).
    Events are unchanged. On a synthetic (MESSY-synth) build, 24 `MEDICATION//START` codes gain a stem parent (8 of them `…//UNK`) and 24 stem rows are added. To migrate, nothing is needed unless a tool expects every
    `codes.parquet` row to have events: drop the stem rows (no `code_template`, no `unit`), or
    ignore a parent that is the code without its last `//` component.

- A subject with a `patients.dod` but no `admissions.deathtime` no longer gets a second
    `MEDS_DEATH` at the `dischtime` of an admission discharged to `EXPIRED…`; their one death is at
    the `dod`. Before, `death_untimed` checked only the admission's `deathtime`. The full NWICU 0.1.0
    build had no such subject when `death_untimed` was added, so the release output should not
    change; a synthetic build had 1 of 40. To migrate, nothing is needed; to reproduce the old
    output, add a `MEDS_DEATH` at `dischtime` for those admissions.

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
