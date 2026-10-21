import zlib, struct
w = h = 64
rows = []
for y in range(h):
    row = bytearray(b'\x00')
    for x in range(w):
        row += bytes([(x * 4) % 256, 120, 200])
    rows.append(bytes(row))
raw = b''.join(rows)
def ch(t, d):
    return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
open('assets/test_photo.png', 'wb').write(b'\x89PNG\r\n\x1a\n' + ch(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + ch(b'IDAT', zlib.compress(raw)) + ch(b'IEND', b''))
print('png ok')
