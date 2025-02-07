#!/usr/bin/env python3
###
# Shared functions
from enum import Enum
import os
from pathlib import Path

import ctypes
import sys
from typing import List
import unicodedata
import re

REGION_CODE_REGEX_BYTES = re.compile(rb'[HhMmPpGgNnCcSsJjTtBbDdAaKk][a-zA-Z]{3}.?\d{3}\.?\d{2}')
REGION_CODE_REGEX_STR = re.compile(r'[HhMmPpGgNnCcSsJjTtBbDdAaKk][a-zA-Z]{3}.?\d{3}\.?\d{2}')

def read_in_chunks(file_object, chunk_size=1024):
    """Lazy function (generator) to read a file piece by piece.
    Default chunk size: 1k."""
    while True:
        data = file_object.read(chunk_size)
        if not data:
            break
        yield data


def path_to_ul_cfg(opl_dir: Path) -> Path:
    return opl_dir.joinpath('ul.cfg')


def get_iso_id(filepath: Path) -> str:
    with open(filepath, 'rb') as f:
        for chunk in read_in_chunks(f):
            id_matches: List[bytes] = REGION_CODE_REGEX_BYTES.findall(chunk)
            if id_matches:
                return id_matches[0].decode("ascii", "ignore")
    raise ValueError(f"Cannot find Game ID for ISO/VCD file '{filepath}'")


def ul_files_from_iso(src_iso: Path, dest_path: Path, force=False) -> int:
    CHUNK_SIZE = 1073741824

    file_part = 0
    with src_iso.open('rb') as f:
        chunk = f.read(CHUNK_SIZE)
        title = re.sub(r'.[iI][sS][oO]', '', src_iso.name)

        while chunk:
            crc32 = hex(usba_crc32(title.encode('ascii')))[2:].upper()
            game_id = get_iso_id(src_iso)
            part = hex(file_part)[2:4].zfill(2).upper()

            filename = f"ul.{crc32}.{game_id}.{part}"
            filepath = dest_path.joinpath(filename)

            if filepath.is_file() and not force:
                print(
                    f"Warn: File '{filename}' already exists! Use -f to force overwrite.")
                return 0

            print(f"Writing File '{filepath}'...")
            with filepath.open('wb') as outfile:
                outfile.write(chunk)
                file_part += 1
                chunk = f.read(CHUNK_SIZE)
                os.chmod(filepath, 0o777)
    return file_part




def slugify(value, allow_unicode=False):
    """
    Normalizes string, **DOESN'T** converts to lowercase, removes non-alpha characters,

    Stolen from: https://docs.djangoproject.com/en/2.1/ref/utils/#django.utils.text.slugify
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode(
            'ascii', 'ignore').decode("ascii", "ignore")
        value = re.sub(r'[^\w\s-]', '', value).strip()
        return value



class ULCorruptionType(Enum):
    REGION_CODE = 1
    MEDIA_TYPE = 2
    NO_CORRUPTION = 3

def check_ul_entry_for_corruption_and_crash(data: bytes):
    if not check_ul_entry_for_corruption(data):
        print(
            f"The entry \'{data[0:32].decode('ascii', 'ignore')}\' in ul.cfg is corrupted, run 'fix' on the directory to try automatically fixing the issue'")
        sys.exit(1)

def check_ul_entry_for_corruption(data: bytes) -> ULCorruptionType:
    if not REGION_CODE_REGEX_BYTES.findall(bytes(data[32:46])):
        return ULCorruptionType.REGION_CODE
    if not (bytes([data[48]]) == b"\x12" or bytes([data[48]]) == b"\x14"):
        return ULCorruptionType.MEDIA_TYPE
    return ULCorruptionType.NO_CORRUPTION

'''


//Original CRC32-Function from OPL-Sourcecode:

unsigned int USBA_crc32(char *string)
{
    int crc, table, count, byte;

    for (table = 0; table < 256; table++) {
        crc = table << 24;

        for (count = 8; count > 0; count--) {
            if (crc < 0)
                crc = crc << 1;
            else
                crc = (crc << 1) ^ 0x04C11DB7;
        }
        crctab[255 - table] = crc;
    }

    do {
        byte = string[count++];
        crc = crctab[byte ^ ((crc >> 24) & 0xFF)] ^ ((crc << 8) & 0xFFFFFF00);
    } while (string[count - 1] != 0);

    return crc;
}
'''


# ^ That function in shitty python
# Generate crc32 from game title for ul.cfg

def usba_crc32(name: bytes):
    name = name.strip(b'\x00')
    crctab = [0] * 1024
    crc = ctypes.c_int32()
    for table in range(0, 256):
        crc = (table << 24)

        for i in range(8, 0, -1):
            crc = ctypes.c_int32(crc).value
            if ((crc)) < 0:
                crc = (crc << 1)
            else:
                crc = (crc << 1) ^ 0x04C11DB7
        crctab[255 - table] = ctypes.c_uint32(crc).value

    c = 0
    name += b'\x00'
    while c < len(name):
        crc = ctypes.c_uint32(crctab[name[c] ^ ((crc >> 24) & 0xFF)]
                              ^ ((crc << 8) & 0xFFFFFF00)).value
        c += 1
    return ctypes.c_uint32(crc).value
