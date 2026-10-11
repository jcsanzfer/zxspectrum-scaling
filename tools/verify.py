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


class SpectrumMemory:
    """Persist paged RAM and reject writes to the visible screen during drawing."""
    def __init__(self, m):
        self.m = m
        self.pages = {b: bytearray(PAGES.get(b, bytes(16384))) for b in range(8)}
        self.bank = 0
        self.display = 0
        self.guard = False
        self.flips = 0
        m.set_memory_block(0xc000, self.pages[0])
        m.set_output_callback(self.output)
        m.set_write_callback(self.write)
        m.mark_addrs(0x4000, 6912, m.WRITE_MARK)
        m.mark_addrs(0xc000, 6912, m.WRITE_MARK)

    def output(self, port, value):
        if port != 0x7ffd:
            return
        assert value & 0xf0 == 0x10, 'Paging lock or wrong ROM selected'
        display = value & 8
        if display != self.display:
            assert SYMBOLS['interrupt'] <= self.m.pc <= SYMBOLS['interrupt_end'], 'Flip outside IM2'
            assert self.m.memory[SYMBOLS['flip_pending']] == 0
            assert self.m.memory[SYMBOLS['visible_screen']] == display
            self.flips += 1
        self.pages[self.bank][:] = self.m.memory[0xc000:]
        self.bank = value & 7
        self.m.set_memory_block(0xc000, self.pages[self.bank])
        self.display = display

    def write(self, addr, value):
        if self.guard:
            is_visible = (0x4000 <= addr < 0x5b00 and self.display == 0
                          or 0xc000 <= addr < 0xdb00 and self.bank == 7 and self.display == 8)
            assert not is_visible, f'Write to visible screen at {addr:04x}'
        self.m.memory[addr] = value

    def screen(self, bank):
        if bank == 5:
            return bytes(self.m.memory[0x4000:0x5b00])
        assert bank == 7
        if self.bank == 7:
            return bytes(self.m.memory[0xc000:0xdb00])
        return bytes(self.pages[7][:6912])

    def fill_screens(self, value):
        self.m.set_memory_block(0x4000, bytes([value])*6912)
        self.pages[7][:6912] = bytes([value])*6912
        if self.bank == 7:
            self.m.set_memory_block(0xc000, self.pages[7])


def machine():
    m = z80.Z80Machine()
    m.set_memory_block(0x8000, CODE)
    m.spectrum = SpectrumMemory(m)
    return m


def run_to(m, end, budget=5_000_000, interrupts=False):
    m.set_breakpoint(end)
    m.ticks_to_stop = budget
    while True:
        events = m.run()
        if interrupts and events & 8:
            m.on_handle_active_int()
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
        for display in (0, 8):
            m = machine()
            m.spectrum.display = display
            m.memory[SYMBOLS['visible_screen']] = display
            m.set_memory_block(SYMBOLS['sprite'], sprite)
            m.spectrum.guard = True
            for n in range(16, 129):
                m.spectrum.fill_screens(0x55)
                m.memory[SYMBOLS['size']] = n
                select_ticks = call(m, 'select_plan')
                plan = PLANS[str(n)]
                start = plan['address']-49152
                assert bytes(m.memory[SYMBOLS['plan']:SYMBOLS['plan']+plan['length']]) == PAGES[plan['bank']][start:start+plan['length']]
                page_ticks = call(m, 'select_draw_screen')
                clear_ticks = call(m, 'clear_box')
                render_ticks = call(m, 'render')
                target = 7 if display == 0 else 5
                assert m.spectrum.screen(target)[:6144] == expected(sprite, n), (pattern, n, display)
                assert m.spectrum.screen(target)[6144:] == bytes([0x55])*768
                assert m.spectrum.screen(5 if target == 7 else 7) == bytes([0x55])*6912
                assert m.spectrum.flips == 0
                if pattern == 0 and display == 0:
                    measurements[n] = dict(clear=clear_ticks, select=select_ticks,
                                           page=page_ticks, render=render_ticks,
                                           total=clear_ticks+select_ticks+page_ticks+render_ticks)
    # Decode the generated SNA and boot its actual common RAM/initial page.
    snapshot = (BUILD/'scaling.sna').read_bytes()
    m = machine()
    m.set_memory_block(0x4000, snapshot[27:27+49152])
    remaining = snapshot[27+49152+4:]
    for bank in (1, 3, 4, 6, 7):
        m.spectrum.pages[bank][:] = remaining[:16384]
        remaining = remaining[16384:]
    assert not remaining
    m.pc = struct.unpack_from('<H', snapshot, 27+49152)[0]
    m.sp = struct.unpack_from('<H', snapshot, 23)[0]
    m.i = snapshot[0]
    # Initialization may write both screens. All subsequent writes are guarded.
    run_to(m, SYMBOLS['frame'])
    m.spectrum.guard = True
    run_to(m, SYMBOLS['frame_done'], interrupts=True)
    assert m.spectrum.flips == 0, 'Incomplete first frame displayed'
    sequence = []
    for index in range(225):
        n = m.memory[SYMBOLS['size']]
        sequence.append(n)
        visible = 7 if m.spectrum.display else 5
        visible_before = m.spectrum.screen(visible)
        hidden = 5 if visible == 7 else 7
        reference = expected(sprites[0], n)
        for y in range(192):
            for column in range(32):
                if not (32 <= y < 160 and 8 <= column < 24):
                    reference[address(y, column)-0x4000] = 0
        expected_screen = bytes(reference) + bytes([7])*768
        assert m.spectrum.screen(hidden) == expected_screen, ('hidden frame', n)
        # Enter HALT: no flip and no visible changes until the interrupt.
        m.ticks_to_stop = 100
        m.run()
        assert m.halted and m.memory[SYMBOLS['flip_pending']] == 1
        assert m.spectrum.screen(visible) == visible_before
        assert m.on_handle_active_int(), 'IM2 interrupt was not accepted'
        run_to(m, SYMBOLS['flip_complete'])  # ISR finished; main has not rendered again
        assert m.spectrum.flips == index+1
        assert m.memory[SYMBOLS['flip_pending']] == 0
        assert m.spectrum.screen(hidden) == expected_screen
        assert m.spectrum.screen(visible) == visible_before
        # Periodic interrupts during slow draws must leave the displayed frame intact.
        run_to(m, SYMBOLS['frame_done'], interrupts=True)
        assert m.spectrum.flips == index+1
        assert m.spectrum.screen(hidden) == expected_screen
    assert sequence == list(range(16, 129)) + list(range(127, 15, -1))
    (BUILD/'timings.json').write_text(json.dumps(measurements, indent=2))
    print(f'PASS: {len(sprites)*113*2} Z80 renders on both screens, all 113 sizes, 8 sprite patterns; '
          'paging, screen layout, bounds, padding and boot verified.')
    print('TAP checksums/payloads and SNA layout verified (not ROM tape loading).')
    print('PASS: SNA boot + 225 VBlank flips, both reversals; no visible-screen writes or incomplete frames.')
    print('Size  Clear  Select+Page  Render  Total T-states  Ideal ms (no contention)')
    for n in (16, 32, 48, 64, 96, 128):
        t = measurements[n]
        print(f'{n:4} {t["clear"]:6} {t["select"]+t["page"]:11} {t["render"]:7} '
              f'{t["total"]:14} {t["total"]*1000/CPU_HZ:9.2f}')


if __name__ == '__main__':
    main()
