import sys
import getopt
import os
import struct

VERSION = "1.2.1"
USAGE = (
    "Usage: bchunk [-v] [-r] [-p (PSX)] [-w (wav)] [-s (swabaudio)]\n"
    "         <image.bin> <image.cue> <basename>\n"
    "Example: bchunk foo.bin foo.cue foo\n"
    "  -v  Verbose mode\n"
    "  -r  Raw mode for MODE2/2352: write all 2352 bytes from offset 0 (VCD/MPEG)\n"
    "  -p  PSX mode for MODE2/2352: write 2336 bytes from offset 24\n"
    "      (default MODE2/2352 mode writes 2048 bytes from offset 24)\n"
    "  -w  Output audio files in WAV format\n"
    "  -s  swabaudio: swap byte order in audio tracks\n"
)

VERSTR = (
    "binchunker for Windows, version " + VERSION + " by ...\n"
    "\tBased upon work by Heikki Hannikainen <hessu@hes.iki.fi>\n"
    "\tReleased under the GNU GPL, version 2 or later (at your option).\n\n"
)

CUELLEN = 1024
SECTLEN = 2352

WAV_RIFF_HLEN = 12
WAV_FORMAT_HLEN = 24
WAV_DATA_HLEN = 8
WAV_HEADER_LEN = WAV_RIFF_HLEN + WAV_FORMAT_HLEN + WAV_DATA_HLEN

class Args:
    def __init__(self, basefile=None, binfile=None, cuefile=None,
                 verbose=0, psxtruncate=0, raw=0, swabaudio=0, towav=0):        
        self.basefile = basefile
        self.binfile = binfile
        self.cuefile = cuefile
        self.verbose = verbose
        self.psxtruncate = psxtruncate
        self.raw = raw
        self.swabaudio = swabaudio
        self.towav = towav        

class Track:
    def __init__(self):
        self.num = 0
        self.mode = 0
        self.audio = 0
        self.modes = ""
        self.extension = None
        self.bstart = -1
        self.bsize = -1
        self.startsect = -1
        self.stopsect = -1
        self.start = -1
        self.stop = -1


def parse_args(argv) -> Args:
    args_obj = Args()
    
    try:
        opts, args = getopt.getopt(argv[1:], "swvp?hr")
    except getopt.GetoptError as e:
        sys.stderr.write(str(e) + "\n")
        sys.stderr.write(USAGE)
        sys.exit(1)

    for opt, _ in opts:
        if opt == "-r":
            args_obj.raw = 1
        elif opt == "-v":
            args_obj.verbose = 1
        elif opt == "-w":
            args_obj.towav = 1
        elif opt == "-p":
            args_obj.psxtruncate = 1
        elif opt == "-s":
            args_obj.swabaudio = 1
        elif opt in ("-?", "-h"):
            sys.stderr.write(USAGE)
            sys.exit(0)

    if len(args) != 3:
        sys.stderr.write(USAGE)
        sys.exit(1)

    args_obj.binfile, args_obj.cuefile, args_obj.basefile = args[0], args[1], args[2]
    return args_obj

def time2frames(s):
    """Convert MM:SS:FF time string to frame number."""
    parts = s.strip().split(":")
    if len(parts) != 3:
        return -1
    try:
        mins = int(parts[0])
        secs = int(parts[1])
        frames = int(parts[2])
    except ValueError:
        return -1
    return 75 * (mins * 60 + secs) + frames


