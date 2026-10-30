"""The packaged suMEDS rules file parses and its rules match the codes this ETL writes.

suMEDS is not a dependency of the ETL, so the structural checks mirror its loader
(``sumeds.ontology.load_rules``, format ``sumeds-rules/0.1``) with ``yaml`` and ``re`` only, and
the example codes are rendered from the ETL's own ``messy.yaml`` templates with synthetic values.
"""

import re
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

from NWICU_MEDS import MESSY_CFG, __package_name__

SCHEMA = "sumeds-rules/0.1"
TOP_LEVEL_KEYS = {"schema", "ontology", "crosswalk", "hierarchy"}
ONTOLOGY_KEYS = {"id", "pattern", "vocabulary", "normalize", "validate"}
CROSSWALK_KEYS = {
    "id",
    "pattern",
    "table",
    "key_column",
    "code_column",
    "vocabulary",
    "where",
    "normalize",
    "validate",
}
HIERARCHY_KEYS = {
    "id",
    "pattern",
    "group",
    "mode",
    "separator",
    "ignore",
    "nearest_only",
    "from_ontology",
    "rules",
}
VALIDATE_MODES = {"pack", "athena", "none"}
TEMPLATE_REFERENCE = re.compile(r"\\(?:g<([^>]*)>|(\d{1,2}))")


@pytest.fixture(scope="module")
def rules() -> dict:
    path = files(__package_name__) / "sumeds_rules.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw_cfg() -> dict:
    return yaml.safe_load(Path(str(MESSY_CFG)).read_text())


def _rule(rules: dict, rule_id: str) -> dict:
    for kind in ("ontology", "crosswalk", "hierarchy"):
        for rule in rules.get(kind) or []:
            if rule["id"] == rule_id:
                return rule
    raise KeyError(rule_id)


def _render(template: str, **values: str) -> str:
    """Render an ``f"..."`` code template of ``messy.yaml`` with synthetic column values."""
    body = re.fullmatch(r'\s*f"(.*)"\s*', template, flags=re.S).group(1)
    return re.sub(
        r"\{\s*\$(\w+)(?:\s*\?\?\s*'[^']*')?\s*\}",
        lambda m: values.get(m.group(1), "UNK"),
        body,
    )


def _resolve(rule: dict, code: str) -> str | None:
    """The vocabulary code suMEDS derives from ``code`` with an ontology rule."""
    match = re.search(rule["pattern"], code)
    if match is None or match.group("code") is None:
        return None
    value = match.group("code")
    for step in rule.get("normalize") or []:
        value = re.sub(step["pattern"], step["replace"], value)
    return value


def test_rules_file_is_valid_sumeds_rules(rules: dict):
    assert rules["schema"] == SCHEMA
    assert set(rules) <= TOP_LEVEL_KEYS
    seen = set()
    vocabulary_ids = set()
    for kind, allowed, group in (
        ("ontology", ONTOLOGY_KEYS, "code"),
        ("crosswalk", CROSSWALK_KEYS, "key"),
    ):
        for rule in rules.get(kind) or []:
            assert set(rule) <= allowed, (rule["id"], set(rule) - allowed)
            assert rule["id"] and rule["id"] not in seen
            seen.add(rule["id"])
            vocabulary_ids.add(rule["id"])
            assert group in re.compile(rule["pattern"]).groupindex, rule["id"]
            assert rule["vocabulary"] and "/" not in rule["vocabulary"]
            assert rule.get("validate", "pack") in VALIDATE_MODES
            for step in rule.get("normalize") or []:
                assert set(step) == {"pattern", "replace"}
                compiled = re.compile(step["pattern"])
                for name, number in TEMPLATE_REFERENCE.findall(step["replace"]):
                    if number:
                        assert int(number) <= compiled.groups
                    else:
                        assert name in compiled.groupindex
            if kind == "crosswalk":
                assert re.fullmatch(
                    r"[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*", rule["table"]
                )
                assert rule["key_column"] and rule["code_column"]
    for rule in rules.get("hierarchy") or []:
        assert set(rule) <= HIERARCHY_KEYS, (rule["id"], set(rule) - HIERARCHY_KEYS)
        assert rule["id"] and rule["id"] not in seen
        seen.add(rule["id"])
        assert isinstance(rule.get("nearest_only", True), bool)
        if rule.get("from_ontology"):
            assert set(rule) <= {"id", "from_ontology", "nearest_only", "rules"}
            assert set(rule.get("rules") or []) <= vocabulary_ids
            continue
        assert rule["group"] in re.compile(rule["pattern"]).groupindex, rule["id"]
        if (
            rule.get("mode", "separator" if "separator" in rule else None)
            == "separator"
        ):
            assert rule["separator"] and "ignore" not in rule
        else:
            assert rule["mode"] == "prefix" and "separator" not in rule


