# -*- coding: utf-8 -*-
"""Lector/escritor de los formatos .ctb y .cbddlp (ChiTu).

Estructura según la documentación de catibo
(https://github.com/cbiffle/catibo/blob/master/doc/cbddlp-ctb.adoc):

- Cabecera fija de 112 bytes + ExtConfig (60 B) + ExtConfig2 (76 B).
- Vistas previas RGB15+RLE idénticas a las de .phz (ver phz.py).
- Tabla de capas de 36 bytes por capa.
- Imagen de capa:
    * ctb   : valor de 7 bits (0..127) + largo de corrida variable de
              1-4 bytes en BIG-endian (única parte big-endian del formato).
    * cbddlp: 1 bit por píxel, corrida en el mismo byte (bit alto = color).
- Cifrado: se escribe siempre con encryption_key = 0 (sin cifrar), igual
  que hace catibo; las impresoras lo aceptan sin problema.
"""

import hashlib
import struct

import numpy as np

from .phz import encode_preview_rgb15, decode_preview_rgb15

MAGIC_CTB = 0x12FD0086
MAGIC_CBDDLP = 0x12FD0019

_HEADER_FIELDS = [
    ("magic", "I"), ("version", "I"),
    ("bed_size_x", "f"), ("bed_size_y", "f"), ("bed_size_z", "f"),
    ("zero1", "I"), ("zero2", "I"),
    ("overall_height_mm", "f"), ("layer_height_mm", "f"),
    ("exposure_s", "f"), ("bottom_exposure_s", "f"), ("light_off_delay_s", "f"),
    ("bottom_layers", "I"),
    ("resolution_x", "I"), ("resolution_y", "I"),
    ("preview_large_offset", "I"), ("layers_definition_offset", "I"),
    ("layer_count", "I"), ("preview_small_offset", "I"),
    ("print_time_s", "I"), ("projector_type", "I"),
    ("ext_config_offset", "I"), ("ext_config_size", "I"),
    ("level_set_count", "I"),
    ("light_pwm", "H"), ("bottom_light_pwm", "H"),
    ("encryption_key", "I"),
    ("ext_config2_offset", "I"), ("ext_config2_size", "I"),
]
_HEADER_FMT = "<" + "".join(f for _, f in _HEADER_FIELDS)
HEADER_SIZE = struct.calcsize(_HEADER_FMT)
assert HEADER_SIZE == 112, HEADER_SIZE

_EXTCFG_FMT = "<10f5I"  # 60 bytes
_EXTCFG_SIZE = struct.calcsize(_EXTCFG_FMT)
assert _EXTCFG_SIZE == 60

_EXTCFG2_FMT = "<19I"   # 76 bytes
_EXTCFG2_SIZE = struct.calcsize(_EXTCFG2_FMT)
assert _EXTCFG2_SIZE == 76

_PREVIEW_FMT = "<8I"
_LAYERDEF_FMT = "<3f2I4I"  # z, exposure, light_off, offset, len, 4 ceros
LAYERDEF_SIZE = struct.calcsize(_LAYERDEF_FMT)
assert LAYERDEF_SIZE == 36


# ------------------------------------------------------------- RLE de capa

def encode_layer_ctb(image):
    """RLE del .ctb: imagen uint8 (alto, ancho) → bytes.

    El valor de píxel se reduce a 7 bits (0..127). Corridas de largo
    variable: 0b0xxxxxxx (7 bits), 0b10xxxxxx +1 byte (14), 0b110xxxxx
    +2 bytes (21), 0b1110xxxx +3 bytes (28), big-endian.
    """
    flat = (image.reshape(-1) >> 1).astype(np.uint8)
    n = flat.size
    starts_mask = np.empty(n, dtype=bool)
    starts_mask[0] = True
    starts_mask[1:] = flat[1:] != flat[:-1]
    starts = np.flatnonzero(starts_mask)
    lengths = np.empty(starts.size, dtype=np.int64)
    lengths[:-1] = np.diff(starts)
    lengths[-1] = n - starts[-1]
    values = flat[starts]

    out = bytearray()
    append = out.append
    for val, run in zip(values.tolist(), lengths.tolist()):
        if run == 1:
            append(val)
            continue
        append(val | 0x80)
        if run < (1 << 7):
            append(run)
        elif run < (1 << 14):
            append(0x80 | (run >> 8))
            append(run & 0xFF)
        elif run < (1 << 21):
            append(0xC0 | (run >> 16))
            append((run >> 8) & 0xFF)
            append(run & 0xFF)
        else:
            append(0xE0 | (run >> 24))
            append((run >> 16) & 0xFF)
            append((run >> 8) & 0xFF)
            append(run & 0xFF)
    return bytes(out)


