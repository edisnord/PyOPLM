#!/usr/bin/env python3

import csv
import io
from pathlib import Path

import pytest
from PIL import Image

from pyoplm.storage import Storage, Indexing
from pyoplm.game import ISOGame, POPSGame


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), color).save(buf, "PNG")
    return buf.getvalue()


def _write_csv(path: Path, rows: list[dict[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


RED = (255, 0, 0)
BLUE = (0, 0, 255)
GREEN = (0, 255, 0)
YELLOW = (255, 255, 0)
BLACK = (0, 0, 0)


@pytest.fixture()
def storage_with_art(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    opl_dir = tmp_path / "opl"
    opl_dir.mkdir()
    (opl_dir / "ART").mkdir()

    region = "SLUS_205.62"

    ps2_dir = storage_dir / "PS2" / region
    ps2_dir.mkdir(parents=True)
    (ps2_dir / f"{region}_COV.png").write_bytes(_png_bytes(RED))
    (ps2_dir / f"{region}_COV2.png").write_bytes(_png_bytes(BLUE))
    (ps2_dir / f"{region}_SCR_00.png").write_bytes(_png_bytes(GREEN))
    (ps2_dir / f"{region}_SCR_01.png").write_bytes(_png_bytes(YELLOW))
    (ps2_dir / f"{region}_BG_00.png").write_bytes(_png_bytes(BLACK))
    (ps2_dir / f"{region}_BG_01.png").write_bytes(_png_bytes(RED))

    (storage_dir / "PS1" / region).mkdir(parents=True)

    storage = Storage(str(storage_dir), opl_dir)
    return storage, opl_dir, region


@pytest.fixture()
def storage_with_csv(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    opl_dir = tmp_path / "opl"
    opl_dir.mkdir()
    (opl_dir / "ART").mkdir()

    _write_csv(storage_dir / "PS1_LIST.csv", [
        {"Serial": "SCUS_942.10", "Title": "Crash Bandicoot"},
        {"Serial": "SLUS_202.67", "Title": "Some PS1 Game"},
    ])
    _write_csv(storage_dir / "PS2_LIST.csv", [
        {"Serial": "SLUS_205.62", "Title": "Max Payne"},
        {"Serial": "SLUS_200.01", "Title": "Another PS2 Game"},
    ])

    storage = Storage(str(storage_dir), opl_dir)
    return storage, opl_dir


class TestBug7WrongCoverArt:
    """GitHub issue #7: `storage artwork` used COV2.png as both COV.png
    and COV2.png because the COV glob also matched COV2 files."""

    def test_cov_and_cov2_get_distinct_files(
        self, storage_with_art: tuple[Storage, Path, str]
    ):
        storage, opl_dir, region = storage_with_art
        storage.get_artwork_for_game(region, overwrite=True)

        cov = opl_dir / "ART" / f"{region}_COV.png"
        cov2 = opl_dir / "ART" / f"{region}_COV2.png"
        assert cov.exists() and cov2.exists()

        assert Image.open(cov).getpixel((0, 0)) == RED
        assert Image.open(cov2).getpixel((0, 0)) == BLUE

    def test_scr_and_bg_use_opl_naming(
        self, storage_with_art: tuple[Storage, Path, str]
    ):
        storage, opl_dir, region = storage_with_art
        storage.get_artwork_for_game(region, overwrite=True)

        art = opl_dir / "ART"
        scr = art / f"{region}_SCR.png"
        scr2 = art / f"{region}_SCR2.png"
        bg = art / f"{region}_BG.png"
        assert scr.exists() and scr2.exists() and bg.exists()

        assert Image.open(scr).getpixel((0, 0)) == GREEN
        assert Image.open(scr2).getpixel((0, 0)) == YELLOW
        assert Image.open(bg).getpixel((0, 0)) == BLACK

        assert not list(art.glob(f"{region}_SCR1.*"))
        assert not list(art.glob(f"{region}_BG[0-9].*"))


class TestBug6RenameCrash:
    """GitHub issue #6: `pyoplm storage rename` crashed with
    `TypeError: object of type 'NoneType' has no len()` when a game
    could not be found in the storage CSVs."""

    def test_csv_location_must_interpolate_console(
        self, storage_with_csv: tuple[Storage, Path]
    ):
        storage, opl_dir = storage_with_csv

        ps1_url = storage.get_game_title_csv_location("PS1")
        ps2_url = storage.get_game_title_csv_location("PS2")

        assert "PS1_LIST.csv" in ps1_url
        assert "PS2_LIST.csv" in ps2_url
        assert "{console}" not in ps1_url and "%7Bconsole%7D" not in ps1_url

    def test_get_game_title_searches_both_csvs(
        self, storage_with_csv: tuple[Storage, Path]
    ):
        storage, opl_dir = storage_with_csv

        assert storage.get_game_title("SLUS_205.62") == "Max Payne"
        assert storage.get_game_title("SLUS_202.67") == "Some PS1 Game"
        assert storage.get_game_title("SCUS_942.10") == "Crash Bandicoot"

    def test_rename_must_not_crash_on_none(self, tmp_path: Path):
        game_dir = tmp_path / "games"
        game_dir.mkdir()
        iso_path = game_dir / "SLUS_205.62.SomeGame.iso"
        iso_path.write_bytes(b"\x00" * 4096)

        game = ISOGame(iso_path)
        game.rename(None)
        assert game.filepath.name == "SLUS_205.62.SomeGame.iso"

    def test_pops_rename_must_not_crash_on_none(self, tmp_path: Path):
        from unittest.mock import patch

        game_dir = tmp_path / "pops"
        game_dir.mkdir()
        vcd_path = game_dir / "SLUS_205.62.SomeGame.vcd"
        vcd_path.write_bytes(b"\x00" * (1086272 + 1024))

        with patch("pyoplm.game.get_iso_id", return_value="SLUS-205.62"):
            game = POPSGame(vcd_path)

        game.rename(None)
        assert game.filepath.name == "SLUS_205.62.SomeGame.vcd"

    def test_bulk_rename_must_not_crash(
        self, storage_with_csv: tuple[Storage, Path], tmp_path: Path
    ):
        storage, opl_dir = storage_with_csv

        game_dir = tmp_path / "games"
        game_dir.mkdir()

        games = []
        for serial, name in [("SLUS_205.62", "MaxPayne"), ("SLUS_202.67", "AnotherGame")]:
            iso_path = game_dir / f"{serial}.{name}.iso"
            iso_path.write_bytes(b"\x00" * 4096)
            games.append(ISOGame(iso_path))

        crashes = []
        for game in games:
            title = storage.get_game_title(game.opl_id)
            try:
                game.rename(title)
            except TypeError as e:
                crashes.append((game.opl_id, e))

        assert len(crashes) == 0, (
            f"{len(crashes)}/{len(games)} games crashed with TypeError:\n"
            + "\n".join(f"  {oid}: {e}" for oid, e in crashes)
        )


ARCHIVE_URL = (
    "https://ia800701.us.archive.org/view_archive.php"
    "?archive=/11/items/OPLM_ART_2024_09/OPLM_ART_2024_09.zip"
)


class TestIndexingIntegration:
    """Full indexing workflow against the real OPLM art dump on
    archive.org."""

    @staticmethod
    def _records_for_region(region: str):
        from urllib.request import urlopen
        from bs4 import BeautifulSoup
        import re

        contents = urlopen(ARCHIVE_URL)
        games_page = BeautifulSoup(contents.read(), features="lxml")
        contents.close()

        table = games_page.find("table")
        rows = table.find_all("tr")

        records = []
        for row in rows:
            image_path = row.find("td")
            if not image_path:
                continue
            path: str = image_path.text.strip()
            if not path.endswith((".jpg", ".png")):
                continue
            split_path = path.split("/")
            if len(split_path) < 3:
                continue

            game_id = split_path[1]
            if game_id != region:
                continue

            console = split_path[0]
            filename = split_path[2]
            art_type_match = re.findall(Indexing.ART_FILENAME_PATTERN, filename)
            if not art_type_match:
                continue
            art_type = art_type_match[0][0]

            if "_" in art_type:
                split_art_type = art_type.split("_")
                nr = split_art_type[1]
                base_type = split_art_type[0]
                if int(nr) <= 1 and base_type == "SCR":
                    art_type = f"{base_type}{'' if int(nr) == 0 else '2'}"
                elif base_type == "BG" and int(nr) == 0:
                    art_type = "BG"
                else:
                    continue

            file_extension: str = filename.split(".")[2]
            dest_filename = f"{game_id}_{art_type}.{file_extension}"
            records.append((game_id, console, art_type, file_extension, filename, dest_filename))

        return records

    @pytest.mark.integration
    def test_index_artwork_parses_real_dump(self, tmp_path: Path):
        records = self._records_for_region("SLUS_205.62")

        assert len(records) == 8, (
            f"Expected 8 artwork records, got {len(records)}: "
            f"{[r[2] for r in records]}"
        )

        art_types = {r[2] for r in records}
        expected_types = {"BG", "COV", "COV2", "ICO", "LAB", "LGO", "SCR", "SCR2"}
        assert art_types == expected_types

        cov_records = [r for r in records if r[2] == "COV"]
        cov2_records = [r for r in records if r[2] == "COV2"]
        assert len(cov_records) == 1
        assert len(cov2_records) == 1
        assert cov_records[0][4] != cov2_records[0][4]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not integration"])
