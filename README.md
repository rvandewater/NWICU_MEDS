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
export DATASET_DOWNLOAD_USERNAME=... DATASET_DOWNLOAD_PASSWORD=...

meds-extract-run spec=NWICU output_dir=$MEDS_COHORT_DIR
```

## Configuration

**This package contains no ETL code.** The entire pipeline is one file,
[`src/NWICU_MEDS/configs/messy.yaml`](src/NWICU_MEDS/configs/messy.yaml), registered under the
`MEDS_extract.pipelines` entry-point group.

Everything the old `pre_MEDS.py` did is now config:

| Was | Now |
| --- | --- |
| `fix_static_data` — earliest death time per subject | `_table.join` with `cols: {deathtime: min}`, then `dod_final: $deathtime ?? $dod` |
| DOB from `anchor_year - anchor_age` | `_table.cols`: `year_of_birth: ($anchor_year - $anchor_age)::str` |
| `add_discharge_time_by_hadm_id` | `_table.join` on `hadm_id` for `dischtime` |
| `add_icd_diagnosis_dot` | three `_table.cols` lines using slice + `len_chars` |
| Post-hoc `codes.parquet` rebuild | `_metadata` blocks against NWICU's own `d_labitems` / `d_items` |

### Code descriptions

Lab, chart-event and procedure codes get descriptions from NWICU's **own** item dictionaries via
`_metadata` blocks, joined on `itemid` alone so a label applies to every unit variant of a code.
This replaces the Python rebuild that existed because the MIMIC-IV crosswalks are keyed on MIMIC
itemids that never match NWICU's — a mismatch that now surfaces as a WARNING instead of silently
matching zero rows.


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
