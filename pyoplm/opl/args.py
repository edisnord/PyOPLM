import argparse
import os
import sys

from pyoplm.opl.pyoplm_manager import PyOPLManager

from pathlib import Path
from functools import reduce
from enum import Enum


class SubparserKind(Enum):
    BINTOOLS = 0
    OPLM = 1


class OPLMCommand:
    LIST = 0
    ADD = 1
    ST_ARTWORK = 2
    ST_RENAME = 3
    RENAME = 4
    FIX = 5
    INIT = 6
    DELETE = 7


class BinToolsCommand:
    BCHUNK = 0
    CUE2POPS = 1
    BINMERGE = 2


def handle_oplm_commands(opl_dir: Path, cmd: OPLMCommand, **kwargs):
    opl = PyOPLManager(opl_dir)
    match cmd:
        case OPLMCommand.LIST:
            opl.list()
        case OPLMCommand.ADD:
            opl.add(**kwargs)
        case OPLMCommand.RENAME:
            opl.rename(**kwargs)
        case OPLMCommand.FIX:
            opl.fix()
        case OPLMCommand.INIT:
            opl.init()
        case OPLMCommand.DELETE:
            opl.delete(**kwargs)
        case OPLMCommand.ST_RENAME:
            opl.rename(**kwargs, storage=True)
        case OPLMCommand.ST_ARTWORK:
            opl.artwork(**kwargs)


def handle_bintools_commands(cmd: BinToolsCommand, **kwargs):
    match cmd:
        case BinToolsCommand.BCHUNK:
            pass
        case BinToolsCommand.CUE2POPS:
            pass
        case BinToolsCommand.BINMERGE:
            pass


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "add", help="Add ISO/CUE PS2 and PSX game to opl_dir")
    parser.add_argument(
        "--force", "-f", help="Force overwriting of existing files", action='store_true', default=False)
    parser.add_argument(
        "--psx", "-p", help="Install PSX games", action="store_true")
    parser.add_argument(
        "--ul", "-u", help="Force UL-Game converting", action="store_true")
    parser.add_argument(
        "--iso", "-i", help="Don't do UL conversion", action="store_true")
    parser.add_argument(
        "--storage", "-s", help="Get title and artwork from storage if it's enabled", action="store_true")
    parser.add_argument(
        "opl_dir", help="Path to your OPL directory",
        type=Path, nargs="?")
    parser.add_argument("src_files", nargs="+",
                        help="Game files to install",
                        type=Path)
    parser.set_defaults(kind=SubparserKind.OPLM, cmd=OPLMCommand.ADD)
    return subparsers


def list_parser(subparsers):
    parser = subparsers.add_parser("list", help="List Games on OPL-Drive")
    parser.add_argument(
        "opl_dir", help="Path to your OPL directory",
        type=Path, nargs="?")
    parser.set_defaults(kind=SubparserKind.OPLM, cmd=OPLMCommand.LIST)
    return subparsers


def fix_parser(subparsers):
    parser = subparsers.add_parser(
        "fix", help="rename/fix media filenames")
    parser.add_argument(
        "opl_dir", help="Path to your OPL directory",
        type=Path, nargs="?")
    parser.set_defaults(kind=SubparserKind.OPLM, cmd=OPLMCommand.FIX)
    return subparsers


def rename_parser(subparsers):
    parser = subparsers.add_parser(
        "rename", help="Change the title of the game corresponding to opl_id to new_title in the given opl_dir"
    )
    parser.add_argument(
        "opl_dir", help="Path to your OPL directory",
        type=Path, nargs="?")
    parser.add_argument("opl_id",
                        help="OPL-ID of Media/ISO File to delete")
    parser.add_argument("new_title",
                        help="New title for the game")
    parser.set_defaults(kind=SubparserKind.OPLM, cmd=OPLMCommand.RENAME)
    return subparsers


def init_parser(subparsers):
    parser = subparsers.add_parser(
        "init", help="Initialize OPL folder structure")
    parser.add_argument(
        "opl_dir", help="Path to your OPL USB or SMB Directory\nExample: /media/usb",
        type=Path, nargs="?")
    parser.set_defaults(kind=SubparserKind.OPLM, cmd=OPLMCommand.INIT)
    return subparsers


def delete_parser(subparsers):
    parser = subparsers.add_parser("delete", help="Delete game from Drive")
    parser.add_argument(
        "opl_dir", help="Path to your OPL directory",
        type=Path, nargs="?")
    parser.add_argument("region_codes", nargs="+",
                        help="Region codes/OPL IDs of games to delete")
    parser.set_defaults(kind=SubparserKind.OPLM, cmd=OPLMCommand.DELETE)
    return subparsers


