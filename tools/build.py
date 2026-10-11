"""Build sprite-independent scaling plans and a Spectrum 128K demo."""
import argparse
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'
BANKS = [0, 1, 3, 4]


def source_sprite():
    # One 64x64 image: border, circle, asymmetric arrow and checker detail.
    pixels = []
    for y in range(64):
        for x in range(64):
            radius = (x - 31) ** 2 + (y - 31) ** 2
            on = (x in (1, 62) or y in (1, 62) or 650 < radius < 820
                  or (12 <= x <= 40 and 28 <= y <= 35)
                  or (36 <= x <= 50 and abs(y - 31) <= 50 - x)
                  or (8 <= x < 24 and 8 <= y < 24 and (x//2 + y//2) % 2))
            pixels.append(int(on))
    return bytes(sum(pixels[i + bit] << (7-bit) for bit in range(8))
                 for i in range(0, 4096, 8))


def make_plan(n):
    # Pixel-centre nearest neighbour: same transform on both axes.
    samples = [((2*x + 1)*64)//(2*n) for x in range(n)]
    padding = ((256-n)//2) % 8
    width = (padding+n+7)//8
    result = bytearray([width, *samples])
    for first in range(0, width*8, 8):
        groups = {}
        for bit in range(8):
            x = first+bit-padding
            if not 0 <= x < n:
                continue
            source = samples[x]
            groups.setdefault(source//4, []).append((source%4, 7-bit))
        result.append(len(groups))
        for nibble, mapping in sorted(groups.items()):
            result.extend([nibble//2, int(nibble % 2 == 0)])
            result.extend(sum(((value >> (3-src)) & 1) << dst
                              for src, dst in mapping) for value in range(16))
    return bytes(result)


def tape_block(flag, payload):
    data = bytes([flag]) + payload
    checksum = 0
    for b in data:
        checksum ^= b
    return struct.pack('<H', len(data)+1) + data + bytes([checksum])


def tape_file(kind, name, data, p1, p2):
    header = bytes([kind]) + name.encode().ljust(10, b' ')[:10]
    header += struct.pack('<HHH', len(data), p1, p2)
    return tape_block(0, header) + tape_block(255, data)


def number(n):
    return str(n).encode() + b'\x0e\x00\x00' + struct.pack('<H', n) + b'\x00'


def basic_loader(banks=BANKS):
    # Tokenized 48K BASIC; supported by the 128K's 48K ROM too.
    statements = [b'\xfd ' + number(32767), b'\xef ""\xaf']
    for bank in banks:
        statements.extend([b'\xdf ' + number(32765) + b',' + number(16+bank),
                           b'\xef ""\xaf'])
    statements.extend([b'\xdf ' + number(32765) + b',' + number(16),
                       b'\xf9 \xc0 ' + number(32768)])
    lines = bytearray()
    for i, statement in enumerate(statements, 1):
        body = statement + b'\r'
        lines.extend(struct.pack('>H', i*10) + struct.pack('<H', len(body)) + body)
    return bytes(lines)


def write_images(output, code, pages, banks):
    loader = basic_loader(banks)
    tap = tape_file(0, 'SCALING', loader, 10, len(loader))
    tap += tape_file(3, 'ENGINE', code, 32768, 0)
    for bank in banks:
        tap += tape_file(3, f'BANK{bank}', pages[bank], 49152, 0)
    (output/'scaling.tap').write_bytes(tap)
    header = bytearray(27)
    header[0] = 0xbe
    header[23:25] = struct.pack('<H', 0xbff0)
    header[25] = 2
    screen = bytearray(16384)
    screen[6144:6912] = bytes([7])*768
    snapshot = bytes(header) + screen + code.ljust(16384, b'\x00') + pages[0]
    snapshot += struct.pack('<HBB', 32768, 16, 0)
    snapshot += b''.join(pages.get(b, bytes(16384)) for b in [1, 3, 4, 6, 7])
    assert len(snapshot) == 131103
    (output/'scaling.sna').write_bytes(snapshot)


def build_cached(assembler):
    output = BUILD/'cached'
    output.mkdir(exist_ok=True)
    banks = [0, 1, 3, 4, 6]
    pages = {bank: bytearray(16384) for bank in banks}
    directory = bytearray()
    manifest = {}
    page_index = offset = 0
    for n in range(16, 129, 2):
        plan = make_plan(n)
        if offset+len(plan) > 16384:
            page_index += 1
            offset = 0
        assert page_index < 2, 'Plans must fit banks 0 and 1'
        bank = banks[page_index]
        pages[bank][offset:offset+len(plan)] = plan
        directory.extend(struct.pack('<BHH', bank, 49152+offset, len(plan)))
        manifest[n] = dict(bank=bank, address=49152+offset, length=len(plan))
        offset += len(plan)
    # Cache header: one byte of row width, then row-major pixels and padding.
    # Fit complete frames using first-fit decreasing; no frame crosses a bank.
    lengths = {n: ((1+n*make_plan(n)[0]+15)//16)*16 for n in manifest}
    used = {b: 0 for b in (3, 4, 6)}
    cache = {}
    for n in sorted(lengths, key=lengths.get, reverse=True):
        length = lengths[n]
        for bank in used:
            if used[bank]+length <= 16384:
                cache[n] = dict(bank=bank, address=49152+used[bank], length=length,
                                width=make_plan(n)[0], pixels=n*make_plan(n)[0])
                used[bank] += length
                break
        else:
            raise ValueError(f'Cache does not fit: size {n}')
    cache_directory = b''.join(struct.pack('<BHH', cache[n]['bank'],
                                          cache[n]['address'], cache[n]['length'])
                               for n in range(16, 129, 2))
    (output/'directory.bin').write_bytes(directory)
    (output/'sprite.bin').write_bytes((BUILD/'sprite.bin').read_bytes())
    (output/'cache_directory.bin').write_bytes(cache_directory)
    (output/'plans.json').write_text(json.dumps(manifest, indent=2))
    (output/'cache.json').write_text(json.dumps(cache, indent=2))
    for bank, page in pages.items():
        (output/f'bank{bank}.bin').write_bytes(page)
    subprocess.run([assembler, '--sym=build/cached/main.sym', 'src/cached.asm'],
                   cwd=ROOT, check=True)
    code = (output/'main.bin').read_bytes()
    write_images(output, code, pages, banks)
    print(f'Cached variant: {sum(v["length"] for v in manifest.values())} bytes '
          f'of plans; {sum(lengths.values())} bytes cache; banks {used}.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--assembler', default='sjasmplus')
    args = parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    pages = {bank: bytearray(16384) for bank in BANKS}
    directory = bytearray()
    manifest = {}
    page_index = offset = 0
    for n in range(16, 129):
        plan = make_plan(n)
        assert len(plan) <= 1024
        if offset + len(plan) > 16384:
            page_index += 1
            offset = 0
        bank = BANKS[page_index]
        pages[bank][offset:offset+len(plan)] = plan
        directory.extend(struct.pack('<BHH', bank, 49152+offset, len(plan)))
        manifest[n] = dict(bank=bank, address=49152+offset, length=len(plan))
        offset += len(plan)
    (BUILD/'directory.bin').write_bytes(directory)
    (BUILD/'sprite.bin').write_bytes(source_sprite())
    for bank, page in pages.items():
        (BUILD/f'bank{bank}.bin').write_bytes(page)
    subprocess.run([args.assembler, '--sym=build/main.sym', 'src/demo.asm'],
                   cwd=ROOT, check=True)
    code = (BUILD/'main.bin').read_bytes()
    assert len(code) <= 16384
    write_images(BUILD, code, pages, BANKS)
    (BUILD/'plans.json').write_text(json.dumps(manifest, indent=2))
    print(f'113 plans, {sum(v["length"] for v in manifest.values())} bytes; '
          f'{page_index+1} banks used. TAP + 128K SNA written to build/.')
    build_cached(args.assembler)


if __name__ == '__main__':
    main()
