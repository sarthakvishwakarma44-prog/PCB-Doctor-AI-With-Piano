import struct


def vlq(value):
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def build(path, melody, ticks=480, bpm=110):
    track = bytearray()
    track += vlq(0) + b'\xff\x51\x03' + (60000000 // bpm).to_bytes(3, 'big')
    wait = 0
    for pitch, beats in melody:
        length = int(ticks * beats)
        track += vlq(wait) + bytes([0x90, pitch, 90])
        track += vlq(int(length * 0.9)) + bytes([0x80, pitch, 0])
        wait = length - int(length * 0.9)
    track += vlq(wait) + b'\xff\x2f\x00'
    with open(path, 'wb') as f:
        f.write(b'MThd' + struct.pack('>IHHH', 6, 0, 1, ticks))
        f.write(b'MTrk' + struct.pack('>I', len(track)) + bytes(track))


scale = [(p, 0.5) for p in (60, 62, 64, 65, 67, 69, 71, 72, 74, 72, 71, 69, 67, 65, 64, 62)] + [(60, 2)]
twinkle = [(60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2), (65, 1), (65, 1), (64, 1), (64, 1), (62, 1), (62, 1), (60, 2)]
build('demo_scale.mid', scale)
build('demo_twinkle.mid', twinkle)
