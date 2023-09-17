from dataclasses import dataclass
from pathlib import Path
import re
from shutil import copyfile
import sys
from typing import Dict, Iterator

from pyoplm.bintools import install_ps2_cue, psx_add

from ..ul import ULConfig
from ..common import get_iso_id, path_to_ul_cfg
from ..game import Game, ISOGame, ULGame, POPSGame
from itertools import chain


class GamesManager():
    games_dict: Dict[str, Game]
    iso_games: Iterator[ISOGame]
    ul_games: Iterator[ULGame]
    pops_games: Iterator[POPSGame]
    opl_dir: Path

    def __init__(self, opl_dir: Path):
        self.opl_dir = opl_dir
        self.games_dict = {}
        self.__initialize_games()        

    def __get_pops_game_files(self) -> Iterator[Path]:
        path = self.opl_dir.joinpath("POPS")
        return path.glob("*.[vV][cC][dD]")

    def __get_iso_game_files(self) -> Iterator[Path]:
        extension_pattern = "*.[iI][sS][oO]"
        path1 = self.opl_dir.joinpath("DVD")
        path2 = self.opl_dir.joinpath("CD")
        return chain(path1.glob(extension_pattern), path2.glob(extension_pattern))

    def __initialize_games(self):
        game_to_files_func = [
            (POPSGame, self.__get_pops_game_files, "pops_games"),
            (ISOGame, self.__get_iso_game_files, "iso_games"),
        ]
        for (game_type, get_files, dest_list) in game_to_files_func:
                files = get_files()
                games = {
                    game.opl_id: game 
                        for game in (game_type(file) for file in files)
                    }
                self.games_dict.update(games)

                setattr(self, dest_list, iter(games.values()))
        self.__initialize_ul_games()

    def __initialize_ul_games(self) -> None:
        if not (ulcfg_file := path_to_ul_cfg(self.opl_dir)).exists():
            self.ul_games = []
            return

        games = {
            game_cfg.game.opl_id :game_cfg.game
                for game_cfg in ULConfig(ulcfg_file).ulgames.values()
        }
        self.games_dict.update(games)
        self.ul_games = iter(games.values())


    def list(self) -> None:
        games_and_kinds: Dict[str, Iterator[Game]] = {
            "ISO": self.iso_games,
            "UL": self.ul_games,
            "POPS": self.pops_games
        }

        found_one = False
        for (kind, game_list) in games_and_kinds.items():
            while game := next(game_list, None):
                if not found_one:
                    print(f"|-> {kind} Games:")
                    found_one = True
                print(f"    {game}")
            found_one = False

    def delete(self, game_id) -> None:
        try:
            print(f"Deleting game {game_id}...")
            self.games_dict[game_id].delete_game(self.opl_dir)
            print("Deleted!")
        except KeyError:
            print(f"Game with the given region code {game_id} not found", file=sys.stderr)
            sys.exit(1)

    # Installs game to OPL directory, returns the Game subclass object representing the added game
    def add(self, game_path: Path, psx = False, iso = False, ul = False, force = False) -> Game:
            if psx:
                print("Installing POPS game...")
                return psx_add(game_path, self.opl_dir)
            
            if re.match(r"^.[cC][uU][eE]$", game_path.suffix):
                print(
                    f"Attempting to convert game {game_path} to ISO and install...")
                return install_ps2_cue(game_path, self.opl_dir)

            iso_id = get_iso_id(game_path)
            # Game size in MB
            game_size = game_path.stat().st_size / (1024 ** 2)

            if (game_size > 4000 and not iso) or ul:
                print("Converting to UL format because game is larger than 4GB")
                ul_cfg = ULConfig(path_to_ul_cfg(self.opl_dir))
                return ul_cfg.add_game_from_iso(game_path, force)
            else:
                if (iso_id in self.games_dict) and not force:
                    print(
                        f"Game with ID \'{iso_id}\' is already installed, skipping...")
                    print("Use the -f flag to force the installation of this game")
                else:
                    title = game_path.stem

                    if len(title) > 32:
                        print(
                            f"Game title \'{title}\' is longer than 32 characters, skipping...")
                        return
                    new_game_path: Path = self.opl_dir.joinpath(
                        "DVD" if game_size > 700 else "CD",
                        f"{iso_id}.{title}.iso")

                    print(
                        f"Copying game to \'{new_game_path}\', please wait...")
                    copyfile(game_path, new_game_path)
                    new_game_path.chmod(0o777)
                    print("Done!")

                    return ISOGame(new_game_path)
