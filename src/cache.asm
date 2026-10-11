; This file is included by demo.asm only for the cached variant.
; Startup: render each even size to common RAM, then store it in a cache bank.
prepare_cache:
    ld a,16
prepare_next:
    ld (size),a
    call select_plan
    ld hl,frame_buffer
    ld de,frame_buffer+1
    ld bc,2063
    ld (hl),0
    ldir
    call render
    call select_cached
    ex de,hl
    ld hl,frame_buffer
    call copy_blocks
    ld a,(size)
    add a,2
    cp 130
    jr nz,prepare_next
    ld a,16
    ld (size),a
    ret

; Return HL=cache address, BC=padded length; preserve visible-screen bit.
select_cached:
    ld a,(size)
    sub 16
    srl a
    ld l,a
    ld h,0
    ld e,l
    ld d,h
    add hl,hl
    add hl,hl
    add hl,de
    ld de,cache_directory
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
    ret

; BC is a nonzero multiple of 16. HL=source, DE=destination.
copy_blocks:
    DUP 16
    ldi
    EDUP
    jp pe,copy_blocks
    ret

; A=size -> B=top, C=left byte, D=width in bytes, E=height.
geometry:
    ld e,a
    ld a,192
    sub e
    srl a
    ld b,a
    ld a,e
    neg
    srl a
    ld c,a
    and 7
    add a,e
    add a,7
    srl a
    srl a
    srl a
    ld d,a
    ld a,c
    srl a
    srl a
    srl a
    ld c,a
    ret

draw_cached:
    call select_cached
    ld de,frame_buffer
    call copy_blocks          ; one transfer, avoiding a bank switch per row
    call select_draw_screen
    ld a,(size)
    call geometry
    ld a,b
    ld (new_top),a
    add a,e
    ld (new_bottom),a
    ld a,c
    ld (new_left),a
    add a,d
    ld (new_right),a
    ld a,d
    ld (width),a
    ; Remember geometry independently for both alternating buffers.
    ld hl,old_size7
    ld a,(visible_screen)
    or a
    jr z,old_size_ready
    ld hl,old_size5
old_size_ready:
    ld b,(hl)
    ld a,(size)
    ld (hl),a
    cp b
    jr nc,fringe_done         ; growing overwrites the entire previous image
    ld a,b
    call erase_fringe
fringe_done:
    ld a,(new_top)
    ld (screen_y),a
    ld a,(size)
    ld (rows_left),a
    ld hl,frame_buffer+1
    ld (buffer_cursor),hl
    ; Enter an unrolled LDI sequence at (16-width)*2.
    ld a,(width)
    neg
    add a,16
    add a,a
    ld e,a
    ld d,0
    ld hl,copy_unrolled
    add hl,de
    ld (copy_jump+1),hl
    ld a,(new_top)
    call screen_addr
    ld a,(new_left)
    ld e,a
    ld d,0
    add hl,de
    ex de,hl
    ld hl,frame_buffer+1
    ld a,(width)
    ld (restore_column+2),a
    ld (row_length+1),a
cached_row:
row_length:
    ld bc,0
    call copy_jump
restore_column:
    ld a,e
    sub 0
    ld e,a
    call next_scanline_de
    ld a,(rows_left)
    dec a
    ld (rows_left),a
    jr nz,cached_row
    ret

; Increment Spectrum bitmap row, keeping the byte column constant.
next_scanline_de:
    inc d
    ld a,d
    and 7
    ret nz
    ld a,e
    add a,32
    ld e,a
    ret c
    ld a,d
    sub 8
    ld d,a
    ret
copy_jump:
    jp copy_unrolled
copy_unrolled:
    DUP 16
    ldi
    EDUP
    ret

; A=old size. Clear only old bytes outside the new byte rectangle.
; Padding bits inside the new rectangle are overwritten by the cached image.
erase_fringe:
    call geometry
    ld a,b
    ld (old_top),a
    add a,e
    ld (old_bottom),a
    ld a,c
    ld (old_left),a
    add a,d
    ld (old_right),a
    ld a,d
    ld (old_width),a
    ; Top band.
    ld a,(old_top)
    ld e,a
    ld a,(new_top)
    sub e
    ld b,a
    ld a,(old_left)
    ld c,a
    ld a,(old_width)
    ld d,a
    ld a,e
    call erase_rectangle
    ; Bottom band.
    ld a,(new_bottom)
    ld e,a
    ld a,(old_bottom)
    sub e
    ld b,a
    ld a,(old_left)
    ld c,a
    ld a,(old_width)
    ld d,a
    ld a,e
    call erase_rectangle
    ; Left strip alongside the new image.
    ld a,(old_left)
    ld c,a
    ld a,(new_left)
    sub c
    ld d,a
    ld a,(size)
    ld b,a
    ld a,(new_top)
    call erase_rectangle
    ; Right strip.
    ld a,(new_right)
    ld c,a
    ld a,(old_right)
    sub c
    ld d,a
    ld a,(size)
    ld b,a
    ld a,(new_top)
    jp erase_rectangle

; A=top, B=height, C=left byte, D=width. Zero-sized bands are skipped.
erase_rectangle:
    ld e,a
    ld a,b
    or a
    ret z
    ld (erase_height),a
    ld a,d
    or a
    ret z
    ld (erase_width),a
    ld a,e
    call screen_addr
    ld e,c
    ld d,0
    add hl,de
    ld a,(erase_width)
    ld (erase_restore+2),a
rectangle_row:
    ld a,(erase_width)
    ld b,a
    xor a
rectangle_byte:
    ld (hl),a
    inc l
    djnz rectangle_byte
erase_restore:
    ld a,l
    sub 0
    ld l,a
    call next_scanline_hl
    ld a,(erase_height)
    dec a
    ld (erase_height),a
    jr nz,rectangle_row
    ret
next_scanline_hl:
    inc h
    ld a,h
    and 7
    ret nz
    ld a,l
    add a,32
    ld l,a
    ret c
    ld a,h
    sub 8
    ld h,a
    ret

old_size5:     db 0
old_size7:     db 0
new_top:       db 0
new_bottom:    db 0
new_left:      db 0
new_right:     db 0
old_top:       db 0
erase_width:   db 0
erase_height:  db 0
old_bottom:    db 0
old_left:      db 0
old_right:     db 0
old_width:     db 0
buffer_cursor: dw 0
cache_directory: INCBIN "build/cached/cache_directory.bin"
frame_buffer:  ds 2064
