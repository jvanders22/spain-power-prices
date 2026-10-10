from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from conftest import synthetic_inputs

from spain_power import case_study, findings
from spain_power.cache import PROCESSED
from spain_power.transform import build_hourly

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_case_study.py"
README = f"# Title\n\nintro\n\n{case_study.START}\nold\n{case_study.END}\n\n## After\n"


@pytest.fixture(scope="module")
def frame():
    return build_hourly(*synthetic_inputs("2024-10-01", "2025-11-30 23:00"))


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("build_case_study", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_uses_findings_numbers(frame):
    md = case_study.render(frame)
    h = findings.headline(frame)
    assert md.startswith("# Case study")
    for section in ["Problem", "Data", "Method", "Findings", "Engineering choices", "Tests and CI"]:
        assert f"\n## {section}\n" in md
    assert f"{h['hours']:,} hourly rows" in md
    assert f"correlate at\n  {h['corr_price_renewables']:.2f}" in md
    assert "1 Oct 2024 to 30 Nov 2025" in md
    assert "nan" not in md.lower()
    assert case_study.render(frame) == md


def test_render_needs_two_windows(hourly):
    with pytest.raises(ValueError, match="two comparison windows"):
        case_study.render(hourly)


def test_update_readme_replaces_block_and_demotes_headings():
    out = case_study.update_readme(README, "# Case study\n\n## Problem\n\ntext\n")
    assert out == (
        f"# Title\n\nintro\n\n{case_study.START}\n## Case study\n\n### Problem\n\ntext\n"
        f"{case_study.END}\n\n## After\n"
    )
    assert case_study.update_readme(out, "# Case study\n\n## Problem\n\ntext\n") == out
    with pytest.raises(ValueError, match="case-study:start"):
        case_study.update_readme("no markers", "# x")


def test_script_writes_then_check_passes_and_detects_staleness(script, frame, tmp_path, capsys):
    data, readme, doc = tmp_path / "hourly.parquet", tmp_path / "README.md", tmp_path / "docs" / "cs.md"
    frame.to_parquet(data, index=False)
    readme.write_text(README, encoding="utf-8")
    args = ["--data", str(data), "--readme", str(readme), "--doc", str(doc)]

    assert script.main([*args, "--check"]) == 1
    assert not doc.exists() and readme.read_text(encoding="utf-8") == README

    assert script.main(args) == 0
    assert doc.read_text(encoding="utf-8") == case_study.render(frame)
    assert "### Findings" in readme.read_text(encoding="utf-8")
    assert script.main([*args, "--check"]) == 0

    doc.write_text(doc.read_text(encoding="utf-8").replace("Problem", "Probelm"), encoding="utf-8")
    assert script.main([*args, "--check"]) == 1
    assert "out of date" in capsys.readouterr().err


@pytest.mark.skipif(not PROCESSED.exists(), reason="no data/processed/hourly.parquet")
def test_repo_case_study_is_up_to_date(script):
    assert script.main(["--check"]) == 0, "run: python scripts/build_case_study.py"
