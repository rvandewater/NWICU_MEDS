"""A tiny, fully synthetic NWICU-shaped release and one plain ETL run over it, shared by the tests.

NWICU is credentialed-access (no open demo), so the tests cannot download it. Instead this writes a
handful of made-up rows with the release's layout -- the tables under ``data/nw_hosp/`` and
``data/nw_icu/``, with the columns ``messy.yaml`` reads, which NWICU keeps from MIMIC-IV -- and runs
``meds-extract-run spec=NWICU`` on them with ``do_download=false``. No values here come from the
real dataset; the item ids, titles and labels are invented.

The rows cover every event of the config and the code families the suMEDS rules act on:

- undotted ICD-10 and ICD-9 diagnoses (including an ICD-9 E code), one of them the parent of
  another (``I502`` and ``I5023``), and one that is not in the synthetic ICD-10-CM pack of
  ``test_run_with_enrichment.py`` (``R4689``);
- ``LAB//{itemid}//{unit}`` codes from ``labevents`` and from ``chartevents``, some of whose item
  ids are in the synthetic ``nwicu/loinc_parents`` crosswalk and some not;
- ``GENDER//F`` and ``GENDER//M``;
- prescriptions with a 3-segment NDC, so their codes carry an ``NDC/...`` parent from the ETL.
"""

import subprocess
from pathlib import Path

import polars as pl
import pytest

# Patients 1-4. MEDS-Extract needs >= 1 per train/tuning/held_out split. Patient 2 dies in
# hospital (admissions.deathtime); patient 3 has a dod but no deathtime.
PATIENTS = """\
subject_id,gender,anchor_age,anchor_year,dod
1,F,60,2150,
2,M,45,2160,2160-03-02
3,F,70,2170,2171-05-01
4,M,30,2180,
"""

ADMISSIONS = """\
subject_id,hadm_id,admittime,dischtime,deathtime,admission_type,admission_location,\
discharge_location,insurance,language,marital_status,race,edregtime,edouttime
1,101,2150-01-01 10:00:00,2150-01-05 12:00:00,,EW EMER.,EMERGENCY ROOM,HOME,Medicare,ENGLISH,\
MARRIED,WHITE,2150-01-01 08:00:00,2150-01-01 10:30:00
2,201,2160-03-01 09:00:00,2160-03-02 18:00:00,2160-03-02 18:00:00,URGENT,TRANSFER FROM HOSPITAL,\
EXPIRED,Medicaid,ENGLISH,SINGLE,BLACK,,
3,301,2170-06-01 14:00:00,2170-06-03 11:00:00,,ELECTIVE,PHYSICIAN REFERRAL,HOME HEALTH CARE,\
Other,,WIDOWED,,2170-06-01 12:00:00,2170-06-01 14:30:00
4,401,2180-09-10 07:00:00,2180-09-12 15:00:00,,EW EMER.,EMERGENCY ROOM,HOME,Private,ENGLISH,\
SINGLE,WHITE,2180-09-10 05:00:00,2180-09-10 07:15:00
"""

DIAGNOSES_ICD = """\
subject_id,hadm_id,seq_num,icd_code,icd_version
1,101,1,I5023,10
1,101,2,E119,10
2,201,1,I502,10
2,201,2,R4689,10
3,301,1,4019,9
3,301,2,E8889,9
4,401,1,I5023,10
"""

D_ICD_DIAGNOSES = """\
icd_code,icd_version,long_title
I5023,10,Synthetic diagnosis title I5023
E119,10,Synthetic diagnosis title E119
I502,10,Synthetic diagnosis title I502
R4689,10,Synthetic diagnosis title R4689
4019,9,Synthetic diagnosis title 4019
E8889,9,Synthetic diagnosis title E8889
"""

EMAR = """\
subject_id,hadm_id,emar_id,emar_seq,charttime,medication,event_txt
1,101,1-1,1,2150-01-02 08:00:00,Synthetic drug A,Administered
2,201,2-1,1,2160-03-01 12:00:00,Synthetic drug B,Not Given
"""

# 900001 and 900002 are in the synthetic crosswalk, 900003 is not.
LABEVENTS = """\
subject_id,hadm_id,itemid,charttime,value,valuenum,valueuom,priority
1,101,900001,2150-01-02 06:00:00,1.1,1.1,mg/dL,ROUTINE
1,101,900002,2150-01-02 06:00:00,140,140,mEq/L,ROUTINE
2,201,900001,2160-03-01 10:00:00,2.4,2.4,mg/dL,STAT
3,301,900003,2170-06-02 06:00:00,Negative,,,
4,401,900001,2180-09-11 06:00:00,0.9,0.9,mg/dL,ROUTINE
"""

