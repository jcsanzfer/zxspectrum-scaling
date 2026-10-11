    DEVICE ZXSPECTRUM128
    ORG $8000
entry:
    di
    ld sp,$bff0
    ld a,$be
    ld i,a
    im 2
    xor a
    out ($fe),a
    ld hl,$4000
    call initialize_screen
    ld a,23                   ; ROM 48K, screen 5 visible, RAM bank 7 paged
    ld bc,$7ffd
    out (c),a
    ld hl,$c000
    call initialize_screen
    ei
frame:
    call select_plan
    call select_draw_screen
    call clear_box
    call render
frame_done:
    di                        ; EI/HALT below avoids a flip-before-HALT race
    ld a,1
    ld (flip_pending),a
    ei
wait_flip:
    halt
flip_complete:
    ld a,(flip_pending)
    or a
    jr nz,wait_flip
    ld a,(size)
    ld b,a
    ld a,(direction)
    add a,b
    ld (size),a
    cp 128
    jr z,reverse
    cp 16
    jr nz,frame
reverse:
    ld a,(direction)
    neg
    ld (direction),a
    jr frame

; Initialize bitmap and attributes of the screen at HL ($4000 or $c000).
initialize_screen:
    xor a
    ld d,h
    ld e,l
    inc de
    ld bc,6143
    ld (hl),a
    ldir
    inc hl
    ld d,h
    ld e,l
    inc de
    ld bc,767
    ld (hl),7                 ; white ink, black paper
    ldir
    ret

; Bank 7 stays at $c000 while drawing. Only the hidden screen is modified.
select_draw_screen:
    ld a,(visible_screen)
    or 23
    ld bc,$7ffd
    out (c),a
    ld a,(visible_screen)
    or a
    ld a,$c0
    jr z,draw_base_ready
    ld a,$40
draw_base_ready:
    ld (screen_base),a
    ret

; Clear the fixed 128x128 footprint, not the full screen.
clear_box:
    ld a,32
clear_row:
    push af
    call screen_addr
    ld de,8
    add hl,de
    xor a
    DUP 16
    ld (hl),a
    inc l
    EDUP
    pop af
    inc a
    cp 160
    jr nz,clear_row
    ret

; A=y, HL=Spectrum bitmap address of byte column 0.
screen_addr:
    push af
    ld l,a
    and 7
    ld h,a
    ld a,(screen_base)
    or h
    ld h,a
    ld a,l
    and $38
    rlca
    rlca
    ld l,a
    pop af
    and $c0
    rrca
    rrca
    rrca
    or h
    ld h,a
    ret

; Directory entry: bank, address, length. Copy one plan into common RAM.
select_plan:
    ld a,(size)
    sub 16
    ld l,a
    ld h,0
    ld e,l
    ld d,h
    add hl,hl
    add hl,hl
    add hl,de
    ld de,directory
    add hl,de
    ld a,(hl)
    ld b,a
    ld a,(visible_screen)
    or 16
    or b
    ld bc,$7ffd
    out (c),a
    inc hl
    ld e,(hl)
    inc hl
    ld d,(hl)
    inc hl
    ld c,(hl)
    inc hl
    ld b,(hl)
    ex de,hl
    ld de,plan
    ldir
    ret

; Plan: width in bytes, N source-row numbers, then horizontal byte groups.
render:
    ld a,255
    ld (previous_source),a
    ld a,(plan)
    ld (width),a
    ld a,(size)
    neg                       ; 256-N, then /2/8 -> byte column
    srl a
    srl a
    srl a
    srl a
    ld (x_byte),a
    ld a,(size)
    ld b,a
    ld a,192
    sub b
    srl a
    ld (screen_y),a
    ld a,b
    ld (rows_left),a
    ld hl,plan+1
    ld (y_cursor),hl
    ld e,b
    ld d,0
    add hl,de
    ld (horizontal),hl
render_row:
    ld hl,(y_cursor)
    ld a,(hl)
    inc hl
    ld (y_cursor),hl
    ld b,a
    ld a,(previous_source)
    cp b
    jp z,copy_row
    ld a,b
    ld (previous_source),a
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    ld de,sprite
    add hl,de
    push hl
    pop ix
    ld hl,row_cache
    ld (destination),hl
    ld a,(width)
    ld (bytes_left),a
    ld hl,(horizontal)
render_byte:
    ld b,(hl)                 ; contributions in this output byte
    inc hl
    ld c,0                    ; accumulated output
    ld d,0
contribution:
    ld a,(hl)                 ; source-byte offset 0..7
    inc hl
    ld (fetch+2),a
    ld a,(hl)                 ; 1: high nibble, 0: low nibble
    inc hl
    or a
fetch:
    ld a,(ix+0)
    jr z,low_nibble
    rrca
    rrca
    rrca
    rrca
low_nibble:
    and 15
    ld e,a
    push hl
    add hl,de
    ld a,(hl)                 ; table[nibble]
    pop hl
    or c
    ld c,a
    ld de,16
    add hl,de
    djnz contribution
    ld de,(destination)
    ld a,c
    ld (de),a
    inc de
    ld (destination),de
    ld a,(bytes_left)
    dec a
    ld (bytes_left),a
    jr nz,render_byte
copy_row:
    ld a,(screen_y)
    call screen_addr
    ld a,(x_byte)
    ld e,a
    ld d,0
    add hl,de
    ex de,hl
    ld hl,row_cache
    ld a,(width)
    ld c,a
    ld b,0
    ldir
    ld a,(screen_y)
    inc a
    ld (screen_y),a
    ld a,(rows_left)
    dec a
    ld (rows_left),a
    jp nz,render_row
    ret

size:           db 16
visible_screen: db 0           ; bit 3 of $7ffd, mirrored across ALL paging
screen_base:    db $c0
flip_pending:   db 0
direction:      db 1
width:          db 0
x_byte:         db 0
screen_y:       db 0
rows_left:      db 0
bytes_left:     db 0
y_cursor:      dw 0
horizontal:    dw 0
destination:   dw 0
previous_source: db 255
row_cache:     ds 16
directory:     INCBIN "build/directory.bin"
sprite:        INCBIN "build/sprite.bin"
    ALIGN 256
plan:          ds 1024
    ASSERT $ < $bdbd
    ORG $bdbd
interrupt:
    push af
    push bc
    ld a,(flip_pending)
    or a
    jr z,no_flip
    xor a
    ld (flip_pending),a
    ld a,(visible_screen)
    xor 8
    ld (visible_screen),a
    or 23
    ld bc,$7ffd
    out (c),a                 ; flip immediately after vertical interrupt
no_flip:
    pop bc
    pop af
    ei
    reti
interrupt_end:
    ASSERT $ < $be00
    ORG $be00
    ds 257,$bd                ; any ULA interrupt vector -> $bdbd
    SAVEBIN "build/main.bin",$8000,$bf01-$8000
