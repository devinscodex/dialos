"""Builds a tiny JPEG with a hand-written EXIF block (camera, date, GPS) for tests."""
import struct


def jpeg_with_exif(base_jpeg: bytes) -> bytes:
    e = "<"
    def entry(tag, typ, cnt, val):
        return struct.pack(e + "HHI", tag, typ, cnt) + val
    def ascii_(s):
        b = s.encode() + b"\x00"
        return len(b), b
    # layout: header(8) | IFD0 | sub IFD | GPS IFD | data
    data = b""
    # we compute offsets after sizes are known: IFD0 has 4 entries, sub 1, gps 4
    ifd0_off = 8
    ifd0_size = 2 + 4 * 12 + 4
    sub_off = ifd0_off + ifd0_size
    sub_size = 2 + 1 * 12 + 4
    gps_off = sub_off + sub_size
    gps_size = 2 + 4 * 12 + 4
    data_off = gps_off + gps_size
    blobs = []
    def blob(b):
        nonlocal data_off
        o = data_off
        blobs.append(b)
        data_off += len(b)
        return struct.pack(e + "I", o)
    make_n, make_b = ascii_("TestCam")
    model_n, model_b = ascii_("Model X")
    date_n, date_b = ascii_("2026:09:30 08:15:00")
    ifd0 = struct.pack(e + "H", 4) + entry(0x010F, 2, make_n, blob(make_b)) + entry(0x0110, 2, model_n, blob(model_b)) \
        + entry(0x8769, 4, 1, struct.pack(e + "I", sub_off)) + entry(0x8825, 4, 1, struct.pack(e + "I", gps_off)) + struct.pack(e + "I", 0)
    sub = struct.pack(e + "H", 1) + entry(0x9003, 2, date_n, blob(date_b)) + struct.pack(e + "I", 0)
    rat = lambda *pairs: b"".join(struct.pack(e + "II", a, b) for a, b in pairs)
    gps = struct.pack(e + "H", 4) + entry(1, 2, 2, b"N\x00\x00\x00") + entry(2, 5, 3, blob(rat((10, 1), (30, 1), (0, 1)))) \
        + entry(3, 2, 2, b"W\x00\x00\x00") + entry(4, 5, 3, blob(rat((66, 1), (0, 1), (36, 1)))) + struct.pack(e + "I", 0)
    tiff = b"II*\x00" + struct.pack(e + "I", 8) + ifd0 + sub + gps + b"".join(blobs)
    seg = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(seg) + 2) + seg
    return base_jpeg[:2] + app1 + base_jpeg[2:]