def gettrackmode(track, modes, args: Args):
    """Parse the track mode string (same logic as C code)."""
    raw = args.raw
    psxtruncate = args.psxtruncate
    towav = args.towav

    modes_upper = modes.strip().upper()
    track.audio = 0

    if modes_upper == "MODE1/2352":
        track.bstart = 16
        track.bsize = 2048
        track.extension = "iso"

    elif modes_upper == "MODE2/2352":
        track.extension = "iso"
        if raw:
            # Raw MODE2/2352
            track.bstart = 0
            track.bsize = 2352
        elif psxtruncate:
            # PSX: truncate from 2352 to 2336 byte tracks
            track.bstart = 0
            track.bsize = 2336
        else:
            # Normal MODE2/2352
            track.bstart = 24
            track.bsize = 2048

    elif modes_upper == "MODE2/2336":
        # WAS 2352 in V1.361B still work?
        # what if MODE2/2336 single track bin, still 2352 sectors?
        track.bstart = 16
        track.bsize = 2336
        track.extension = "iso"

    elif modes_upper == "AUDIO":
        track.bstart = 0
        track.bsize = 2352
        track.audio = 1
        if towav:
            track.extension = "wav"
        else:
            track.extension = "cdr"
    else:
        sys.stdout.write("(?) ")
        track.bstart = 0
        track.bsize = 2352
        track.extension = "ugh"


def progressbar(f, length):
    n = int(length * f)
    if n < 0:
        n = 0
    if n > length:
        n = length
    return "*" * n + " " * (length - n)