D_LABITEMS = """\
itemid,label
900001,Synthetic lab A
900002,Synthetic lab B
900003,Synthetic lab C
"""

PRESCRIPTIONS = """\
subject_id,hadm_id,pharmacy_id,starttime,stoptime,drug,ndc,dose_val_rx,dose_unit_rx,route
1,101,11,2150-01-02 09:00:00,2150-01-04 09:00:00,Synthetic drug A,12345-6789-01,10,mg,PO
3,301,31,2170-06-01 16:00:00,2170-06-02 16:00:00,Synthetic drug C,,5,mL,IV
"""

ICUSTAYS = """\
subject_id,hadm_id,stay_id,first_careunit,last_careunit,intime,outtime
1,101,1001,Synthetic ICU A,Synthetic ICU A,2150-01-01 11:00:00,2150-01-03 11:00:00
2,201,2001,Synthetic ICU B,Synthetic ICU A,2160-03-01 09:30:00,2160-03-02 18:00:00
4,401,4001,Synthetic ICU A,Synthetic ICU B,2180-09-10 08:00:00,2180-09-11 20:00:00
"""

# 800001 is in the synthetic crosswalk, 800002 is not (a procedure item).
CHARTEVENTS = """\
subject_id,hadm_id,stay_id,charttime,itemid,value,valuenum,valueuom
1,101,1001,2150-01-01 12:00:00,800001,88,88,bpm
2,201,2001,2160-03-01 10:00:00,800001,120,120,bpm
4,401,4001,2180-09-10 09:00:00,800001,72,72,bpm
"""

D_ITEMS = """\
itemid,label
800001,Synthetic chart item A
800002,Synthetic procedure A
"""

PROCEDUREEVENTS = """\
subject_id,hadm_id,stay_id,starttime,endtime,itemid
1,101,1001,2150-01-01 13:00:00,2150-01-01 14:00:00,800002
4,401,4001,2180-09-10 10:00:00,2180-09-10 10:30:00,800002
"""

TABLES = {
    "data/nw_hosp/patients": PATIENTS,
    "data/nw_hosp/admissions": ADMISSIONS,
    "data/nw_hosp/diagnoses_icd": DIAGNOSES_ICD,
    "data/nw_hosp/d_icd_diagnoses": D_ICD_DIAGNOSES,
    "data/nw_hosp/emar": EMAR,
    "data/nw_hosp/labevents": LABEVENTS,
    "data/nw_hosp/d_labitems": D_LABITEMS,
    "data/nw_hosp/prescriptions": PRESCRIPTIONS,
    "data/nw_icu/icustays": ICUSTAYS,
    "data/nw_icu/chartevents": CHARTEVENTS,
    "data/nw_icu/d_items": D_ITEMS,
    "data/nw_icu/procedureevents": PROCEDUREEVENTS,
}


@pytest.fixture(scope="session")
def raw_dir(tmp_path_factory) -> Path:
    """The synthetic tables, laid out as the raw NWICU release (the directory holding ``data/``)."""
    raw_dir = tmp_path_factory.mktemp("nwicu_raw")
    for prefix, content in TABLES.items():
        fp = raw_dir / f"{prefix}.csv"
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
    return raw_dir


def run_command(argv: list[str]) -> str:
    """Run a CLI, failing the test with its full output if it does not succeed; return its stderr."""
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode == 0, (
        f"{argv[0]} failed with exit code {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stderr


@pytest.fixture(scope="session")
def meds_output(tmp_path_factory, raw_dir: Path) -> Path:
    """The plain ETL (no suMEDS) over the synthetic release."""
    output_dir = tmp_path_factory.mktemp("nwicu") / "MEDS_cohort"
    run_command(
        [
            "meds-extract-run",
            "spec=NWICU",
            f"output_dir={output_dir}",
            "do_download=false",
            f"input_dir={raw_dir}",
        ]
    )
    return output_dir


@pytest.fixture(scope="session")
def events(meds_output: Path) -> pl.DataFrame:
    return pl.concat(
        [pl.read_parquet(fp) for fp in (meds_output / "data").rglob("*.parquet")]
    )


@pytest.fixture(scope="session")
def codes(meds_output: Path) -> pl.DataFrame:
    return pl.read_parquet(meds_output / "metadata" / "codes.parquet")
