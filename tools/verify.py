"""Execute the assembled Z80, not a Python copy of the renderer."""
import json
import random
import struct
from pathlib import Path

import z80

BUILD = Path(__file__).resolve().parents[1] / 'build'
SYMBOLS = {line.split(':')[0]: int(line.split()[-1], 16)
           for line in (BUILD/'main.sym').read_text().splitlines()}
PLANS = json.loads((BUILD/'plans.json').read_text())
PAGES = {b: (BUILD/f'bank{b}.bin').read_bytes() for b in (0, 1, 3, 4)}
CODE = (BUILD/'main.bin').read_bytes()
CPU_HZ = 3546900


def address(y, column):
    return 0x4000 + ((y & 0xc0) << 5) + ((y & 7) << 8) + ((y & 56) << 2) + column


def machine():
    m = z80.Z80Machine()
    m.set_memory_block(0x8000, CODE)

    def output(port, value):
        if port == 0x7ffd:
            assert value & 0xf8 == 0x10, 'Unexpected paging/ROM/screen bits'
            m.set_memory_block(0xc000, PAGES[value & 7])
    m.set_output_callback(output)
    return m


def run_to(m, end, budget=5_000_000):
    m.set_breakpoint(end)
    m.ticks_to_stop = budget
    while True:
        events = m.run()
        if events & 1:
            break
        if m.ticks_to_stop == 0 or events & 4:
            raise AssertionError(f'CPU timeout at {m.pc:04x}')
    assert m.pc == end
    m.clear_breakpoint(end)
    return budget - m.ticks_to_stop


def call(m, name):
    m.sp = 0xbfee
    m.set_memory_block(m.sp, struct.pack('<H', 0x7fff))
    m.pc = SYMBOLS[name]
    return run_to(m, 0x7fff)


def expected(sprite, n):
    bitmap = bytearray([0x55]*6144)
    for y in range(32, 160):
        for column in range(8, 24):
            bitmap[address(y, column)-0x4000] = 0
    top = (192-n)//2
    left = (256-n)//2
    for y in range(n):
        sy = int((y + 0.5) * 64 / n)
        for x in range(n):
            sx = int((x + 0.5) * 64 / n)
            if sprite[sy*8 + sx//8] & (128 >> (sx % 8)):
                bitmap[address(top+y, (left+x)//8)-0x4000] |= 128 >> ((left+x) % 8)
    return bitmap


def verify_tape():
    data = (BUILD/'scaling.tap').read_bytes()
    blocks = []
    while data:
        length, = struct.unpack_from('<H', data)
        block, data = data[2:2+length], data[2+length:]
        assert len(block) == length
        checksum = 0
        for byte in block:
            checksum ^= byte
        assert checksum == 0
        blocks.append(block)
    assert len(blocks) == 12
    assert blocks[3][1:-1] == CODE
    for i, bank in enumerate((0, 1, 3, 4)):
        assert blocks[5+2*i][1:-1] == PAGES[bank]
    assert len((BUILD/'scaling.sna').read_bytes()) == 131103


def main():
    verify_tape()
    rng = random.Random(128)
    sprites = [(BUILD/'sprite.bin').read_bytes(), bytes(512), bytes([255])*512,
               bytes([0x80])+bytes(511), bytes(511)+bytes([1])]
    sprites += [rng.randbytes(512) for _ in range(3)]
    measurements = {}
    for pattern, sprite in enumerate(sprites):
        m = machine()
        m.set_memory_block(SYMBOLS['sprite'], sprite)
        for n in range(16, 129):
            m.set_memory_block(0x4000, bytes([0x55])*6912)
            m.memory[SYMBOLS['size']] = n
            clear_ticks = call(m, 'clear_box')
            select_ticks = call(m, 'select_plan')
            plan = PLANS[str(n)]
            start = plan['address']-49152
            assert bytes(m.memory[SYMBOLS['plan']:SYMBOLS['plan']+plan['length']]) == PAGES[plan['bank']][start:start+plan['length']]
            render_ticks = call(m, 'render')
            assert bytes(m.memory[0x4000:0x5800]) == expected(sprite, n), (pattern, n)
            assert bytes(m.memory[0x5800:0x5b00]) == bytes([0x55])*768
            if pattern == 0:
                measurements[n] = dict(clear=clear_ticks, select=select_ticks,
                                       render=render_ticks,
                                       total=clear_ticks+select_ticks+render_ticks)
    m = machine()
    m.pc = SYMBOLS['entry']
    run_to(m, SYMBOLS['frame_done'])
    boot_expected = expected(sprites[0], 16)
    # Initialization clears the whole screen, unlike the 0x55 canaries above.
    for y in range(192):
        for column in range(32):
            if not (32 <= y < 160 and 8 <= column < 24):
                boot_expected[address(y, column)-0x4000] = 0
    assert bytes(m.memory[0x4000:0x5800]) == boot_expected
    assert bytes(m.memory[0x5800:0x5b00]) == bytes([7])*768
    # Start from the generated 128K snapshot and exercise a full oscillation.
    snapshot = (BUILD/'scaling.sna').read_bytes()
    m = machine()
    m.set_memory_block(0x4000, snapshot[27:27+49152])
    m.pc = struct.unpack_from('<H', snapshot, 27+49152)[0]
    m.sp = struct.unpack_from('<H', snapshot, 23)[0]
    m.i = snapshot[0]
    run_to(m, SYMBOLS['frame_done'])
    sequence = [16]
    for _ in range(224):
        m.ticks_to_stop = 100
        m.run()
        assert m.halted, 'HALT synchronization failed'
        assert m.on_handle_active_int(), 'IM2 interrupt was not accepted'
        run_to(m, SYMBOLS['frame_done'])
        n = m.memory[SYMBOLS['size']]
        sequence.append(n)
        reference = expected(sprites[0], n)
        for y in range(192):
            for column in range(32):
                if not (32 <= y < 160 and 8 <= column < 24):
                    reference[address(y, column)-0x4000] = 0
        assert bytes(m.memory[0x4000:0x5800]) == reference, ('animation', n)
    assert sequence == list(range(16, 129)) + list(range(127, 15, -1))
    (BUILD/'timings.json').write_text(json.dumps(measurements, indent=2))
    print(f'PASS: {len(sprites)*113} Z80 renders, all 113 sizes, 8 sprite patterns; '
          'paging, screen layout, bounds, padding and boot verified.')
    print('TAP checksums/payloads and SNA layout verified (not ROM tape loading).')
    print('PASS: SNA boot + 225 animation frames, IM2/HALT, both reversals.')
    print('Size  Clear  Select  Render  Total T-states  Ideal ms (no contention)')
    for n in (16, 32, 48, 64, 96, 128):
        t = measurements[n]
        print(f'{n:4} {t["clear"]:6} {t["select"]:7} {t["render"]:7} '
              f'{t["total"]:14} {t["total"]*1000/CPU_HZ:9.2f}')


if __name__ == '__main__':
    main()
