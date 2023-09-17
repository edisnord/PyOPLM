#!/usr/bin/env python3
###
# Game Class
#
from functools import reduce
from pathlib import Path
import sys
from pyoplm.common import REGION_CODE_REGEX_BYTES, get_iso_id, REGION_CODE_REGEX_STR
from abc import ABC, abstractmethod

import re
from typing import List
from enum import Enum
from os import path


class GameFormat(Enum):
    UL = "UL (USBExtreme)"
    ISO = "ISO"
    POPS = "VCD"


class Game(ABC):
    # constant values for gametypes
    game_format: GameFormat
    global REGION_CODE_REGEX_BYTES

    GameStatus = Enum('GameStatuses', ['OK'])

    filedir: Path
    filename: str
    filetype: str
    filepath: Path
    id: str
    opl_id: str
    title: str
    size: float
    proper_filename_regex = re.compile(
        r"^[HhMmPpGgNnCcSsJjTtBbDdAaKk][a-zA-Z]{3}.?\d{3}\.?\d{2}\..{1,32}\.([iI][sS][oO]|[vV][cC][dD])$")

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.filename = self.filepath.name
        self.filedir = self.filepath.parent

    def __repr__(self):
        return f"""\n----------------------------------------
LANG=en_US.UTF-8
Region code:       {self.opl_id}
Size (MB):    {self.size} 
New Title:    {self.title} 
Filename:     {self.filename}

Filetype:     {self.filetype}
Filedir:      {self.filedir}
Type:         {self.game_format.value}
ID:           {self.id} 
Filepath:     {self.filepath}
"""

    def __str__(self):
        return f"[{self.opl_id}] {self.title}"

    def print_data(self):
        print(repr(self))

    # Generate Serial/ID in OPL Format
    def gen_opl_id(self):
        oplid = self.id.replace('-', '_')
        oplid = oplid.replace('.', '')
        try:
            oplid = oplid[:8] + "." + oplid[8:]
        except:
            oplid = None
        self.opl_id = oplid

    @abstractmethod
    def check_status(self) -> GameStatus:
        return self.GameStatus.OK
    
    @abstractmethod
    def rename(self, new_title: str) -> None:
        pass

    def fix_if_not_ok(self):
        if not (status := self.check_status()):
            self.fix_issues(status)

    @abstractmethod
    def fix_issues(self, status: GameStatus):
        pass

    @abstractmethod
    def delete_game(self, opl_dir: Path):
        for directory in ["ART", "CFG", "CHT", "VMC"]:
            for file in opl_dir.joinpath(directory).glob(f"{self.id}*"):
                file.unlink()

####
# UL-Format game, child-class of "Game"


class ULGame(Game):
    # ULConfigGame object
    from pyoplm.ul import ULConfigGame, ULConfig
    ulcfg: ULConfigGame
    filenames: List[Path]
    size: float
    type: GameFormat = GameFormat.UL
    GameStatus = Enum("GameStatus", ["FILE_NOT_EXIST", "OK"])
    crc32: str

    global REGION_CODE_REGEX_STR

    # Chunk size matched USBUtil
    CHUNK_SIZE = 1073741824

    # Generate ULGameImage from ulcfg
    def __init__(self, ulcfg: ULConfigGame):
        self.ulcfg = ulcfg
        self.opl_id = self.ulcfg.region_code.replace(
            b'ul.', b'').decode('utf-8')
        self.id = self.opl_id
        self.title = self.ulcfg.name.decode('utf-8')
        self.crc32 = self.ulcfg.crc32
        self.filenames = self.get_filenames()
        self.size = self.get_size()

    def rename(self, new_title: str) -> None:
        self.ulcfg.parent_cfg.rename_game(self.opl_id, new_title)
        print(
            f"The game \'{self.opl_id}\' was renamed to \'{new_title}\'")

    def get_filenames(self):
        if hasattr(self, "filenames"):
            return self.filenames
        else:
            crc32 = self.crc32[2:].upper()
            def part_format(part): return hex(part)[2:4].zfill(2).upper()

            self.filenames = [self.ulcfg.filedir.joinpath(
                f"ul.{crc32}.{self.id}.{part_format(part)}")
                for part in range(0, int(self.ulcfg.parts[0]))]
            return self.filenames

    def get_size(self):
        if hasattr(self, "size"):
            return self.size
        else:
            self.size = reduce(lambda x, y: x + y.stat().st_size / (1024 ^ 2),
                               self.get_filenames(), 0)
            return self.size

    def check_status(self) -> GameStatus:
        for file in self.get_filenames():
            if not file.exists():
                return self.GameStatus.FILE_NOT_EXIST
        return self.GameStatus.OK

    def fix_issues(self, status: GameStatus):
        match status:
            case self.GameStatus.FILE_NOT_EXIST:
                print(
                    f"UL Game {self.opl_id} is missing a part. Deleting broken game...")
                self.delete_game(self.ulcfg.filedir)
            case _:
                pass

    def delete_game(self, opl_dir: Path) -> None:
        print("Deleting game chunks...")
        for file in self.get_filenames():
            file.unlink()
        print("Done!")
        print("Adjusting ul.cfg...")
        self.ulcfg.parent_cfg.ulgames.pop(self.ulcfg.region_code)
        self.ulcfg.parent_cfg.write()
        if not len(self.ulcfg.parent_cfg.ulgames):
            print("No more games left, deleting ul.cfg...")
            self.ulcfg.parent_cfg.filepath.unlink()
        super().delete_game(opl_dir)

    def __repr__(self):
        return f"""\n----------------------------------------
LANG=en_US.UTF-8
Region Code:       {self.opl_id}
Size (MB):    {self.size} 
Title:    {self.title} 

Game type:     UL
Game dir:      {self.filedir}
CRC32:        {self.crc32}
ID:           {self.id} 
Filepath:     {self.filepath}
"""

