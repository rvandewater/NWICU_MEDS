"""MEDS_DEATH over the synthetic release of ``conftest.py``: at most one per subject."""

from datetime import datetime

import polars as pl


def test_one_death_per_subject(events: pl.DataFrame):
    """Each subject dies at most once: at the earliest admissions.deathtime, else patients.dod, else
    (a discharge to EXPIRED with neither) at that admission's dischtime.

    Patient 3 has a dod and an EXPIRED discharge without a deathtime; before the dod guard of
    `death_untimed`, they died twice.
    """
    deaths = events.filter(pl.col("code") == "MEDS_DEATH").sort("subject_id")
    assert deaths["subject_id"].is_unique().all()
    assert dict(zip(deaths["subject_id"], deaths["time"], strict=True)) == {
        2: datetime(2160, 3, 2, 18),
        3: datetime(2171, 5, 1),
        4: datetime(2181, 1, 3, 12),
    }