def decode_layer_ctb(data, width, height):
    out = np.zeros(width * height, dtype=np.uint8)
    limit = out.size
    idx = 0
    i = 0
    n = len(data)
    while i < n:
        first = data[i]
        i += 1
        val = first & 0x7F
        run = 1
        if first & 0x80:
            b0 = data[i]
            i += 1
            if b0 < 0x80:
                run = b0
            elif b0 < 0xC0:
                run = ((b0 & 0x3F) << 8) | data[i]
                i += 1
            elif b0 < 0xE0:
                run = ((b0 & 0x1F) << 16) | (data[i] << 8) | data[i + 1]
                i += 2
            else:
                run = (((b0 & 0x0F) << 24) | (data[i] << 16)
                       | (data[i + 1] << 8) | data[i + 2])
                i += 3
        if idx + run > limit:
            raise ValueError("RLE ctb corrupto (exceso de píxeles)")
        # 7 bits → 8 bits (127 → 255)
        out[idx:idx + run] = (val << 1) | (1 if val == 0x7F else 0)
        idx += run
    return out.reshape(height, width)


def encode_layer_rle1(image):
    """RLE del .cbddlp: 1 bit por píxel, corridas ≤ 0x7D en un byte."""
    flat = (image.reshape(-1) > 127)
    n = flat.size
    starts_mask = np.empty(n, dtype=bool)
    starts_mask[0] = True
    starts_mask[1:] = flat[1:] != flat[:-1]
    starts = np.flatnonzero(starts_mask)
    lengths = np.empty(starts.size, dtype=np.int64)
    lengths[:-1] = np.diff(starts)
    lengths[-1] = n - starts[-1]
    values = flat[starts]

    out = bytearray()
    append = out.append
    for val, run in zip(values.tolist(), lengths.tolist()):
        color = 0x80 if val else 0x00
        n_full, rem = divmod(run, 0x7D)
        for _ in range(n_full):
            append(color | 0x7D)
        if rem:
            append(color | rem)
    return bytes(out)


def decode_layer_rle1(data, width, height):
    out = np.zeros(width * height, dtype=np.uint8)
    limit = out.size
    idx = 0
    for code in data:
        run = code & 0x7F
        if idx + run > limit:
            raise ValueError("RLE1 corrupto (exceso de píxeles)")
        if code & 0x80:
            out[idx:idx + run] = 255
        idx += run
    return out.reshape(height, width)


# ------------------------------------------------------------------ escritor

