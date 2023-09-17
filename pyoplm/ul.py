#!/usr/bin/env python3
# from game import ULGameImage
import math
import os
import re
from typing import Dict, List
from enum import Enum
from pathlib import Path
from pyoplm.common import usba_crc32, get_iso_id, ul_files_from_iso\
                        , check_ul_entry_for_corruption_and_crash  \
                        , check_ul_entry_for_corruption, ULCorruptionType


class ULMediaType(Enum):
    CD = b'\x12'
    DVD = b'\x14'

# single game in ul.cfg / on filesystem
# ul.cfg is binary
# 64byte per game


class ULConfigGame():
    filedir: Path = None
    global REGION_CODE_REGEX

    # Fields in ul.cfg per game (always 64byte)
    # 32byte - Title/Name of Game
    name: bytes

    # 14byte - region_code is "ul." + OPL_ID (aka ID/Serial of game)
    region_code: bytes

    # 1byte - According to USBUtil, "DESC"
    unknown: bytes
    # 1byte - Number of file chunks / parts
    parts: bytes

    # 1byte - media type?! so DVD/CD?...
    media: ULMediaType

    # 15byte - According to USBUtil, simply named "Information"
    remains: bytes

    # This CRC32-Hash is used for the ul-filenames
    # By hashing the "name"-bytes OPL finds the files,
    # that belong to a specific game
    crc32 = None

    # For Game object
    game = None

    def __init__(self, filedir, data, ulconfig):
        from pyoplm.game import ULGame
        self.parent_cfg = ulconfig
        self.filedir = filedir
        self.name = bytes(data[:32])
        self.crc32 = hex(usba_crc32(self.name)).capitalize()
        self.region_code = bytes(data[32:46])
        self.unknown = bytes([data[46]])
        self.parts = bytes([data[47]])
        self.media = ULMediaType(bytes([data[48]]))
        self.remains = bytes(data[49:64])

        self.opl_id = self.region_code[3:]
        self.game = ULGame(ulcfg=self)

    def refresh_crc32(self):
        self.crc32 = hex(usba_crc32(self.name)).capitalize()

    # Get binary config data, with padding to 64byte
    def get_binary_data(self):
        assert self.name
        assert self.region_code
        assert self.parts
        assert self.media

        data = self.name[:32] + \
            self.region_code + self.unknown + self.parts + self.media.value + self.remains

        return data.ljust(64, b'\x00')


