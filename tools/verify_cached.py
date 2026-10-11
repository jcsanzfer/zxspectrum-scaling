"""Validate Z80 startup caching and copies against an independent pixel oracle."""
import json
import os
from pathlib import Path
import random
import struct

ROOT = Path(__file__).resolve().parents[1]
os.environ['ZX_BUILD'] = str(ROOT/'build/cached')
import verify as v

CACHE = json.loads((v.BUILD/'cache.json').read_text())
SEQUENCE = list(range(16, 129, 2)) + list(range(126, 15, -2))


def page(m, bank):
    if m.spectrum.bank == bank:
        return bytes(m.memory[0xc000:])
    return bytes(m.spectrum.pages[bank])


def check_cache(m, sprite):
    for n in range(16, 129, 2):
        info = CACHE[str(n)]
        width = info['width']
        bitmap = v.expected(sprite, n)
        top, left = (192-n)//2, (256-n)//16
        pixels = b''.join(bitmap[v.address(top+y, left)-0x4000:
                                v.address(top+y, left)-0x4000+width] for y in range(n))
        reference = (bytes([width])+pixels).ljust(info['length'], b'\x00')
        start = info['address']-49152
        assert start % 16 == 0 and info['length'] % 16 == 0
        assert start+info['length'] <= 16384
        assert page(m, info['bank'])[start:start+info['length']] == reference, n
    for bank in (0, 1):
        assert page(m, bank) == v.PAGES[bank], 'Precomputation corrupted plans'


def initial_bitmap():
    return bytes(v.expected(bytes(512), 16))+bytes([0x55])*768


def set_initial_screens(m):
    bitmap = initial_bitmap()
    m.set_memory_block(0x4000, bitmap)
    m.spectrum.pages[7][:6912] = bitmap
    if m.spectrum.bank == 7:
        m.set_memory_block(0xc000, m.spectrum.pages[7])
    m.memory[v.SYMBOLS['old_size5']] = 0
    m.memory[v.SYMBOLS['old_size7']] = 0


def main():
    v.verify_tape()
    rng = random.Random(128)
    sprites = [(v.BUILD/'sprite.bin').read_bytes(), bytes(512), bytes([255])*512,
               bytes([0x80])+bytes(511), bytes(511)+bytes([1])]
    sprites += [rng.randbytes(512) for _ in range(3)]
    measurements = {}
    preparations = []
    for pattern, sprite in enumerate(sprites):
        m = v.machine()
        m.spectrum.guard = True
        m.set_memory_block(v.SYMBOLS['sprite'], sprite)
        preparations.append(v.call(m, 'prepare_cache', budget=100_000_000))
        check_cache(m, sprite)
        immutable = {bank: page(m, bank) for bank in (0, 1, 3, 4, 6)}
        # If the blitter accidentally calls the scaler, execution stops and fails.
        m.set_breakpoint(v.SYMBOLS['render'])
        for initial_display in (0, 8):
            set_initial_screens(m)
            display = initial_display
            old_n = 0
            for n in SEQUENCE:
                m.spectrum.display = display
                m.memory[v.SYMBOLS['visible_screen']] = display
                m.memory[v.SYMBOLS['size']] = n
                visible = 7 if display else 5
                before = m.spectrum.screen(visible)
                ticks = v.call(m, 'draw_cached')
                target = 5 if visible == 7 else 7
                assert m.spectrum.screen(target) == bytes(v.expected(sprite, n))+bytes([0x55])*768, (pattern, n, display)
                assert m.spectrum.screen(visible) == before
                if pattern == 0 and initial_display == 0:
                    measurements.setdefault(n, {})['grow' if n >= old_n else 'shrink'] = ticks
                old_n = n
                display ^= 8
        for bank, data in immutable.items():
            assert page(m, bank) == data, 'Runtime mutated cache or plans'

    # Actual snapshot boot, including on-machine preparation, then 113 flips.
    snapshot = (v.BUILD/'scaling.sna').read_bytes()
    m = v.machine()
    m.set_memory_block(0x4000, snapshot[27:27+49152])
    remaining = snapshot[27+49152+4:]
    for bank in (1, 3, 4, 6, 7):
        m.spectrum.pages[bank][:] = remaining[:16384]
        remaining = remaining[16384:]
    m.pc = struct.unpack_from('<H', snapshot, 27+49152)[0]
    m.sp = struct.unpack_from('<H', snapshot, 23)[0]
    v.run_to(m, v.SYMBOLS['prepare_cache'])
    m.spectrum.guard = True
    v.run_to(m, v.SYMBOLS['frame'], budget=100_000_000)
    check_cache(m, sprites[0])
    m.set_breakpoint(v.SYMBOLS['render'])
    v.run_to(m, v.SYMBOLS['frame_done'], interrupts=True)
    sequence = []
    for index in range(113):
        n = m.memory[v.SYMBOLS['size']]
        sequence.append(n)
        visible = 7 if m.spectrum.display else 5
        hidden = 5 if visible == 7 else 7
        before = m.spectrum.screen(visible)
        reference = v.expected(sprites[0], n)
        for y in range(192):
            for column in range(32):
                if not (32 <= y < 160 and 8 <= column < 24):
                    reference[v.address(y, column)-0x4000] = 0
        ready = bytes(reference)+bytes([7])*768
        assert m.spectrum.screen(hidden) == ready
        m.ticks_to_stop = 100
        m.run()
        assert m.halted and m.memory[v.SYMBOLS['flip_pending']] == 1
        assert m.on_handle_active_int()
        v.run_to(m, v.SYMBOLS['flip_complete'])
        assert m.spectrum.flips == index+1
        assert m.spectrum.screen(hidden) == ready
        assert m.spectrum.screen(visible) == before
        v.run_to(m, v.SYMBOLS['frame_done'], interrupts=True)
        assert m.spectrum.flips == index+1
        assert m.spectrum.screen(hidden) == ready
    assert sequence == SEQUENCE
    result = dict(preparation_tstates=preparations[0], cache_bytes=48784,
                  sizes=measurements)
    (v.BUILD/'timings.json').write_text(json.dumps(result, indent=2))
    print('PASS: 456 Z80-generated cached images; 1808 cached blits on both screens; '
          '113 snapshot flips; no runtime rescaling, stale pixels, visible writes or cache mutation.')
    print(f'Preparation: {preparations[0]} T-states, '
          f'{preparations[0]/v.CPU_HZ:.2f}s ideal (once). Cache: 48784 bytes.')
    print('Size   Grow T-states   Shrink T-states   Worst ideal ms (no contention)')
    for n in (16, 32, 48, 64, 96, 128):
        t = measurements[n]
        print(f'{n:4} {t["grow"]:14} {str(t.get("shrink", "-")):>16} '
              f'{max(t.values())*1000/v.CPU_HZ:14.2f}')


if __name__ == '__main__':
    main()
