"""The packaged suMEDS rules load in suMEDS and match the codes this ETL writes.

suMEDS validates the rules file itself (``sumeds.load_rules``) and resolves codes with the rule
objects its enrichment uses, so these tests only state what NWICU's codes must resolve to. The
example codes are rendered from the ETL's own ``messy.yaml`` templates with synthetic values.
"""

import re
from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from sumeds import OntologyRules, load_rules

from NWICU_MEDS import MESSY_CFG, __package_name__

RULES_FP = Path(__file__).parents[1] / "src" / "NWICU_MEDS" / "sumeds_rules.yaml"
ICD_RULES = {"10": "nwicu-icd10cm-diagnoses", "9": "nwicu-icd9cm-diagnoses"}


@pytest.fixture(scope="module")
def rules() -> OntologyRules:
    return load_rules(RULES_FP)


@pytest.fixture(scope="module")
def raw_cfg() -> dict:
    return yaml.safe_load(Path(str(MESSY_CFG)).read_text())


def _rule(rules: OntologyRules, rule_id: str):
    for rule in (*rules.vocabulary_rules, *rules.hierarchy):
        if rule.id == rule_id:
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


def test_rules_file_is_packaged():
    assert files(__package_name__).joinpath("sumeds_rules.yaml").is_file()


def test_rules_load_in_sumeds():
    """suMEDS rejects any malformed rule."""
    load_rules(RULES_FP)


def test_icd_parents_come_from_the_icd_rules(rules: OntologyRules):
    rule = _rule(rules, "nwicu-icd-parents-in-dataset")
    assert rule.mode == "ontology"
    assert set(rule.rules) == set(ICD_RULES.values())


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
    resolved = {rule.id: rule.resolve(code) for rule in rules.ontology}
    assert {k: v for k, v in resolved.items() if v is not None} == {
        ICD_RULES[version]: expected
    }


def test_icd_rules_skip_unknown_versions(raw_cfg, rules):
    template = raw_cfg["data/nw_hosp/diagnoses_icd"]["diagnosis"]["code"]
    for code in (_render(template), _render(template, icd_version="10")):
        for rule in rules.ontology:
            assert rule.resolve(code) is None, (rule.id, code)


def test_gender_rule(raw_cfg, rules):
    template = raw_cfg["data/nw_hosp/patients"]["gender"]["code"]
    rule = _rule(rules, "nwicu-gender")
    assert rule.resolve(_render(template, gender="F")) == "F"
    assert rule.resolve(_render(template, gender="M")) == "M"
    assert rule.resolve(_render(template)) is None  # GENDER//UNK


@pytest.mark.parametrize(
    "table,event",
    [("data/nw_hosp/labevents", "lab"), ("data/nw_icu/chartevents", "event")],
)
@pytest.mark.parametrize("unit", ["mg/dL", "%", "/hpf", "UNK"])
def test_lab_loinc_crosswalk_key_is_the_itemid(raw_cfg, rules, table, event, unit):
    rule = _rule(rules, "nwicu-lab-loinc")
    template = raw_cfg[table][event]["code"]
    code = _render(template, itemid="123456", valueuom=unit)
    assert code == f"LAB//123456//{unit}"
    assert rule.key(code) == "123456"
    assert rule.key(_render(template)) is None  # LAB//UNK//UNK


def test_lab_loinc_crosswalk_skips_other_families(raw_cfg, rules):
    rule = _rule(rules, "nwicu-lab-loinc")
    for table, event in (
        ("data/nw_icu/procedureevents", "start"),
        ("data/nw_icu/procedureevents", "end"),
    ):
        code = _render(raw_cfg[table][event]["code"], itemid="123456")
        assert rule.key(code) is None, code
