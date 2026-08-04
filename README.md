# NWICU MEDS Extraction ETL

[![PyPI - Version](https://img.shields.io/pypi/v/NWICU_MEDS)](https://pypi.org/project/NWICU_MEDS/)
[![codecov](https://codecov.io/gh/rvandewater/NWICU_MEDS/graph/badge.svg?token=RW6JXHNT0W)](https://codecov.io/gh/rvandewater/NWICU_MEDS)
[![tests](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/tests.yaml/badge.svg)](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/tests.yml)
[![code-quality](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/code-quality-main.yaml/badge.svg)](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/code-quality-main.yaml)
[![Documentation](https://readthedocs.org/projects/nwicu-meds/badge/?version=latest)](https://nwicu-meds.readthedocs.io/en/latest/)
[![Python Version](https://img.shields.io/pypi/pyversions/NWICU_MEDS.svg)](https://pypi.python.org/pypi/NWICU_MEDS/)
[![license](https://img.shields.io/badge/License-MIT-green.svg?labelColor=gray)](https://github.com/rvandewater/NWICU_MEDS#license)
[![PRs](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/rvandewater/NWICU_MEDS/pulls)
[![contributors](https://img.shields.io/github/contributors/rvandewater/NWICU_MEDS.svg)](https://github.com/rvandewater/NWICU_MEDS/graphs/contributors)
[![DOI](https://zenodo.org/badge/913786544.svg)](https://doi.org/10.5281/zenodo.14892134)
[![MEDS v0.3.3](https://img.shields.io/badge/MEDS-0.3.3-blue)](https://medical-event-data-standard.github.io/)

This pipeline extracts the NWICU dataset (from physionet, https://physionet.org/content/nwicu-northwestern-icu/0.1.0/) into the MEDS format.

## Usage:

```bash
pip install NWICU_MEDS
export DATASET_DOWNLOAD_USERNAME=$PHYSIONET_USERNAME
export DATASET_DOWNLOAD_PASSWORD=$PHYSIONET_PASSWORD
MEDS_extract-NWICU root_output_dir=$ROOT_OUTPUT_DIR
```

When you run this, the program will:

1. Download the needed raw NWICU files for the currently supported version into
    `$ROOT_OUTPUT_DIR/raw_input`.
2. Perform initial, pre-MEDS processing on the raw NWICU files, saving the results in
    `$ROOT_OUTPUT_DIR/pre_MEDS`.
3. Construct the final MEDS cohort, and save it to `$ROOT_OUTPUT_DIR/MEDS_cohort`.

You can also specify the target directories more directly, with

```bash
export DATASET_DOWNLOAD_USERNAME=$PHYSIONET_USERNAME
export DATASET_DOWNLOAD_PASSWORD=$PHYSIONET_PASSWORD
MEDS_extract-NWICU raw_input_dir=$RAW_INPUT_DIR pre_MEDS_dir=$PRE_MEDS_DIR MEDS_cohort_dir=$MEDS_COHORT_DIR
```

## Examples and More Info:

You can run `MEDS_extract-NWICU --help` for more information on the arguments and options. You can also run

```bash
MEDS_extract-NWICU root_output_dir=$ROOT_OUTPUT_DIR
```

to run the entire pipeline.

## Configuration

The entire ETL is described by one file, `src/NWICU_MEDS/configs/messy.yaml` — a
[MESSY](https://github.com/mmcdermott/MEDS_extract) config carrying three sections:

- **`sources:`** — where the raw data lives. `meds-extract-download` stages it, with SHA-256
    verification and resumable transfers. This replaces the old hand-rolled `download.py`.
- **`etl:`** — the dataset name plus curated stage options (`n_subjects_per_shard`).
- **the event tables** — what to extract, written in
    [dftly](https://github.com/mmcdermott/dftly) expressions.

Because the config is registered under the `MEDS_extract.pipelines` entry-point group, the
extraction half is runnable directly, without this package's CLI wrapper:

```bash
# Stage the raw data only:
meds-extract-download spec=NWICU output_dir=$RAW_INPUT_DIR

# Run the canonical 8-stage pipeline over already-pre-MEDS'd data:
meds-extract-run spec=NWICU output_dir=$MEDS_COHORT_DIR download_key=null input_dir=$PRE_MEDS_DIR
```

### Code descriptions

Lab, chart-event and procedure codes get their descriptions from NWICU's **own** item
dictionaries (`nw_hosp/d_labitems`, `nw_icu/d_items`) via `_metadata` blocks in the config,
joined on `itemid` alone so a label applies to every unit variant of a code.

This replaces the post-hoc `codes.parquet` rebuild the ETL used to perform in Python. It was
needed because the MIMIC-IV crosswalks NWICU shipped are keyed on MIMIC itemids that never match
NWICU's own itemid space, so they matched zero rows silently. Under MEDS-Extract 0.7 a
`_metadata` join that matches nothing emits a WARNING, and join keys are dtype-normalized, so
this class of silent mismatch is now visible in the logs.

## Citation

If you find our work useful, please cite the resource through the github repository (or the bibtex entry below), and cite the original dataset through PhysioNet. The following is the recommended citation for this package:

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
