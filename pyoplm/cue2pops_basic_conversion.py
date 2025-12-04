#!/usr/bin/env python3
# cue2pops.py — Python reimplementation of BIN/CUE -> IMAGE0.VCD (POPS) converter
# Minimal version: default conversion only (no vmode, no trainer, no gap++/gap--)
# Converted with AI, tested on many BIN/CUE files, seems to generate the same files
# with the original C program
# Last modified: 2025-11-05

import argparse
import os
import sys
import struct

SECTORSIZE = 2352
HEADERSIZE = 0x100000  # POPS header size and I/O chunk size

# --- helpers --------------------------------------------------------------------
def debug_print(debug, *args, **kwargs):
    if debug:
        print(*args, **kwargs)

def file_size(path):
    try:
        return os.path.getsize(path)
    except OSError as e:
        print(f"Error: Failed to get size for {path}: {e}", file=sys.stderr)
        return -1

def bcd_encode(n):  # 0..99 -> one byte BCD
    return ((n // 10) << 4) | (n % 10)

def bcd_decode(b):
    return (b >> 4) * 10 + (b & 0x0F)

def msf_to_lba(mm, ss, ff):
    # mm:ss:ff (decimal) to sectors (LBA from 00:00:00)
    return mm * 60 * 75 + ss * 75 + ff

def add_seconds_bcd(mm_bcd, ss_bcd, ff_bcd, delta_seconds):
    mm = bcd_decode(mm_bcd)
    ss = bcd_decode(ss_bcd)
    ff = bcd_decode(ff_bcd)
    total = mm * 60 + ss + delta_seconds
    if total < 0:
        total = 0
    mm2 = total // 60
    ss2 = total % 60
    return bcd_encode(mm2), bcd_encode(ss2), ff_bcd

def read_cue_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    return raw.decode(errors="ignore")

def parse_cue(cue_text, cue_path, debug=False):
    """
    Minimal parser sufficient to mirror the C tool behavior:
    - find FILE "..." BINARY
    - ensure TRACK 01 MODE2/2352 exists
    - collect per-track INDEX 00 and 01 times (as strings "MM:SS:FF")
    - count PREGAP/POSTGAP
    - find first AUDIO track boundary for daTrack_ptr
    """
    lines = []
    for line in cue_text.splitlines():
        line = line.strip()
        if not line:
            continue
        lines.append(line)

    # Find FILE "..."
    bin_path_decl = None
    for ln in lines:
        if ln.upper().startswith("FILE "):
            try:
                first_quote = ln.index('"')
                second_quote = ln.index('"', first_quote + 1)
                bin_path_decl = ln[first_quote + 1:second_quote]
            except ValueError:
                pass
            break
    if not bin_path_decl:
        raise RuntimeError("Error: The cue sheet is not valid (FILE line not found).")

    # Resolve bin path relative to cue
    if os.path.isabs(bin_path_decl):
        bin_path = bin_path_decl
    else:
        bin_path = os.path.join(os.path.dirname(os.path.abspath(cue_path)), bin_path_decl)

    # Verify MODE2/2352 for TRACK 01
    cue_upper = cue_text.upper()
    if "TRACK 01 MODE2/2352" not in cue_upper:
        raise RuntimeError("Error: Looks like your game dump is not MODE2/2352, or the cue is invalid.")

    # Counters
    pregap_count = sum(1 for ln in lines if ln.upper().startswith("PREGAP"))
    postgap_count = sum(1 for ln in lines if ln.upper().startswith("POSTGAP"))
    binary_count = sum(1 for ln in lines if " BINARY" in ln.upper())
    wave_count = sum(1 for ln in lines if ln.upper().endswith(" WAVE"))

    # Tracks
    tracks = []  # list of dicts: {'num':int,'type':'DATA'|'AUDIO','index00':'MM:SS:FF' or None,'index01':'MM:SS:FF'}
    current_track = None
    for ln in lines:
        up = ln.upper()
        if up.startswith("TRACK "):
            parts = up.split()
            # TRACK NN MODE2/2352  or  TRACK NN AUDIO
            num = int(parts[1])
            typ = 'DATA'
            if "AUDIO" in parts:
                typ = 'AUDIO'
            current_track = {'num': num, 'type': typ, 'index00': None, 'index01': None}
            tracks.append(current_track)
        elif up.startswith("INDEX 00"):
            ts = up.split()[-1]
            if current_track:
                current_track['index00'] = ts
        elif up.startswith("INDEX 01"):
            ts = up.split()[-1]
            if current_track:
                current_track['index01'] = ts

    track_count = len(tracks)
    index1_count = sum(1 for t in tracks if t.get('index01') is not None)

    # Validate counts as in C
    if binary_count == 0:
        raise RuntimeError("Error: Unstandard cue sheet")
    if track_count == 0 or index1_count != track_count:
        raise RuntimeError("Error: Cannot count tracks")
    if binary_count != 1 or wave_count != 0:
        raise RuntimeError("Error: Split dumps are not supported. Use BinMerge/BinMerger to create a single BIN.")

    # Determine daTrack_ptr (first audio boundary)
    daTrack_ptr = 0
    first_audio_idx = None
    for ti, t in enumerate(tracks):
        if t['type'] == 'AUDIO':
            first_audio_idx = ti
            break
    if first_audio_idx is not None:
        t = tracks[first_audio_idx]
        if t['index00']:
            mm, ss, ff = map(int, t['index00'].split(':'))
        else:
            mm, ss, ff = map(int, t['index01'].split(':'))
        daTrack_ptr = msf_to_lba(mm, ss, ff) * SECTORSIZE
        debug_print(debug, f"daTrack_ptr from first AUDIO track: LBA={msf_to_lba(mm,ss,ff)} bytes={daTrack_ptr}")
    else:
        daTrack_ptr = None  # set to EOF later (no CDDA)

    return {
        'bin_path': bin_path,
        'tracks': tracks,
        'pregap_count': pregap_count,
        'postgap_count': postgap_count,
        'daTrack_ptr': daTrack_ptr,
    }

# --- POPS header builder (A0/A1/A2 + per-track entries) -------------------------
def build_pops_header(meta, bin_size, debug=False):
    """
    Mirrors the original layout and behavior closely, including the unconditional +2s
    nudges and CDRWIN fix. Times in header are BCD.
    """
    tracks = meta['tracks']
    pregap_count = meta['pregap_count']
    postgap_count = meta['postgap_count']

    hdr = bytearray(HEADERSIZE)

    # A0: first track info + disc type
    hdr[0]  = 0x41  # first track type (assume DATA; replaced per track entries later if needed)
    hdr[2]  = 0xA0  # descriptor A0
    hdr[7]  = 0x01  # first track number
    hdr[8]  = 0x20  # Disc Type = CD-XA001

    # A1: contents
    hdr[12] = 0xA1
    hdr[17] = bcd_encode(len(tracks))  # number of tracks (BCD)
    content_mixed = any(t['type'] == 'AUDIO' for t in tracks)
    hdr[10] = 0x01 if content_mixed else 0x41
    hdr[20] = hdr[10]

    # A2: lead-in/out
    hdr[22] = 0xA2

    # Lead-out calculation (mirrors the C logic)
    sector_count_full = (bin_size // SECTORSIZE) + (150 * (pregap_count + postgap_count)) + 150
    loM = sector_count_full // 4500
    loS = (sector_count_full - loM * 4500) // 75
    loF = sector_count_full - loM * 4500 - loS * 75
    hdr[27] = bcd_encode(loM)
    hdr[28] = bcd_encode(loS)
    hdr[29] = bcd_encode(loF)

    # The effective sector count stored twice at 1032 and 1036 (LE32)
    sector_count = (bin_size // SECTORSIZE) + (150 * (pregap_count + postgap_count))
    hdr[1032:1036] = struct.pack("<I", sector_count)
    hdr[1036:1040] = struct.pack("<I", sector_count)

    # version ident
    hdr[1024:1028] = bytes([0x6B, 0x48, 0x6E, 0x20])

    # Per-track entries: start at offset 30, 10 bytes per track
    base = 30
    fix_CDRWIN = 1 if (pregap_count == 1 and postgap_count == 0) else 0

    for i, t in enumerate(tracks):
        off = base + i * 10
        # Type: 0x41 DATA, 0x01 AUDIO
        typ = 0x41 if t['type'] == 'DATA' else 0x01
        hdr[off + 0] = typ
        hdr[10] = typ
        hdr[20] = typ
        # Track number (BCD)
        hdr[off + 2] = bcd_encode(t['num'])

        # INDEX 01 always present (validated)
        m1, s1, f1 = (int(x) for x in t['index01'].split(':'))
        # Default INDEX 00 duplicates INDEX 01 if missing
        if t['index00']:
            m0, s0, f0 = (int(x) for x in t['index00'].split(':'))
        else:
            m0, s0, f0 = m1, s1, f1

        mm0, ss0, ff0 = bcd_encode(m0), bcd_encode(s0), bcd_encode(f0)
        mm1, ss1, ff1 = bcd_encode(m1), bcd_encode(s1), bcd_encode(f1)

        # Unconditional +2 sec adjustments (mirror C default behavior):
        # - INDEX 00: +2s for all tracks except the first (i != 0)
        # - INDEX 01: +2s for ALL tracks (including first)
        if i != 0:
            mm0, ss0, ff0 = add_seconds_bcd(mm0, ss0, ff0, +2)
        mm1, ss1, ff1 = add_seconds_bcd(mm1, ss1, ff1, +2)

        # CDRWIN fix adds another +2s for tracks beyond the first
        if fix_CDRWIN and i != 0:
            mm0, ss0, ff0 = add_seconds_bcd(mm0, ss0, ff0, +2)
            mm1, ss1, ff1 = add_seconds_bcd(mm1, ss1, ff1, +2)

        # Write fields:
        # [off+3..5] INDEX 00 (Abs)
        hdr[off + 3] = mm0
        hdr[off + 4] = ss0
        hdr[off + 5] = ff0
        # [off+7..9] INDEX 01 (Rel)
        hdr[off + 7] = mm1
        hdr[off + 8] = ss1
        hdr[off + 9] = ff1

    return hdr, fix_CDRWIN

# --- main conversion -------------------------------------------------------------
def convert(cue_path, out_vcd, debug=False):
    cue_text = read_cue_text(cue_path)
    meta = parse_cue(cue_text, cue_path, debug=debug)

    bin_path = meta['bin_path']
    daTrack_ptr = meta['daTrack_ptr']
    bin_size = file_size(bin_path)
    if bin_size < 0:
        raise RuntimeError(f"Cannot open {bin_path}")

    if daTrack_ptr is None:
        daTrack_ptr = bin_size  # no CDDA => treat full BIN as data (no patchers anyway)

    # Build header
    header, fix_CDRWIN = build_pops_header(meta, bin_size, debug=debug)

    print("\nBIN/CUE to IMAGE0.VCD conversion tool (Python, minimal)")
    print(f"Input  CUE : {cue_path}")
    print(f"Input  BIN : {bin_path}")
    print(f"Output VCD : {out_vcd}\n")

    # Write header
    with open(out_vcd, "wb") as f:
        f.write(header)

    # Stream BIN (no patching)
    print("Saving the virtual CD-ROM image. Please wait...")
    with open(out_vcd, "ab") as vcd, open(bin_path, "rb") as binf:
        # Prime
        first = binf.read(HEADERSIZE)
        if not first:
            raise RuntimeError("Empty BIN?")

        buf = bytearray(first)
        offset = 0

        # Handle CDRWIN padding injection if boundary falls inside this first chunk
        injected = False
        if fix_CDRWIN and (offset + len(buf) >= daTrack_ptr):
            before = daTrack_ptr - offset
            vcd.write(buf[:before])
            pad_len = 150 * SECTORSIZE  # 2 seconds
            vcd.write(bytes(pad_len))
            vcd.write(buf[before:])
            injected = True
        else:
            vcd.write(buf)

        written = len(first)
        total = bin_size
        print(f"{written} -> Source bin size")

        # Continue streaming
        while True:
            chunk = binf.read(HEADERSIZE)
            if not chunk:
                break
            offset = written
            buf = bytearray(chunk)

            if fix_CDRWIN and not injected and (offset + len(buf) >= daTrack_ptr):
                before = daTrack_ptr - offset
                vcd.write(buf[:before])
                pad_len = 150 * SECTORSIZE
                vcd.write(bytes(pad_len))
                vcd.write(buf[before:])
                injected = True
            else:
                vcd.write(buf)

            written += len(chunk)
            pct = (written * 100.0) / total
            print(f"{written} bytes written\t{pct:.1f}%", end="\r")

    print("\nA POPS virtual CD-ROM image was saved to :")
    print(out_vcd)
    print()

def main():
    parser = argparse.ArgumentParser(
        description="BIN/CUE -> IMAGE0.VCD (POPS) converter — minimal (no vmode, no trainer, no gap options)."
    )
    parser.add_argument("cue", help="Input .cue file")
    parser.add_argument("out", nargs="?", help="Optional output .VCD path")
    parser.add_argument("--debug", action="store_true", help="Print extra info")
    # For backward compatibility with old scripts that pass random tokens, accept & ignore them:
    parser.add_argument("--ignore", nargs="*", help=argparse.SUPPRESS, default=[])
    args, extra = parser.parse_known_args()

    cue_path = args.cue
    if not os.path.isfile(cue_path):
        print(f"Error: No input file {cue_path}", file=sys.stderr)
        sys.exit(2)

    out_vcd = args.out
    if out_vcd is None:
        root, _ = os.path.splitext(cue_path)
        out_vcd = root + ".VCD"

    try:
        convert(cue_path, out_vcd, debug=args.debug)
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
