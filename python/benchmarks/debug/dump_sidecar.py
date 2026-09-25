import struct, sys
H = struct.Struct('<QQ')
blob = open(sys.argv[1],'rb').read()
off = 0; n = 0
while off + 16 <= len(blob):
    idx, ln = H.unpack_from(blob, off)
    assert off + 16 + ln <= len(blob), (n, idx, ln)
    payload = blob[off+16:off+16+ln]
    lines = payload.split(b'\n')
    first = lines[0][:14] if lines else b''
    last = lines[-2][:14] if len(lines) > 1 else b''
    if n < 5 or b'LINE 00000' in payload[:20] or n % 10 == 0:
        print('rec', n, 'idx', idx, 'len', ln, 'first', first, 'last', last)
    off += 16 + ln; n += 1
print('total records:', n, 'tail:', len(blob)-off)
