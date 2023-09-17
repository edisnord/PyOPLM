from configparser import ConfigParser
from pathlib import Path
import sys
from typing import List
from pyoplm.common import path_to_ul_cfg
from pyoplm.opl.games_manager import GamesManager

from pyoplm.storage import Storage
from pyoplm.ul import ULConfig


class PyOPLManager:
    args = None
    opl_dir: Path
    storage: Storage
    games_manager: GamesManager

    def __init__(self, opl_dir: Path):
        self.opl_dir = opl_dir
        self.games_manager = GamesManager(opl_dir)
        self.initialize_storage()

    def initialize_storage(self):
        config = ConfigParser()
        config.read(str(self.opl_dir.joinpath("pyoplm.ini")))
        self.storage = Storage(config.get("STORAGE", "location", fallback=None), self.opl_dir, config.get(
            "STORAGE.INDEXING", "zip_contents_location", fallback=None))

    def delete(self, region_codes: List[str]):
        for code in region_codes:
            self.games_manager.delete(code)

    def rename(self, new_title: str | None = None, storage=False, opl_id: str | None = None):
        if storage:
            if not self.storage.is_enabled():
                print("Proper storage link not supplied in opl_dir/pyoplm.ini,\
                        not renaming.", file=sys.stderr)
                sys.exit(0)

        if not opl_id and storage:
            print("Bulk renaming games from storage...")
            for game in self.games_manager.games_dict.values():
                game.rename(self.storage.get_game_title(game.opl_id))

        elif opl_id and storage:
            new_title = self.storage.get_game_title(opl_id)

            try:
                self.games_manager.games_dict[opl_id].rename(new_title)
            except:
                print(
                    f"Game with region code {opl_id} is not installed.", file=sys.stderr)
                sys.exit(1)

        print("Fixing all games just in case...")
        self.fix()

    # Add game(s) to args.opl_dir
    #  - split game if > 4GB / forced
    #  - otherwise just copy with OPL-like filename
    #  - If storage features are enabled, try to get title from storage and download artwork

    def add(self, src_files: List[Path], psx=False, iso=False, ul=False, force=False, storage=False):
        for game_path in src_files:
            game = self.games_manager.add(game_path, psx, iso, ul, force)

            if self.storage.is_enabled() and storage:
                self.storage.get_artwork_for_game(game.opl_id, True)
                self.rename(storage=True, opl_id=game.opl_id)
            
            print("Fixing all game titles...")
            self.fix()

    # Fix ISO names for faster OPL access
    # Delete UL games with missing parts
    # Recover UL games which are not in ul.cfg
    # Find corrupted entries in ul.cfg first and delete them
    def fix(self):
        if (ulcfg_file := path_to_ul_cfg(self.opl_dir)).exists():
            ULConfig.find_and_delete_corrupted_entries(
                ulcfg_file)

            ulcfg = ULConfig(ulcfg_file)
            ulcfg.find_and_recover_games()

        print("Fixing ISO and POPS game file names for OPL read speed and deleting broken UL games")
        for game in self.games_manager.games_dict.values():
            if not game.id:
                print(f"Error while parsing file: {game.filepath}")
                continue
            game.fix_if_not_ok()

    # Download all artwork for all games if storage is enabled

    def artwork(self, region_codes: List[str], overwrite):
        if self.storage.is_enabled():
            for region_code in region_codes or self.games_manager.games_dict.keys():
                    try:
                        game = self.games_manager.games_dict[region_code]
                    except KeyError:
                        print(f"Game with region code {region_code} does not exist, skipping...")
                        continue
                    print(
                        f"Downloading artwork for [{game.opl_id}] {game.title}")
                    self.storage.get_artwork_for_game(
                        game.opl_id, bool(overwrite))
        else:
            print(
                "Storage link not supplied in opl_dir/pyoplm.ini, not downloading artwork.", file=sys.stderr)
            sys.exit(0)

    # List all Games on OPL-Drive
    def list(self):
        self.games_manager.list()

    # Create OPL Folders and empty ul.cfg
    def init(self):
        print("Inititalizing OPL-Drive...")
        for dir in ["APPS", "LNG", "ART", "CD", "CFG", "CHT", "DVD", "THM", "VMC", "POPS"]:
            if not (dir := self.opl_dir.joinpath(dir)).is_dir():
                dir.mkdir(0o777)
        self.opl_dir.joinpath("ul.cfg").touch(0o777)
        print("Done!")
