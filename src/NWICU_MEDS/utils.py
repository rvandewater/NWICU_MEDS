"""Small filesystem helpers the pre-MEDS step needs.

These used to be imported from ``MEDS_transforms.utils``, but that module was pared back over the
0.3-0.6 series and ``get_shard_prefix`` / ``write_lazyframe`` no longer exist there (as of
MEDS-Transforms 0.6.7 the module exports only ``PKG_PFX``, ``Path``, ``files``, ``os`` and
``resolve_pkg_path``). They are small and purely local, so they live here now rather than
tracking an upstream module that no longer wants them.
"""

from collections.abc import Callable
from pathlib import Path

import polars as pl


def get_shard_prefix(base_path: Path, fp: Path) -> str:
    """Extract the table prefix from a file path by removing ``base_path`` and all suffixes.

    Args:
        base_path: The base path to strip.
        fp: The file path to extract the prefix from.

    Returns:
        The file path relative to ``base_path``, with every suffix removed.

    Examples:
        >>> get_shard_prefix(Path("/a/b/c"), Path("/a/b/c/d.parquet"))
        'd'
        >>> get_shard_prefix(Path("/a/b/c"), Path("/a/b/c/d/e.csv.gz"))
        'd/e'
    """
    relative_path = fp.relative_to(base_path)
    relative_parent = relative_path.parent
    file_name = relative_path.name.split(".")[0]

    return str(relative_parent / file_name)


def write_lazyframe(df: pl.LazyFrame, out_fp: Path) -> None:
    """Collect ``df`` if needed and write it to ``out_fp`` as parquet, creating parent dirs.

    Args:
        df: The frame to write. Eager frames are accepted and written as-is.
        out_fp: The destination parquet path.

    Examples:
        >>> import tempfile
        >>> tmp = Path(tempfile.mkdtemp())
        >>> write_lazyframe(pl.LazyFrame({"a": [1, 2]}), tmp / "nested" / "out.parquet")
        >>> pl.read_parquet(tmp / "nested" / "out.parquet")["a"].to_list()
        [1, 2]
    """
    if isinstance(df, pl.LazyFrame):
        df = df.collect()
    out_fp.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out_fp, use_pyarrow=True)


# Suffixes to try, in preference order, when resolving a table prefix to a real file.
SUPPORTED_SUFFIXES = (".parquet", ".csv.gz", ".csv")


def get_supported_fp(root_dir: Path, file_prefix: str | Path) -> tuple[Path, Callable]:
    """Resolve a table prefix to the best available file, with a reader for it.

    This used to come from ``MEDS_transforms.extract.utils``; that module moved into MEDS-Extract
    over the 0.5/0.6 series and no longer exposes this helper.

    Args:
        root_dir: The directory to search.
        file_prefix: The table prefix to resolve (may contain ``/``).

    Returns:
        A ``(path, reader)`` pair, where ``reader`` returns a `pl.LazyFrame` for that path.

    Raises:
        FileNotFoundError: If no file exists with the prefix and any supported suffix.

    Examples:
        >>> import tempfile
        >>> tmp = Path(tempfile.mkdtemp())
        >>> pl.DataFrame({"a": [1, 2]}).write_csv(tmp / "test.csv")
        >>> fp, reader = get_supported_fp(tmp, "test")
        >>> fp.name
        'test.csv'
        >>> reader(fp).collect()["a"].to_list()
        [1, 2]

        Parquet wins over csv when both are present:

        >>> pl.DataFrame({"a": [3]}).write_parquet(tmp / "test.parquet")
        >>> get_supported_fp(tmp, "test")[0].name
        'test.parquet'

        A prefix with no matching file is an error:

        >>> get_supported_fp(tmp, "nope")
        Traceback (most recent call last):
            ...
        FileNotFoundError: No files found with prefix: nope and allowed suffixes ...
    """
    for suffix in SUPPORTED_SUFFIXES:
        fp = root_dir / f"{file_prefix}{suffix}"
        if fp.exists():
            reader = pl.scan_parquet if suffix == ".parquet" else pl.scan_csv
            return fp, reader

    raise FileNotFoundError(
        f"No files found with prefix: {file_prefix} and allowed suffixes "
        f"{list(SUPPORTED_SUFFIXES)}"
    )
