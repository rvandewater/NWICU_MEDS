# NWICU MEDS Extraction ETL

[![PyPI - Version](https://img.shields.io/pypi/v/NWICU-MEDS)](https://pypi.org/project/NWICU-MEDS/)
[![Documentation Status](https://readthedocs.org/projects/meds-transforms/badge/?version=latest)](https://meds-transforms.readthedocs.io/en/latest/?badge=latest)
[![codecov](https://codecov.io/gh/rvandewater/NWICU_MEDS/graph/badge.svg?token=E7H6HKZV3O)](https://codecov.io/gh/rvandewater/NWICU_MEDS)
[![tests](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/tests.yaml/badge.svg)](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/tests.yml)
[![code-quality](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/code-quality-main.yaml/badge.svg)](https://github.com/rvandewater/NWICU_MEDS/actions/workflows/code-quality-main.yaml)
![python](https://img.shields.io/badge/-Python_3.11-blue?logo=python&logoColor=white)
[![license](https://img.shields.io/badge/License-MIT-green.svg?labelColor=gray)](https://github.com/rvandewater/NWICU_MEDS#license)
[![PRs](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/rvandewater/NWICU_MEDS/pulls)
[![contributors](https://img.shields.io/github/contributors/rvandewater/NWICU_MEDS.svg)](https://github.com/rvandewater/NWICU_MEDS/graphs/contributors)

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
MEDS_extract-NWICU root_output_dir=$ROOT_OUTPUT_DIR do_demo=True
```

to run the entire pipeline over the publicly available, fully open NWICU demo dataset.