def writetrack(bf, track, bname, args: Args):
    binfile = args.binfile
    swabaudio = args.swabaudio
    towav = args.towav
    verbose = args.verbose
    
    fname = f"{bname}{track.num:02d}.{track.extension}"

    print(f"{track.num:2d}: {fname} ", end="")

    try:
        f = open(fname, "wb")
    except OSError as e:
        sys.stderr.write(f" Could not fopen track file: {e}\n")
        sys.exit(4)

    try:
        bf.seek(track.start, os.SEEK_SET)
    except OSError as e:
        sys.stderr.write(f" Could not fseek to track location: {e}\n")
        sys.exit(4)

    reallen = (track.stopsect - track.startsect + 1) * track.bsize
    if verbose:
        print()
        print(
            f" mmc sectors {track.startsect}->{track.stopsect} "
            f"({track.stopsect - track.startsect + 1})"
        )
        print(f" mmc bytes {track.start}->{track.stop} ({track.stop - track.start + 1})")
        print(f" sector data at {track.bstart}, {track.bsize} bytes per sector")
        print(f" real data {reallen} bytes")

    # initial padding (same visual behavior)
    print("                                          ", end="")
    sys.stdout.flush()

    if track.audio and towav:
        # RIFF header
        f.write(b"RIFF")
        l_val = reallen + WAV_DATA_HLEN + WAV_FORMAT_HLEN + 4
        f.write(struct.pack("<I", l_val))  # length of file, starting from WAVE
        f.write(b"WAVE")
        # FORMAT header
        f.write(b"fmt ")
        f.write(struct.pack("<I", 0x10))       # length of FORMAT header
        f.write(struct.pack("<H", 0x01))       # constant
        f.write(struct.pack("<H", 0x02))       # channels
        f.write(struct.pack("<I", 44100))      # sample rate
        f.write(struct.pack("<I", 44100 * 4))  # bytes per second
        f.write(struct.pack("<H", 4))          # bytes per sample
        f.write(struct.pack("<H", 2 * 8))      # bits per channel
        # DATA header
        f.write(b"data")
        f.write(struct.pack("<I", reallen))

    realsz = 0
    sect = track.startsect

    while sect <= track.stopsect:
        buf = bf.read(SECTLEN)
        if not buf or len(buf) < SECTLEN:
            break

        if track.audio and swabaudio:
            # swap low and high bytes inside the sector payload
            b = bytearray(buf)
            start = track.bstart
            end = start + track.bsize
            if end > len(b):
                end = len(b)
            for i in range(start, end, 2):
                if i + 1 < len(b):
                    b[i], b[i + 1] = b[i + 1], b[i]
            buf = bytes(b)

        data = buf[track.bstart : track.bstart + track.bsize]

        try:
            f.write(data)
        except OSError as e:
            sys.stderr.write(f" Could not write to track: {e}\n")
            sys.exit(4)

        sect += 1
        realsz += track.bsize

        # Update progress every 500 sectors (like original)
        if ((sect - track.startsect) % 500) == 0:
            fl = float(realsz) / float(reallen) if reallen > 0 else 0.0
            bar = progressbar(fl, 20)
            sys.stdout.write(
                "\r%4d/%-4d MB  [%s] %3.0f %%"
                % (realsz // 1024 // 1024, reallen // 1024 // 1024, bar, fl * 100)
            )
            sys.stdout.flush()

    fl = float(realsz) / float(reallen) if reallen > 0 else 1.0
    bar = progressbar(1.0, 20)
    sys.stdout.write(
        "\r%4d/%-4d MB  [%s] %3.0f %%"
        % (realsz // 1024 // 1024, reallen // 1024 // 1024, bar, fl * 100)
    )
    sys.stdout.flush()
    print()

    try:
        f.close()
    except OSError as e:
        sys.stderr.write(f" Could not fclose track file: {e}\n")
        sys.exit(4)

    return 0

def main(args: Args):
    binfile = args.binfile
    cuefile = args.cuefile
    basefile = args.basefile
    verbose = args.verbose
    
    sys.stdout.write(VERSTR)

    try:
        binf = open(binfile, "rb")
    except OSError as e:
        sys.stderr.write(f"Could not open BIN {binfile}: {e}\n")
        return 2

    try:
        cuef = open(cuefile, "r", encoding="latin-1")
    except OSError as e:
        sys.stderr.write(f"Could not open CUE {cuefile}: {e}\n")
        binf.close()
        return 2

    print("Reading the CUE file:")

    # Skip first line (FILE line)
    try:
        first = cuef.readline()
    except OSError as e:
        sys.stderr.write(f"Could not read first line from {cuefile}: {e}\n")
        binf.close()
        cuef.close()
        return 3
    if not first:
        sys.stderr.write(f"Could not read first line from {cuefile}: unexpected EOF\n")
        binf.close()
        cuef.close()
        return 3

    tracks = []
    track = None
    prevtrack = None

    for line in cuef:
        s = line.rstrip("\r\n")

        if "TRACK" in s:
            print("\nTrack ", end="")
            idx = s.find("TRACK")
            p_idx = s.find(" ", idx)
            if p_idx == -1:
                sys.stderr.write("... ouch, no space after TRACK.\n")
                continue
            p_idx += 1
            t_idx = s.find(" ", p_idx)
            if t_idx == -1:
                sys.stderr.write("... ouch, no space after track number.\n")
                continue

            num_str = s[p_idx:t_idx]

            prevtrack = track
            track = Track()
            tracks.append(track)

            try:
                track.num = int(num_str)
            except ValueError:
                sys.stderr.write("... ouch, invalid track number.\n")
                continue

            mode_str = s[t_idx + 1 :].strip()
            print(f"{track.num:2d}: {mode_str[:12]} ", end="")
            track.modes = mode_str
            track.extension = None
            track.mode = 0
            track.audio = 0
            track.bsize = track.bstart = -1
            track.startsect = track.stopsect = -1

            gettrackmode(track, mode_str, args)

        elif "INDEX" in s:
            idx = s.find("INDEX")
            p_idx = s.find(" ", idx)
            if p_idx == -1:
                print("... ouch, no space after INDEX.")
                continue
            p_idx += 1
            t_idx = s.find(" ", p_idx)
            if t_idx == -1:
                print("... ouch, no space after index number.")
                continue

            index_num_str = s[p_idx:t_idx]
            time_str = s[t_idx + 1 :].strip()
            print(f" {index_num_str} {time_str}", end="")
            if track is None:
                continue
            track.startsect = time2frames(time_str)
            track.start = track.startsect * SECTLEN
            if verbose:
                print(f" (startsect {track.startsect} ofs {track.start})", end="")
            if prevtrack is not None and prevtrack.stopsect < 0:
                prevtrack.stopsect = track.startsect
                prevtrack.stop = track.start - 1

    if track is not None:
        binf.seek(0, os.SEEK_END)
        track.stop = binf.tell()
        track.stopsect = track.stop // SECTLEN

    print("\n")

    for tr in tracks:
        writetrack(binf, tr, basefile, args)

    binf.close()
    cuef.close()

    print("End of Conversion\n")
    return 0


if __name__ == "__main__":
    argv = sys.argv
    args = parse_args(argv)
    sys.exit(main(args))
