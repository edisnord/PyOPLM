#!/usr/bin/env python3

from pathlib import Path

import pytest

from pyoplm.storage import csv_delete_cols_to_dict


def _write(tmp_path: Path, content: str) -> str:
    csv_file = tmp_path / "LIST.CSV"
    csv_file.write_text(content, encoding="utf-8")
    return csv_file.as_uri()


def test_comma_delimiter(tmp_path: Path):
    uri = _write(tmp_path, '"sep=,"\nID,ID2,Title\n'
                 'SLUS-20562,SLUS_205.62,"Max Payne"\n'
                 'SLUS-20267,SLUS_202.67,".hack//Infection"\n')
    result = csv_delete_cols_to_dict(uri, ["ID"])
    assert result["SLUS_205.62"] == "Max Payne"
    assert result["SLUS_202.67"] == ".hack//Infection"


def test_semicolon_delimiter(tmp_path: Path):
    uri = _write(tmp_path, '"sep=;"\nID;ID2;Title\n'
                 'SLUS-20562;SLUS_205.62;"Max Payne"\n'
                 'SLUS-20267;SLUS_202.67;".hack//Infection"\n')
    result = csv_delete_cols_to_dict(uri, ["ID"])
    assert result["SLUS_205.62"] == "Max Payne"
    assert result["SLUS_202.67"] == ".hack//Infection"


def test_titles_containing_delimiter(tmp_path: Path):
    uri = _write(tmp_path, '"sep=;"\nID;ID2;Title\n'
                 'SCES-50595;SCES_505.95;"Monsters, Inc."\n')
    result = csv_delete_cols_to_dict(uri, ["ID"])
    assert result["SCES_505.95"] == "Monsters, Inc."


def test_undetectable_delimiter_keeps_legacy_behavior(tmp_path: Path):
    uri = _write(tmp_path, "ID\nSLUS_205.62\n")
    with pytest.raises(ValueError):
        csv_delete_cols_to_dict(uri, ["ID"])