@pytest.mark.parametrize(
    "version,icd_code,expected",
    [
        ("10", "I5023", "I50.23"),
        ("10", "E119", "E11.9"),
        ("10", "Z87891", "Z87.891"),
        ("10", "A41", "A41"),
        ("9", "4019", "401.9"),
        ("9", "0389", "038.9"),
        ("9", "V1052", "V10.52"),
        ("9", "E8889", "E888.9"),
        ("9", "428", "428"),
    ],
)
def test_icd_rules_restore_the_dot(raw_cfg, rules, version, icd_code, expected):
    template = raw_cfg["data/nw_hosp/diagnoses_icd"]["diagnosis"]["code"]
    code = _render(template, icd_version=version, icd_code=icd_code)
    assert code == f"DIAGNOSIS//ICD//{version}//{icd_code}"
    own = {"10": "nwicu-icd10cm-diagnoses", "9": "nwicu-icd9cm-diagnoses"}[version]
    other = {"10": "nwicu-icd9cm-diagnoses", "9": "nwicu-icd10cm-diagnoses"}[version]
    assert _resolve(_rule(rules, own), code) == expected
    assert _resolve(_rule(rules, other), code) is None


def test_icd_rules_skip_unknown_versions(raw_cfg, rules):
    template = raw_cfg["data/nw_hosp/diagnoses_icd"]["diagnosis"]["code"]
    for code in (_render(template), _render(template, icd_version="10")):
        for rule in rules["ontology"]:
            assert _resolve(rule, code) is None, (rule["id"], code)


def test_gender_rule(raw_cfg, rules):
    template = raw_cfg["data/nw_hosp/patients"]["gender"]["code"]
    rule = _rule(rules, "nwicu-gender")
    assert _resolve(rule, _render(template, gender="F")) == "F"
    assert _resolve(rule, _render(template, gender="M")) == "M"
    assert _resolve(rule, _render(template)) is None  # GENDER//UNK


@pytest.mark.parametrize(
    "table,event",
    [("data/nw_hosp/labevents", "lab"), ("data/nw_icu/chartevents", "event")],
)
@pytest.mark.parametrize("unit", ["mg/dL", "%", "/hpf", "UNK"])
def test_lab_loinc_crosswalk_key_is_the_itemid(raw_cfg, rules, table, event, unit):
    pattern = re.compile(_rule(rules, "nwicu-lab-loinc")["pattern"])
    template = raw_cfg[table][event]["code"]
    code = _render(template, itemid="123456", valueuom=unit)
    assert code == f"LAB//123456//{unit}"
    assert pattern.search(code).group("key") == "123456"
    assert pattern.search(_render(template)) is None  # LAB//UNK//UNK


def test_lab_loinc_crosswalk_skips_other_families(raw_cfg, rules):
    pattern = re.compile(_rule(rules, "nwicu-lab-loinc")["pattern"])
    for table, event in (
        ("data/nw_icu/procedureevents", "start"),
        ("data/nw_icu/procedureevents", "end"),
    ):
        code = _render(raw_cfg[table][event]["code"], itemid="123456")
        assert pattern.search(code) is None, code