def storage_parser(subparsers):
    def artwork_parser(subparsers):
        parser = subparsers.add_parser(
            "artwork", help="Download artwork for games installed in opl_dir,\
                  if no opl_id are supplied it downloads artwork for all games"
        )
        parser.add_argument(
            "opl_dir", help="Path to your OPL directory",
            type=Path, nargs="?")
        parser.add_argument(
            "--overwrite", "-o", help="Overwrite existing art files for games", action="store_true")
        parser.add_argument("region_codes", help="Region codes/OPL IDs of games to download artwork for", nargs="*"
                            )
        parser.set_defaults(kind=SubparserKind.OPLM,
                            cmd=OPLMCommand.ST_ARTWORK)
        return subparsers

    def rename_parser(subparsers):
        parser = subparsers.add_parser(
            "rename", help="Rename the game opl_id with a name taken from the storage,\
                  if no opl_id are supplied it renames all games"
        )
        parser.add_argument(
            "opl_dir", help="Path to your OPL directory",
            type=Path, nargs="?")
        parser.add_argument("opl_id",
                            help="OPL-ID of game to rename",
                            nargs="?")
        parser.set_defaults(kind=SubparserKind.OPLM, cmd=OPLMCommand.ST_RENAME)
        return subparsers

    storage_parser = subparsers.add_parser(
        "storage", help="Art and title storage-related functionality"
    )
    storage_subparsers = storage_parser.add_subparsers(
        help="Choose your path...")

    reduce(lambda x, y: y(x), [rename_parser,
           artwork_parser], storage_subparsers)
    
    return subparsers


def bintools_parser(subparsers):
    def bchunk_parser(subparsers):
        parser = subparsers.add_parser(
            "bin2iso", help="Bin to ISO conversion (uses bchunk, repo: https://github.com/extramaster/bchunk)")
        parser.add_argument(
            "-p", help=" PSX mode for MODE2/2352: write 2336 bytes from offset 24")
        parser.add_argument("src_bin", help="BIN file to convert")
        parser.add_argument("src_cue", help="CUE file related to image.bin")
        parser.add_argument(
            "basename", help="name (without extension) for your new bin/cue files")
        parser.set_defaults(kind=SubparserKind.BINTOOLS,
                            cmd=BinToolsCommand.BCHUNK)
        return subparsers

    def binmerge_parser(subparsers):
        parser = subparsers.add_parser(
            "binmerge", help="Merge multibin/cue into a single bin/cue (uses binmerge, repo: https://github.com/putnam/binmerge)")
        parser.add_argument(
            "--outdir", "-o", help="output directory. defaults to the same directory as source cue.directory will be created (recursively) if needed.")
        parser.add_argument(
            "--license", "-l", action="store_true", help="prints license info and exit")
        parser.add_argument("--split", "-s", action="store_true",
                            help="reverses operation, splitting merged files back to individual tracks")
        parser.add_argument(
            "cuefile", type=Path, help="CUE file pointing to bin files (bin files are expected in the same dir)")
        parser.add_argument(
            "basename", help="name (without extension) for your new bin/cue files")
        parser.set_defaults(kind=SubparserKind.BINTOOLS,
                            cmd=BinToolsCommand.BINMERGE)
        return subparsers

    def cue2pops_parser(subparsers):
        cue2pops_parser = subparsers.add_parser(
            "cue2pops", help="Turn single cue/bin files into VCD format readable by POPSTARTER (uses cue2pops-linux, repo: https://github.com/tallero/cue2pops-linux).")
        cue2pops_parser.add_argument(
            "input_file", type=Path, help="Input cue file")
        cue2pops_parser.add_argument(
            "--gap", choices=["++", "--"], help="Adds(gap++)/subtracts(gap--) 2 seconds to all track indexes MSF")
        cue2pops_parser.add_argument("--vmode", "-v", action="store_true",
                                     help="Attempts to patch the video mode to NTSC and to fix the screen position")
        cue2pops_parser.add_argument(
            "--trainer", "-t", action="store_true", help="Enable cheats")
        cue2pops_parser.add_argument(
            "output_file", help="output file", nargs="?")
        parser.set_defaults(kind=SubparserKind.BINTOOLS,
                            cmd=BinToolsCommand.CUE2POPS)
        return subparsers

    parser = subparsers.add_parser(
        "bintools", help="Tools for processing cue/bin games")
    subparsers = parser.add_subparsers(help="Choose your path...")

    reduce(lambda x, y: y(x)
           , [cue2pops_parser, bchunk_parser, binmerge_parser]
           , subparsers)

    return subparsers


def main_parser():
    parser = argparse.ArgumentParser()
    parser.prog = "pyoplm"

    subparsers = parser.add_subparsers(help="Choose your path...")
    parser_list = [list_parser, rename_parser, delete_parser,
                   fix_parser, init_parser, add_parser, storage_parser, bintools_parser]

    # Attach all parsers to the subparsers object
    subparsers = reduce(lambda x, y: y(x), parser_list, subparsers)

    arguments = parser.parse_args()

    if hasattr(arguments, "opl_dir") and arguments.opl_dir:
        opl_dir = arguments.opl_dir
    else:
        try:
            opl_dir = Path(os.environ["PYOPLM_OPL_DIR"])
        except KeyError:
            print("The argument opl_dir must be supplied either as a command line argument or as an environment variable named 'PYOPLM_OPL_DIR.'", file=sys.stderr)
            sys.exit(1)

    if not opl_dir.exists() or not opl_dir.is_dir():
        print("Error: opl_dir directory doesn't exist!")
        sys.exit(1)

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = vars(arguments)
    match args.pop("kind"):
        case SubparserKind.OPLM:
            args = vars(arguments)
            args.pop("opl_dir", None)
            handle_oplm_commands(opl_dir, **args)
        case SubparserKind.BINTOOLS:
            handle_bintools_commands(**args)

    sys.exit(0)