# ul.cfg handling class
class ULConfig():
    ulgames: Dict[bytes, ULConfigGame] = {}
    filepath: Path = None

    # Generate ULconfig using ULGameConfig objects
    # Or Read ULConfig from filepath
    def __init__(self, filepath: Path):
        self.filepath = filepath
        if filepath.exists():
            self.read()
        else:
            filepath.touch(777)

    # Insert game to ULConfig from an ISO file, return ULConfigGame object representing it
    def add_game_from_iso(self, src_iso: Path, force: bool, title: bytes=None):
        if not title:
            title: bytes = re.sub(r'.[iI][sS][oO]', '',
                                src_iso.name).encode('ascii')
        game_size = src_iso.stat().st_size / 1024 ** 2

        if len(title) > 32:
            raise ValueError(
                f"Title length for game \'{title}\' is longer than 32 characters")

        title = title.ljust(32, b'\x00')
        region_code = (
            b'ul.' + get_iso_id(src_iso).encode('ascii')).ljust(14, b'\x00')
        unknown = b'\x00'
        parts = chr(math.ceil(game_size * 1024 **
                    2 / 1073741824)).encode('ascii')
        media = b'\x12' if src_iso.stat().st_size / 1024 ** 2 <= 700 else b'\x14'
        remaining = b'\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

        install_dir = self.filepath.parent
        data = title + region_code + unknown + parts + media + remaining

        ul_files_from_iso(src_iso, install_dir, force)
        config = ULConfigGame(install_dir, data)
        if config.game.check_status():
            self.add_ulgame(region_code, config)
            self.write()
            return config
        else:
            raise IOError(
                f"Files could not be created for game \'{title.decode('ascii', 'ignore')}\'")

    # Add / Update Game using ul_ID & ULGameConfi/g object

    def add_ulgame(self, ul_id: bytes, ulgame: ULConfigGame):
        self.ulgames.update({ul_id: ulgame})

    # Print debug data
    def print_data(self):
        print("Filepath: " + str(self.filepath))
        print("ULGames:")
        for game in self.ulgames:
            print(f" [{str(game)}] {str(self.ulgames[game].name)} ")

    # Read ul.cfg file
    def read(self):
        with open(self.filepath, 'rb') as data:
            game_cfg = data.read(64)
            while game_cfg:
                check_ul_entry_for_corruption_and_crash(game_cfg)

                game = ULConfigGame(
                    data=game_cfg, filedir=self.filepath.parent, ulconfig=self)
                self.ulgames.update({game.region_code: game})
                game_cfg = data.read(64)

    # Write back games to ul.cfg
    def write(self):
        with open(self.filepath, 'wb+') as cfg:
            for game in self.ulgames.values():
                cfg.write(game.get_binary_data())
        
        self.filepath.chmod(0o777)

    def find_and_recover_games(self):
        installed_region_codes = set(
            map(lambda part: ".".join(["ul"] + str(part.name).split('.')[2:4]).encode('ascii'), self.filepath.parent.glob("ul.*.*.*")
                )
        )
        ul_region_codes: List[bytes] = self.ulgames.keys()
        if installed_region_codes == ul_region_codes:
            print('Installed UL games correspond ul.cfg games, nothing to recover')
        else:
            to_recover = installed_region_codes.difference(ul_region_codes)
            print(
                "These games are installed but they are not part of UL.cfg, recovering...")
            for game in to_recover:
                part_nr = len(list(self.filepath.parent.glob(
                    "*"+game.decode("ascii", "ignore").split('.')[1]+"*")))

                first_part_size = next(
                    self.filepath.parent.glob(
                        "*"+".".join(game.decode("ascii", "ignore").split('.')[1:3])+".00")
                ).stat().st_size * (1024 ^ 2)

                self.recover_game(game, part_nr, first_part_size)
                print(f"Recovered \'{game.decode('ascii', 'ignore')}\'!")

    def recover_game(self, region_code: bytes, parts_nr: int, first_part_size: float, title=b"PLACEHOLDER"):
        region_code = region_code.ljust(14, b'\x00')
        title = title.ljust(32, b'\x00')
        unknown = b'\x00'
        parts = chr(parts_nr).encode("ascii")
        media = b'\x12' if first_part_size < 700 else b'\x14'
        remaining = b'\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

        data = title + region_code + unknown + parts + media + remaining

        crc32 = hex(usba_crc32(title))[2:].upper()
        to_rename = self.filepath.parent.glob(
            "*"+str(region_code).split(".")[1]+"*")
        for file in to_rename:
            file_parts = file.name.split(".")
            new_filename = ".".join(
                [file_parts[0], crc32, file_parts[2], file_parts[3], file_parts[4]])
            file.rename(self.filepath.parent.joinpath(new_filename))

        self.add_ulgame(region_code, ULConfigGame(self.filepath.parent, data))

        self.write()

    def rename_game(self, game_id: str, new_title: str):
        game_id = b"ul." + game_id.encode("ascii")
        game_to_rename = self.ulgames[game_id]
        game_to_rename.name = new_title.encode("ascii").ljust(32, b'\x00')

        crc32 = hex(usba_crc32(new_title.encode("ascii")))[2:].upper()
        for file in game_to_rename.game.get_filenames():
            file_parts = file.name.split(".")
            new_filename = ".".join([file_parts[0], crc32, file_parts[2], file_parts[3], file_parts[4]])
            file.rename(self.filepath.parent.joinpath(new_filename))
        
        game_to_rename.refresh_crc32()

        self.write()

    def find_and_delete_corrupted_entries(filepath: Path):
        final_file: bytes = b""

        with filepath.open("rb") as data:
            game_cfg = data.read(64)
            while game_cfg:
                if len(game_cfg) < 64:
                    game_cfg = data.read(64)
                    continue
                match check_ul_entry_for_corruption(game_cfg):
                    case ULCorruptionType.REGION_CODE | ULCorruptionType.MEDIA_TYPE:
                        print(f"The game with the title \'{game_cfg[0:32].decode('ascii', 'ignore')}\' is corrupted, recovering UL entry and renaming to 'PLACEHOLDER'")
                        pass
                    case ULCorruptionType.NO_CORRUPTION:
                        final_file += game_cfg
                game_cfg = data.read(64)
        
        filepath.write_bytes(final_file)

