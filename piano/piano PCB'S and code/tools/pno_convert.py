import argparse
import os
import struct
import sys

KEY_COUNT = 15
AUDIO_EXTENSIONS = {'.wav', '.mp3', '.flac', '.ogg', '.m4a'}


def read_vlq(data, pos):
    value = 0
    while True:
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos


def parse_midi(path):
    data = open(path, 'rb').read()
    if data[:4] != b'MThd':
        raise ValueError('not a midi file')
    _, ntracks, division = struct.unpack('>HHH', data[8:14])
    if division & 0x8000:
        raise ValueError('smpte timing is not supported')
    pos = 14
    tempos = [(0, 500000)]
    notes_ticks = []
    for _ in range(ntracks):
        if data[pos:pos + 4] != b'MTrk':
            raise ValueError('broken track header')
        length = struct.unpack('>I', data[pos + 4:pos + 8])[0]
        cursor = pos + 8
        end = cursor + length
        pos = end
        tick = 0
        status = 0
        open_notes = {}
        while cursor < end:
            delta, cursor = read_vlq(data, cursor)
            tick += delta
            first = data[cursor]
            if first == 0xFF:
                kind = data[cursor + 1]
                size, cursor = read_vlq(data, cursor + 2)
                if kind == 0x51 and size == 3:
                    tempos.append((tick, int.from_bytes(data[cursor:cursor + 3], 'big')))
                cursor += size
                continue
            if first in (0xF0, 0xF7):
                size, cursor = read_vlq(data, cursor + 1)
                cursor += size
                continue
            if first & 0x80:
                status = first
                cursor += 1
            kind, channel = status & 0xF0, status & 0x0F
            if kind in (0xC0, 0xD0):
                cursor += 1
                continue
            a, b = data[cursor], data[cursor + 1]
            cursor += 2
            if channel == 9:
                continue
            if kind == 0x90 and b > 0:
                open_notes.setdefault((channel, a), []).append((tick, b))
            elif kind == 0x80 or (kind == 0x90 and b == 0):
                stack = open_notes.get((channel, a))
                if stack:
                    start, velocity = stack.pop(0)
                    notes_ticks.append((start, tick, a, velocity))
        for (channel, pitch), stack in open_notes.items():
            for start, velocity in stack:
                notes_ticks.append((start, tick, pitch, velocity))
    tempos.sort()
    clean = []
    for t, tempo in tempos:
        if clean and clean[-1][0] == t:
            clean[-1] = (t, tempo)
        else:
            clean.append((t, tempo))

    def to_seconds(tick):
        seconds = 0.0
        last_tick, tempo = 0, 500000
        for t, new_tempo in clean:
            if t >= tick:
                break
            seconds += (t - last_tick) * tempo / division / 1e6
            last_tick, tempo = t, new_tempo
        return seconds + (tick - last_tick) * tempo / division / 1e6

    return [(to_seconds(s), to_seconds(e), p, v) for s, e, p, v in notes_ticks]


def parse_audio(path):
    try:
        from basic_pitch.inference import predict
    except ImportError:
        sys.exit('audio files need basic-pitch: pip install basic-pitch  (or convert the song to midi first)')
    _, _, events = predict(path)
    return [(float(s), float(e), int(p), int(round(a * 127))) for s, e, p, a, _ in events]


def fit_to_keys(notes, low, fold):
    fitted = []
    for start, end, pitch, velocity in notes:
        if fold:
            while pitch < low:
                pitch += 12
            while pitch > low + KEY_COUNT - 1:
                pitch -= 12
        elif not low <= pitch < low + KEY_COUNT:
            continue
        fitted.append((start, end, pitch - low, velocity))
    return fitted


