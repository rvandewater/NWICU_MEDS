# MIMIC-IV MEDS Extraction ETL

This pipeline extracts the MIMIC-IV dataset (from physionet) into the MEDS format.

## Usage:

```bash
pip install MIMIC_IV_MEDS
MEDS_extract-MIMIC_IV raw_input_dir=$RAW_INPUT pre_MEDS_dir=$PRE_MEDS MEDS_cohort_dir=$COHORT
```

## Examples and More Info:

You can run `MEDS_extract-MIMIC_IV --help` for more information on the arguments and options. You can also run

```bash
MEDS_extract-MIMIC_IV raw_input_dir=$RAW_INPUT pre_MEDS_dir=$PRE_MEDS MEDS_cohort_dir=$COHORT do_demo=True
```

to run the entire pipeline over the publicly available, fully open MIMIC-IV demo dataset.
