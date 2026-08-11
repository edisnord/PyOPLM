import lz4.block
from struct import pack, unpack
from pathlib import Path

ZSO_MAGIC = 0x4F53495A
ZSO_HEADER_SIZE = 0x18
DEFAULT_BLOCK_SIZE = 0x800
COMPRESS_THRESHOLD = 95
DEFAULT_PADDING = b'X'


def lz4_compress(plain: bytes, level: int = 2) -> bytes:
    mode = "high_compression" if level > 1 else "default"
    return lz4.block.compress(plain, mode=mode, compression=level, store_size=False)


def lz4_decompress(compressed: bytes, block_size: int) -> bytes:
    decompressed = None
    while decompressed is None:
        if not compressed:
            raise ValueError("Corrupt ZSO block, cannot decompress")
        try:
            decompressed = lz4.block.decompress(
                compressed, uncompressed_size=block_size)
        except lz4.block.LZ4BlockError:
            compressed = compressed[:-1]
    return decompressed


def read_zso_header(fin) -> tuple:
    fin.seek(0)
    data = fin.read(ZSO_HEADER_SIZE)
    magic, header_size, total_bytes, block_size, ver, align = unpack(
        'IIQIbbxx', data)
    return magic, header_size, total_bytes, block_size, ver, align


def generate_zso_header(total_bytes: int, block_size: int, ver: int, align: int) -> bytes:
    return pack('IIQIbbxx', ZSO_MAGIC, ZSO_HEADER_SIZE, total_bytes, block_size, ver, align)


def set_align(fout, write_pos: int, align: int) -> int:
    if write_pos % (1 << align):
        align_len = (1 << align) - write_pos % (1 << align)
        fout.write(DEFAULT_PADDING * align_len)
        write_pos += align_len
    return write_pos


def compress(iso_path: Path, zso_path: Path, level: int = 2) -> None:
    with open(iso_path, "rb") as fin, open(zso_path, "wb") as fout:
        fin.seek(0, 2)
        total_bytes = fin.tell()
        fin.seek(0)

        if total_bytes % DEFAULT_BLOCK_SIZE:
            raise ValueError(
                f"Input size {total_bytes} is not a multiple of the "
                f"{DEFAULT_BLOCK_SIZE} byte ZSO block size")

        block_size = DEFAULT_BLOCK_SIZE
        align = total_bytes // 2 ** 31
        ver = 1

        header = generate_zso_header(total_bytes, block_size, ver, align)
        fout.write(header)

        total_block = total_bytes // block_size
        index_buf = [0 for _ in range(total_block + 1)]

        fout.write(b"\x00\x00\x00\x00" * len(index_buf))

        write_pos = fout.tell()
        block = 0

        while block < total_block:
            iso_data = fin.read(block_size)
            zso_data = lz4_compress(iso_data, level)

            write_pos = set_align(fout, write_pos, align)
            index_buf[block] = write_pos >> align

            if 100 * len(zso_data) / len(iso_data) >= COMPRESS_THRESHOLD:
                zso_data = iso_data
                index_buf[block] |= 0x80000000
            elif index_buf[block] & 0x80000000:
                raise ValueError(
                    "Align error, you have to increase align by 1 or OPL won't be able to read offset above 2**31 bytes")

            fout.write(zso_data)
            write_pos += len(zso_data)
            block += 1

        index_buf[block] = write_pos >> align

        fout.seek(ZSO_HEADER_SIZE)
        for i in index_buf:
            fout.write(pack('I', i))


def decompress(zso_path: Path, iso_path: Path) -> None:
    with open(zso_path, "rb") as fin, open(iso_path, "wb") as fout:
        magic, header_size, total_bytes, block_size, ver, align = read_zso_header(fin)

        if magic != ZSO_MAGIC or block_size == 0 or total_bytes == 0 or header_size != 24 or ver > 1:
            raise ValueError("zso file format error")

        total_block = total_bytes // block_size

        fin.seek(ZSO_HEADER_SIZE)
        index_buf = [unpack('I', fin.read(4))[0] for _ in range(total_block + 1)]

        block = 0
        while block < total_block:
            index = index_buf[block]
            plain = index & 0x80000000
            index &= 0x7fffffff
            read_pos = index << (align)

            if plain:
                read_size = block_size
            else:
                index2 = index_buf[block + 1] & 0x7fffffff
                read_size = (index2 - index) << (align)
                if block == total_block - 1:
                    read_size = total_bytes - read_pos

            fin.seek(read_pos)
            zso_data = fin.read(read_size)

            if plain:
                dec_data = zso_data
            else:
                dec_data = lz4_decompress(zso_data, block_size)

            if len(dec_data) != block_size:
                raise ValueError(f"Block {block}: decompressed size mismatch")

            fout.write(dec_data)
            block += 1