def shape_notes(notes, min_on, max_on, min_gap, max_poly):
    notes = sorted(notes, key=lambda n: (n[0], -n[3]))
    per_key = [[] for _ in range(KEY_COUNT)]
    dropped = 0
    accepted = []
    for start, end, key, velocity in notes:
        end = max(end, start + min_on)
        end = min(end, start + max_on)
        active = [n for n in accepted if n[0] <= start < n[1]]
        if len(active) >= max_poly:
            dropped += 1
            continue
        previous = per_key[key][-1] if per_key[key] else None
        if previous is not None and start < previous[1] + min_gap:
            cut = start - min_gap
            if cut - previous[0] >= min_on:
                previous[1] = cut
                accepted[previous[2]][1] = cut
            else:
                dropped += 1
                continue
        entry = [start, end, len(accepted)]
        per_key[key].append(entry)
        accepted.append([start, end, key])
    return [(s, e, k) for s, e, k in accepted], dropped


def build_events(shaped):
    edges = []
    for start, end, key in shaped:
        edges.append((int(round(start * 1000)), 1, key))
        edges.append((int(round(end * 1000)), 0, key))
    edges.sort(key=lambda e: (e[0], e[1]))
    events = []
    mask = 0
    for t, on, key in edges:
        mask = mask | (1 << key) if on else mask & ~(1 << key)
        if events and events[-1][0] == t:
            events[-1] = (t, mask)
        else:
            events.append((t, mask))
    return events


def write_pno(path, events):
    with open(path, 'wb') as out:
        out.write(b'PNO1')
        out.write(struct.pack('<HI', KEY_COUNT, len(events)))
        for t, mask in events:
            out.write(struct.pack('<IH', t, mask))


def convert(source, target, args):
    ext = os.path.splitext(source)[1].lower()
    notes = parse_audio(source) if ext in AUDIO_EXTENSIONS else parse_midi(source)
    if not notes:
        print('%s: no notes found' % source)
        return False
    if args.start_offset:
        notes = [(s - args.start_offset, e - args.start_offset, p, v) for s, e, p, v in notes if s >= args.start_offset]
    notes = fit_to_keys(notes, args.low, not args.no_fold)
    shaped, dropped = shape_notes(notes, args.min_on / 1000, args.max_on / 1000, args.min_gap / 1000, args.max_poly)
    events = build_events(shaped)
    write_pno(target, events)
    length = events[-1][0] / 1000 if events else 0
    print('%s -> %s  notes %d  dropped %d  events %d  length %.1fs' % (os.path.basename(source), os.path.basename(target), len(shaped), dropped, len(events), length))
    if args.dump:
        for t, mask in events:
            print('%8d ms  %s' % (t, ''.join('#' if mask & (1 << k) else '.' for k in range(KEY_COUNT))))
    return True


def main():
    parser = argparse.ArgumentParser(description='Turn a song into a .pno file for the piano player')
    parser.add_argument('source', help='midi or audio file, or a folder of them')
    parser.add_argument('-o', '--output', help='output file or folder')
    parser.add_argument('--low', type=int, default=60, help='midi note of the leftmost key (default 60, middle C)')
    parser.add_argument('--no-fold', action='store_true', help='drop notes outside the key range instead of moving them by octaves')
    parser.add_argument('--max-poly', type=int, default=6, help='most keys pressed at once')
    parser.add_argument('--min-on', type=int, default=70, help='shortest key press in ms')
    parser.add_argument('--max-on', type=int, default=2300, help='longest key press in ms')
    parser.add_argument('--min-gap', type=int, default=45, help='shortest release before the same key is pressed again in ms')
    parser.add_argument('--start-offset', type=float, default=0.0, help='skip this many seconds at the start')
    parser.add_argument('--dump', action='store_true', help='print the key timeline')
    args = parser.parse_args()

    if os.path.isdir(args.source):
        out_dir = args.output or args.source
        os.makedirs(out_dir, exist_ok=True)
        done = 0
        for name in sorted(os.listdir(args.source)):
            stem, ext = os.path.splitext(name)
            if ext.lower() in AUDIO_EXTENSIONS | {'.mid', '.midi'}:
                if convert(os.path.join(args.source, name), os.path.join(out_dir, stem + '.pno'), args):
                    done += 1
        print('%d songs converted' % done)
        return
    target = args.output or os.path.splitext(args.source)[0] + '.pno'
    if os.path.isdir(target):
        target = os.path.join(target, os.path.splitext(os.path.basename(args.source))[0] + '.pno')
    if not convert(args.source, target, args):
        sys.exit(1)


if __name__ == '__main__':
    main()