class CtbWriter:
    """Escribe .ctb o .cbddlp capa a capa. Misma interfaz que PhzWriter."""

    def __init__(self, path, settings, kind="ctb"):
        if kind not in ("ctb", "cbddlp"):
            raise ValueError(f"Formato desconocido: {kind}")
        self.kind = kind
        self.path = path
        self.s = dict(settings)
        self.f = open(path, "wb")
        self.f.write(b"\x00" * HEADER_SIZE)
        self._preview_small_offset = 0
        self._preview_large_offset = 0
        self._extcfg_offset = 0
        self._extcfg2_offset = 0
        self._machine_name_offset = 0
        self._machine_name_size = 0
        self._layerdefs_offset = 0
        self._layer_count = int(self.s["layer_count"])
        self._layers_written = 0
        self._layerdefs = []
        self._data_cursor = 0
        self._dedup = {}

    def write_previews(self, small_rgb, large_rgb):
        for which, img in (("small", small_rgb), ("large", large_rgb)):
            blob = encode_preview_rgb15(img)
            pos = self.f.tell()
            if which == "small":
                self._preview_small_offset = pos
            else:
                self._preview_large_offset = pos
            header = struct.pack(
                _PREVIEW_FMT, img.shape[1], img.shape[0],
                pos + struct.calcsize(_PREVIEW_FMT), len(blob), 0, 0, 0, 0)
            self.f.write(header)
            self.f.write(blob)

    def begin_layers(self):
        s = self.s
        # ExtConfig
        self._extcfg_offset = self.f.tell()
        self.f.write(struct.pack(
            _EXTCFG_FMT,
            s.get("bottom_lift_height_mm", 5.0),
            s.get("bottom_lift_speed_mmpm", 65.0),
            s.get("lift_height_mm", 5.0),
            s.get("lift_speed_mmpm", 65.0),
            s.get("retract_speed_mmpm", 150.0),
            s.get("volume_ml", 0.0),
            s.get("weight_g", 0.0),
            s.get("cost", 0.0),
            s.get("bottom_light_off_delay_s", 1.0),
            s.get("light_off_delay_s", 1.0),
            int(s["bottom_layers"]), 0, 0, 0, 0))
        # nombre de máquina + ExtConfig2
        name = (s.get("machine_name", "") or "").encode("ascii", "replace")
        self._machine_name_offset = self.f.tell() if name else 0
        self._machine_name_size = len(name)
        self.f.write(name)

        self._extcfg2_offset = self.f.tell()
        encryption_mode = 0xF if self.kind == "ctb" else 0
        self.f.write(struct.pack(
            _EXTCFG2_FMT,
            0, 0, 0, 0, 0, 0, 0,
            self._machine_name_offset, self._machine_name_size,
            encryption_mode,
            0,                       # mysterious_id
            1,                       # antialias_level
            0x01060300,              # software_version
            0x200,                   # visto en archivos reales
            0, 0, 0, 0, 0))

        self._layerdefs_offset = self.f.tell()
        self.f.write(b"\x00" * (LAYERDEF_SIZE * self._layer_count))
        self._data_cursor = self.f.tell()

    def write_layer(self, image, position_z, exposure_s, light_off_s):
        if self.kind == "ctb":
            rle = encode_layer_ctb(image)
        else:
            rle = encode_layer_rle1(image)
        digest = hashlib.sha1(rle).digest()
        if digest in self._dedup:
            addr, size = self._dedup[digest]
        else:
            addr = self._data_cursor
            self.f.seek(addr)
            self.f.write(rle)
            size = len(rle)
            self._data_cursor += size
            self._dedup[digest] = (addr, size)

        self._layerdefs.append(struct.pack(
            _LAYERDEF_FMT, position_z, exposure_s, light_off_s,
            addr, size, 0, 0, 0, 0))
        self._layers_written += 1

    def close(self):
        if self._layers_written != self._layer_count:
            raise ValueError(
                f"Se esperaban {self._layer_count} capas, "
                f"se escribieron {self._layers_written}")
        self.f.seek(self._layerdefs_offset)
        self.f.write(b"".join(self._layerdefs))

        s = self.s
        values = {
            "magic": MAGIC_CTB if self.kind == "ctb" else MAGIC_CBDDLP,
            "version": 2,
            "bed_size_x": s["bed_size_x"], "bed_size_y": s["bed_size_y"],
            "bed_size_z": s["bed_size_z"],
            "overall_height_mm": s.get("overall_height_mm", 0.0),
            "layer_height_mm": s["layer_height_mm"],
            "exposure_s": s["exposure_s"],
            "bottom_exposure_s": s["bottom_exposure_s"],
            "light_off_delay_s": s.get("light_off_delay_s", 1.0),
            "bottom_layers": int(s["bottom_layers"]),
            "resolution_x": s["resolution_x"], "resolution_y": s["resolution_y"],
            "preview_large_offset": self._preview_large_offset,
            "layers_definition_offset": self._layerdefs_offset,
            "layer_count": self._layer_count,
            "preview_small_offset": self._preview_small_offset,
            "print_time_s": int(s.get("print_time_s", 0)),
            "projector_type": s.get("projector_type", 1),
            "ext_config_offset": self._extcfg_offset,
            "ext_config_size": _EXTCFG_SIZE,
            "level_set_count": 1,
            "light_pwm": s.get("light_pwm", 255),
            "bottom_light_pwm": s.get("bottom_light_pwm", 255),
            "encryption_key": 0,
            "ext_config2_offset": self._extcfg2_offset,
            "ext_config2_size": _EXTCFG2_SIZE,
        }
        packed = struct.pack(
            _HEADER_FMT, *[values.get(name, 0) for name, _ in _HEADER_FIELDS])
        self.f.seek(0)
        self.f.write(packed)
        self.f.close()


# --------------------------------------------------------------------- lector

class CtbReader:
    """Lector de .ctb/.cbddlp para verificación round-trip."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            data = f.read()
        self.raw = data
        vals = struct.unpack_from(_HEADER_FMT, data, 0)
        self.header = {name: v for (name, _), v in zip(_HEADER_FIELDS, vals)}
        if self.header["magic"] == MAGIC_CTB:
            self.kind = "ctb"
        elif self.header["magic"] == MAGIC_CBDDLP:
            self.kind = "cbddlp"
        else:
            raise ValueError("No es un archivo CTB/CBDDLP válido")
        self.layerdefs = []
        off = self.header["layers_definition_offset"]
        for i in range(self.header["layer_count"]):
            vals = struct.unpack_from(_LAYERDEF_FMT, data, off + i * LAYERDEF_SIZE)
            self.layerdefs.append({
                "position_z": vals[0], "exposure_s": vals[1],
                "light_off_s": vals[2], "addr": vals[3], "size": vals[4],
            })

    def read_layer(self, index):
        ld = self.layerdefs[index]
        blob = self.raw[ld["addr"]:ld["addr"] + ld["size"]]
        w = self.header["resolution_x"]
        h = self.header["resolution_y"]
        if self.kind == "ctb":
            return decode_layer_ctb(blob, w, h)
        return decode_layer_rle1(blob, w, h)

    def read_preview(self, which="large"):
        off = self.header[f"preview_{which}_offset"]
        if not off:
            return None
        rx, ry, img_off, img_len, *_ = struct.unpack_from(_PREVIEW_FMT, self.raw, off)
        return decode_preview_rgb15(self.raw[img_off:img_off + img_len], rx, ry)
