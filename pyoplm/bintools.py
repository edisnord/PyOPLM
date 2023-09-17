import os
import platform
import re
from shutil import move
import subprocess
from collections import namedtuple
from pathlib import Path
import sys

from pyoplm.game import ISOGame, POPSGame

BinMergeArgs = namedtuple("BinMergeArgs", ["outdir", "license", "split", "cuefile", "basename"])
Cue2PopsArgs = namedtuple("Cue2PopsArgs", ["input_file", "gap", "vmode", "trainer", "output_file"])
BChunkArgs = namedtuple("BChunkArgs", ["p", "src_bin", "src_cue", "basename"])

cue2pops_location = Path(
    __file__).parent.joinpath("lib", "linux64", "cue2pops", "cue2pops")
bchunk_location = Path(
    __file__).parent.joinpath("lib", "linux64", "bchunk", "bchunk")
binmerge_location = Path(
    __file__).parent.joinpath("lib", "linux64", "binmerge", "binmerge")

def cue2pops(args: Cue2PopsArgs):
    if platform.machine() != "x86_64":
        print(f"Machines of type {platform.machine()} cannot run the binary dependencies of this app's bintools (yet)")
        sys.exit(1)
    args_list = [cue2pops_location.absolute().as_posix(), args.input_file or '',
                 f"gap{args.gap}" if args.gap else '', 'vmode' if args.vmode else '', 'trainer' if args.trainer else '', args.output_file or '']
    args_list = list(filter(bool, args_list))
    complete = subprocess.run(args_list)
    return complete.returncode

def bchunk(args: BChunkArgs):
    if platform.machine() != "x86_64":
        print(f"Machines of type {platform.machine()} cannot run the binary dependencies of this app's bintools (yet)")
        sys.exit(1)
    args_list = [bchunk_location.absolute().as_posix(), '-p' if args.p else '', args.src_bin, args.src_cue, args.basename]
    args_list = list(filter(bool, args_list))
    complete = subprocess.run(args_list)
    return complete.returncode

def binmerge(args: BinMergeArgs):
    if platform.machine() != "x86_64":
        print(f"Machines of type {platform.machine()} cannot run the binary dependencies of this app's bintools (yet)")
        sys.exit(1)
    args_list = [binmerge_location.absolute().as_posix(), ('-o' + args.outdir) or '', '-l' if args.license else '', '-s' if args.split else '',
                args.cuefile.absolute().as_posix(), args.basename or '']
    args_list = list(filter(bool, args_list))
    complete = subprocess.run(args_list)
    return complete.returncode

def install_ps2_cue(cuefile_path: Path, opl_dir: Path) -> str:
    if not cuefile_path.exists():
        print(f"File {cuefile_path.as_posix()} does not exist, skipping...")
        return
    if len(cuefile_path.stem) > 32:
        print(
            f"The cue file's name will be kept as a game title, please make the filename {cuefile_path.stem} less than 32 characters long", file=sys.stderr)
        return
    with cuefile_path.open("r") as cue:
        if len(binfile := re.findall(r"\"(.*.bin)\"", cue.read())) > 1:
            print(
                f"The game {cuefile_path.as_posix()} has more than one track, which is not supported for single-iso conversion by bchunk", file=sys.stderr)
            return
        elif not binfile:
            print(
                f"Cue file is invalid {cuefile_path.as_posix()} or there are no bin files, skipping...", file=sys.stderr)
            return

    os.chdir(cuefile_path.parent)
    bchunk_binfile = cuefile_path.parent.joinpath(binfile[0])
    bchunk_exit_code = bchunk(BChunkArgs(
        p=None,
        src_bin=bchunk_binfile,
        src_cue=cuefile_path,
        basename=cuefile_path.stem
    ))
    if bchunk_exit_code != 0:
        print(f"Failed to install game {cuefile_path.stem}")
        print(
            f"Cue2pops finished with exit code: {bchunk_exit_code} for game {cuefile_path}, skipping...", file=sys.stderr)

    finished_conv_path = cuefile_path.with_name(
        cuefile_path.stem + "01.iso")
    final_path = opl_dir.joinpath("CD", cuefile_path.stem + ".iso")

    move(
        finished_conv_path,
        final_path
    )

    final_path.chmod(0o777)

    print(f"Successfully installed game {cuefile_path.stem}")

    return ISOGame(final_path)

def psx_add(cuefile_path: Path, opl_dir: Path) -> str:
    TMP_FILES_NAME = "pyoplm_tmp"
    print("Installing PSX game " + cuefile_path.as_posix())
    if len(cuefile_path.stem) > 32:
        print(
            f"The cue file's name will be kept as a game title, please make the filename {cuefile_path.stem} less than 32 characters long", file=sys.stderr)
        return
    if not (cuefile_path.exists()):
        print(
            f"POPS game with path {cuefile_path.as_posix()} doesn't exist, skipping...", file=sys.stderr)
        return

    with cuefile_path.open("r") as cue:
        filecount = cue.read().count("FILE")
        needs_binmerge = filecount > 1
        if filecount == 0:
            print(
                f"Cue file is invalid {cuefile_path.as_posix()} or there are no bin files, skipping...", file=sys.stderr)
            return

    if needs_binmerge:
        bm_args: BinMergeArgs = BinMergeArgs(cuefile=cuefile_path,
                                                basename=TMP_FILES_NAME,
                                                license=None,
                                                split=None,
                                                outdir="/tmp")
        binmerge_exit_code = binmerge(bm_args)
        if binmerge_exit_code != 0:
            print(
                f"Binmerge finished with exit code: {binmerge_exit_code} for game {cuefile_path}, skipping...", file=sys.stderr)
            return

    cue2pops_input = cuefile_path if not needs_binmerge else Path(
        f"/tmp/{TMP_FILES_NAME}.cue")
    cue2pops_output = opl_dir.joinpath(
        "POPS", cuefile_path.stem + ".VCD")
    cue2pops_args: Cue2PopsArgs = Cue2PopsArgs(
        input_file=cue2pops_input,
        gap=None,
        vmode=None,
        trainer=None,
        output_file=cue2pops_output
    )
    cue2pops_exit_code = cue2pops(cue2pops_args)
    if cue2pops_exit_code != 1:
        print(
            f"Cue2pops finished with exit code: {cue2pops_exit_code} for game {cuefile_path}, skipping...", file=sys.stderr)
        if needs_binmerge:
            cue2pops_input.unlink()
            cue2pops_input.with_suffix(".bin").unlink()
        return

    print(
        f"Successfully installed POPS {cuefile_path.stem} game to opl_dir, ")
    if needs_binmerge:
        cue2pops_input.unlink()
        cue2pops_input.with_suffix(".bin").unlink()

    cue2pops_output.chmod(0o777)

    return POPSGame(cue2pops_output)