####
# Class for ISO-Games (or alike), child-class of "Game"


class ISOGame(Game):
    GameStatus = Enum("GameStatus", ["WRONG_FILENAME", "OK"])
    # Create Game based on filepath

    def __init__(self, filepath):
        self.game_format = GameFormat.ISO
        self.filetype = "ISO"
        super().__init__(filepath)
        self.get_filedata()

    def check_status(self) -> GameStatus:
        if not self.proper_filename_regex.findall(self.filename):
            return self.GameStatus.WRONG_FILENAME
        else:
            return self.GameStatus.OK

    def rename(self, new_title: str) -> None:
        if len(new_title) > 32:
            print(f"Title {new_title} is too long!",
                file=sys.stderr)
            print(
                "Titles longer than 32 characters are not permitted!", file=sys.stderr)
            print(f"Skipping {self.opl_id}...", file=sys.stderr)
            return

        new_filename = f"{self.opl_id}.{new_title}.{self.filetype}"
        new_filepath = self.filepath.parent.joinpath(
            new_filename
        )
        self.filepath = self.filepath.rename(new_filepath)

        new_filepath.chmod(0o777)

        self.title = new_title
        print(
            f"The game \'{self.opl_id}\' was renamed to \'{self.title}\'")

    def fix_issues(self, status: GameStatus) -> None:
        match status:
            case self.GameStatus.WRONG_FILENAME:
                print(f"Fixing \'{self.filename}\'...")
                self.filepath = self.filepath.rename(
                    self.filedir.joinpath(
                        f"{self.opl_id}.{self.title}.{self.filetype}")
                )

                self.filepath.chmod(0o777)
                self.filename = self.filepath.name
                self.gen_opl_id()
                self.print_data()
            case self.GameStatus.OK:
                pass

    # Get data from filename
    def get_filedata(self) -> None:
        # try to get id out of filename
        if (res := REGION_CODE_REGEX_STR.findall(self.filename)):
            self.id = res[0]
        else:
            self.id = get_iso_id(self.filepath)

        if not self.id:
            return

        self.gen_opl_id()
        self.size = self.filepath.stat().st_size / (1024 ^ 2)

        self.title = REGION_CODE_REGEX_STR.sub('', self.filename)
        self.title = re.sub(r".[iI][sS][oO]", "", self.title)
        self.title = self.title.strip('._-\ ')
        self.filename = re.sub(r".[iI][sS][oO]", "", self.filename)

    def delete_game(self, opl_dir: Path):
        print("Deleting ISO file...")
        self.filepath.unlink()
        print("Done!")
        super().delete_game(opl_dir)


class POPSGame(Game):
    REGION_CODE_OFFSET = 1086272
    GameStatus = Enum("GameStatus", ["WRONG_FILENAME", "OK"])

    def __init__(self, filepath: path):
        super().__init__(filepath)
        self.size = self.filepath.stat().st_size / (1024 ^ 2)
        self.filetype = "VCD"
        self.game_format = GameFormat.POPS
        self.id = get_iso_id(filepath)
        self.gen_opl_id()
        self.get_title_from_filename()

    def delete_game(self, opl_dir: Path):
        from shutil import rmtree
        print("Deleting VCD file...")
        self.filepath.unlink()
        print("Done!")
        if self.filedir.joinpath(self.filename[:-4]).exists():
            print("Deleting memory cards and cheats...")
            rmtree(self.filedir.joinpath(self.filename[:-4]))
            print("Done!")
        super().delete_game(opl_dir)

    def get_title_from_filename(self):
        self.title = REGION_CODE_REGEX_STR.sub('', self.filename)
        self.title = re.sub(r".[vV][cC][dD]", "", self.title)
        self.title = self.title.strip('._-\ ')

    def get_id_from_file(self):
        with self.filepath.open('rb') as vcd:
            vcd.seek(self.REGION_CODE_OFFSET)
            region_code = vcd.read(10)
            self.id = (region_code[:8] + b'.' +
                       region_code[8:]).decode('ascii')

    def check_status(self) -> GameStatus:
        if not self.proper_filename_regex.findall(self.filename):
            return self.GameStatus.WRONG_FILENAME
        else:
            return self.GameStatus.OK

    def fix_issues(self, status: GameStatus) -> None:
        match status:
            case self.GameStatus.WRONG_FILENAME:
                print(f"Fixing \'{self.filename}\'...")
                self.filepath = self.filepath.rename(
                    self.filedir.joinpath(
                        f"{self.opl_id}.{self.title}.{self.filetype}")
                )

                pops_data_folder = self.filedir.joinpath(
                    self.filepath.stem)
                if pops_data_folder.exists():
                    self.filedir.joinpath(self.filepath.stem).rename(
                        self.filedir.joinpath(
                            f"{self.opl_id}.{self.title}")
                    )

                self.filepath.chmod(0o777)
                self.filename = self.filepath.name
                self.gen_opl_id()
                self.print_data()
            case self.GameStatus.OK:
                pass

    def rename(self, new_title: str) -> None:
        if len(new_title) > 32:
            print(f"Title {new_title} is too long!",
                file=sys.stderr)
            print(
                "Titles longer than 32 characters are not permitted!", file=sys.stderr)
            print(f"Skipping {self.opl_id}...", file=sys.stderr)
            return

        new_filename = f"{self.opl_id}.{new_title}.{self.filetype}"
        new_filepath = self.filepath.parent.joinpath(
            new_filename
        )
        self.filepath = self.filepath.rename(new_filepath)

        new_filepath.chmod(0o777)

        self.title = new_title
        print(
            f"The game \'{self.opl_id}\' was renamed to \'{self.title}\'")