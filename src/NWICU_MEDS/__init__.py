"""NWICU MEDS ETL -- a pure-config MEDS-Extract pipeline.

This package contains no ETL code. The entire pipeline is `messy.yaml`, registered under
the `MEDS_extract.pipelines` entry-point group, and its suMEDS enrichment rules are
`sumeds_rules.yaml`, registered under the same name in the `sumeds.rules` group. The ETL
followed by the enrichment of its code metadata runs as:

    suMEDS-extract spec=NWICU output_dir=$OUTPUT_DIR

and the ETL alone as `meds-extract-run spec=NWICU output_dir=$OUTPUT_DIR`.
"""

from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files

__package_name__ = "NWICU_MEDS"
try:
    __version__ = version(__package_name__)
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

# The name this ETL registers under `MEDS_extract.pipelines` and its rules under `sumeds.rules`;
# `meds-extract-run spec=NWICU` and `suMEDS-extract spec=NWICU` resolve it, and MEDS-Extract uses
# it as the default dataset name.
PIPELINE_NAME = "NWICU"

MESSY_CFG = files(__package_name__).joinpath("messy.yaml")

__all__ = ["MESSY_CFG", "PIPELINE_NAME", "__package_name__", "__version__"]
