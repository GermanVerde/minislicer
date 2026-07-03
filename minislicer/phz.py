# -*- coding: utf-8 -*-
"""
Lector/escritor del formato .phz (ChiTuBox / Phrozen Sonic Mini).

Estructura basada en UVtools (PHZFile.cs) y en la documentación de catibo:
https://github.com/cbiffle/catibo/blob/master/doc/cbddlp-ctb.adoc

- Cabecera de 216 bytes (little-endian).
- Dos vistas previas (grande 400x300, pequeña 200x125) en RGB15 + RLE.
- Tabla de capas (36 bytes por capa) seguida de los datos RLE de cada capa.
- Imagen de capa: RLE de 7 bits en escala de grises; las corridas se cortan
  al llegar a la mitad de cada fila y nunca cruzan filas.
- Cifrado XOR opcional (EncryptionKey != 0).
"""

import hashlib
import struct
import time

import numpy as np

MAGIC_PHZ = 0x9FDA83AE
PAGE_SIZE = 4_294_967_296  # las direcciones de datos de capa se paginan a 4 GB

# (nombre, formato struct) en el orden exacto del archivo
_HEADER_FIELDS = [
    ("magic", "I"), ("version", "I"),
    ("layer_height_mm", "f"), ("exposure_s", "f"), ("bottom_exposure_s", "f"),
    ("bottom_layers", "I"),
    ("resolution_x", "I"), ("resolution_y", "I"),
    ("preview_large_offset", "I"), ("layers_definition_offset", "I"),
    ("layer_count", "I"), ("preview_small_offset", "I"),
    ("print_time_s", "I"), ("projector_type", "I"), ("antialias_level", "I"),
    ("light_pwm", "H"), ("bottom_light_pwm", "H"),
    ("padding1", "I"), ("padding2", "I"),
    ("overall_height_mm", "f"),
    ("bed_size_x", "f"), ("bed_size_y", "f"), ("bed_size_z", "f"),
    ("encryption_key", "I"),
    ("bottom_light_off_delay_s", "f"), ("light_off_delay_s", "f"),
    ("bottom_layers2", "I"),
    ("padding3", "I"),
    ("bottom_lift_height_mm", "f"), ("bottom_lift_speed_mmpm", "f"),
    ("lift_height_mm", "f"), ("lift_speed_mmpm", "f"), ("retract_speed_mmpm", "f"),
    ("volume_ml", "f"), ("weight_g", "f"), ("cost", "f"),
    ("padding4", "I"),
    ("machine_name_offset", "I"), ("machine_name_size", "I"),
    ("padding5", "I"), ("padding6", "I"), ("padding7", "I"),
    ("padding8", "I"), ("padding9", "I"), ("padding10", "I"),
    ("encryption_mode", "I"),  # 0x1C para phz
    ("modified_timestamp_min", "I"),
    ("antialias_level_info", "I"),
    ("software_version", "I"),  # 0x01060300
    ("padding11", "I"), ("padding12", "I"), ("padding13", "I"),
    ("padding14", "I"), ("padding15", "I"), ("padding16", "I"),
]
_HEADER_FMT = "<" + "".join(f for _, f in _HEADER_FIELDS)
HEADER_SIZE = struct.calcsize(_HEADER_FMT)
assert HEADER_SIZE == 216, HEADER_SIZE

_PREVIEW_FMT = "<8I"   # res_x, res_y, offset, length, unknown1..4
_LAYERDEF_FMT = "<3f6I"  # pos_z, exposure, light_off, addr, size, page, unk2..4
LAYERDEF_SIZE = struct.calcsize(_LAYERDEF_FMT)
assert LAYERDEF_SIZE == 36


# ---------------------------------------------------------------- RLE de capa

def encode_layer_rle7(image, half_break=True):
    """Codifica una imagen de capa (numpy uint8, forma (alto, ancho)).

    Cada corrida empieza con un byte de color (bit alto puesto, gris de 7
    bits limitado a 0x7C) seguido de bytes de repetición <= 0x7D. Las
    corridas se cortan en la mitad de cada fila (comportamiento de ChiTuBox).
    """
    h, w = image.shape
    flat = image.reshape(-1)
    n = flat.size
    # límites de corrida: cambio de valor, inicio de fila o mitad de fila
    starts_mask = np.empty(n, dtype=bool)
    starts_mask[0] = True
    starts_mask[1:] = flat[1:] != flat[:-1]
    row_starts = np.arange(0, n, w)
    starts_mask[row_starts] = True
    if half_break:
        starts_mask[row_starts + w // 2] = True
    starts = np.flatnonzero(starts_mask)
    lengths = np.empty(starts.size, dtype=np.int64)
    lengths[:-1] = np.diff(starts)
    lengths[-1] = n - starts[-1]

    grey7 = (flat[starts] >> 1) & 0x7F
    np.minimum(grey7, 0x7C, out=grey7)
    color_bytes = grey7 | 0x80

    out = bytearray()
    append = out.append
    extend = out.extend
    full_chunk = b"\x7d"
    for color, run in zip(color_bytes.tolist(), lengths.tolist()):
        append(color)
        rest = run - 1
        if rest:
            n_full, rem = divmod(rest, 0x7D)
            if n_full:
                extend(full_chunk * n_full)
            if rem:
                append(rem)
    return bytes(out)


def decode_layer_rle7(data, width, height):
    """Decodifica el RLE de 7 bits a una imagen numpy uint8 (alto, ancho)."""
    out = np.zeros(width * height, dtype=np.uint8)
    idx = 0
    last = 0
    limit = out.size
    for code in data:
        if code & 0x80:
            last = ((code & 0x7F) << 1) | (code & 1)
            if last >= 0xFC:
                last = 0xFF
            if idx >= limit:
                raise ValueError("RLE corrupto (exceso de píxeles)")
            out[idx] = last
            idx += 1
        else:
            if idx + code > limit:
                raise ValueError("RLE corrupto (exceso de píxeles)")
            out[idx:idx + code] = last
            idx += code
    return out.reshape(height, width)


def layer_rle_crypt(seed, layer_index, data):
    """Cifra/descifra (XOR simétrico) los datos RLE de una capa."""
    if seed == 0:
        return bytes(data)
    seed %= 0x4324
    init = (seed * 0x34A32231) & 0xFFFFFFFF
    key = ((layer_index ^ 0x3FAD2212) * seed * 0x4910913D) & 0xFFFFFFFF
    out = bytearray(data)
    index = 0
    for i in range(len(out)):
        out[i] ^= (key >> (8 * index)) & 0xFF
        index += 1
        if index & 3 == 0:
            key = (key + init) & 0xFFFFFFFF
            index = 0
    return bytes(out)


# ------------------------------------------------------------ vistas previas

def encode_preview_rgb15(image_rgb):
    """Codifica una vista previa (numpy uint8 (alto, ancho, 3) RGB) a RLE RGB15.

    Pixel de 16 bits: bbbbb g:bit5=flag ggggg rrrrr — concretamente
    (b>>3) | ((g>>2)<<5) | ((r>>3)<<11); el bit 0x20 marca repetición y va
    seguido de un uint16 (count-1)|0x3000. Corridas máximas de 0xFFF.
    """
    REPEAT = 0x20
    LIMIT = 0xFFF
    h, w, _ = image_rgb.shape
    r = image_rgb[:, :, 0].astype(np.uint16)
    g = image_rgb[:, :, 1].astype(np.uint16)
    b = image_rgb[:, :, 2].astype(np.uint16)
    colors = ((b >> 3) | ((g >> 2) << 5) | ((r >> 3) << 11)).reshape(-1)

    out = bytearray()

    def emit(color, rep):
        if rep == 0:
            return
        if rep <= 2:
            c = color & ~REPEAT & 0xFFFF
            for _ in range(rep):
                out.append(c & 0xFF)
                out.append(c >> 8)
        else:
            c = (color | REPEAT) & 0xFFFF
            out.append(c & 0xFF)
            out.append(c >> 8)
            v = ((rep - 1) | 0x3000) & 0xFFFF
            out.append(v & 0xFF)
            out.append(v >> 8)

    color = 0
    rep = 0
    for ncolor in colors.tolist():
        if ncolor == color:
            rep += 1
            if rep == LIMIT:
                emit(color, rep)
                rep = 0
        else:
            emit(color, rep)
            color = ncolor
            rep = 1
    emit(color, rep)
    return bytes(out)


def decode_preview_rgb15(data, width, height):
    """Decodifica la vista previa a numpy uint8 (alto, ancho, 3) RGB."""
    REPEAT = 0x20
    out = np.zeros((width * height, 3), dtype=np.uint8)
    pixel = 0
    i = 0
    n = len(data)
    while i + 1 < n:
        dot = data[i] | (data[i + 1] << 8)
        i += 2
        red = ((dot >> 11) & 0x1F) << 3
        green = ((dot >> 6) & 0x1F) << 3
        blue = (dot & 0x1F) << 3
        rep = 1
        if dot & REPEAT:
            rep += data[i] | ((data[i + 1] & 0x0F) << 8)
            i += 2
        out[pixel:pixel + rep] = (red, green, blue)
        pixel += rep
    return out.reshape(height, width, 3)


# ------------------------------------------------------------------ escritor

class PhzWriter:
    """Escribe un archivo .phz capa a capa (sin retener todas en memoria)."""

    def __init__(self, path, settings):
        """settings: dict con los campos de la cabecera que interesan.

        Claves esperadas (con valores por defecto razonables):
        resolution_x, resolution_y, bed_size_x, bed_size_y, bed_size_z,
        layer_height_mm, exposure_s, bottom_exposure_s, bottom_layers,
        light_off_delay_s, bottom_light_off_delay_s, lift_height_mm,
        lift_speed_mmpm, bottom_lift_height_mm, bottom_lift_speed_mmpm,
        retract_speed_mmpm, light_pwm, bottom_light_pwm, projector_type,
        machine_name, layer_count, overall_height_mm, print_time_s,
        volume_ml, weight_g, cost, encryption_key
        """
        self.path = path
        self.s = dict(settings)
        self.f = open(path, "wb")
        self.f.write(b"\x00" * HEADER_SIZE)
        self._preview_small_offset = 0
        self._preview_large_offset = 0
        self._machine_name_offset = 0
        self._layerdefs_offset = 0
        self._layer_count = int(self.s["layer_count"])
        self._layers_written = 0
        self._layerdefs = []
        self._data_cursor = 0
        self._dedup = {}

    def write_previews(self, small_rgb, large_rgb):
        """small_rgb: numpy (125,200,3); large_rgb: numpy (300,400,3)."""
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

    def _write_machine_name(self):
        name = self.s.get("machine_name", "") or ""
        data = name.encode("ascii", "replace")
        self._machine_name_offset = self.f.tell() if data else 0
        self.f.write(data)
        self.s["machine_name_size"] = len(data)

    def begin_layers(self):
        self._write_machine_name()
        self._layerdefs_offset = self.f.tell()
        self.f.write(b"\x00" * (LAYERDEF_SIZE * self._layer_count))
        self._data_cursor = self.f.tell()

    def write_layer(self, image, position_z, exposure_s, light_off_s):
        """image: numpy uint8 (res_y, res_x), tal como debe verse en el LCD."""
        index = self._layers_written
        rle = encode_layer_rle7(image)
        key = int(self.s.get("encryption_key", 0))
        if key:
            rle = layer_rle_crypt(key, index, rle)
            digest = None
        else:
            digest = hashlib.sha1(rle).digest()

        if digest is not None and digest in self._dedup:
            addr, size, page = self._dedup[digest]
        else:
            page, addr = divmod(self._data_cursor, PAGE_SIZE)
            self.f.seek(self._data_cursor)
            self.f.write(rle)
            size = len(rle)
            self._data_cursor += size
            if digest is not None:
                self._dedup[digest] = (addr, size, page)

        self._layerdefs.append(struct.pack(
            _LAYERDEF_FMT, position_z, exposure_s, light_off_s,
            addr, size, page, 0, 0, 0))
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
            "magic": MAGIC_PHZ, "version": 2,
            "layer_height_mm": s["layer_height_mm"],
            "exposure_s": s["exposure_s"],
            "bottom_exposure_s": s["bottom_exposure_s"],
            "bottom_layers": s["bottom_layers"],
            "resolution_x": s["resolution_x"], "resolution_y": s["resolution_y"],
            "preview_large_offset": self._preview_large_offset,
            "layers_definition_offset": self._layerdefs_offset,
            "layer_count": self._layer_count,
            "preview_small_offset": self._preview_small_offset,
            "print_time_s": int(s.get("print_time_s", 0)),
            "projector_type": s.get("projector_type", 1),
            "antialias_level": 1,
            "light_pwm": s.get("light_pwm", 255),
            "bottom_light_pwm": s.get("bottom_light_pwm", 255),
            "overall_height_mm": s.get("overall_height_mm", 0.0),
            "bed_size_x": s["bed_size_x"], "bed_size_y": s["bed_size_y"],
            "bed_size_z": s["bed_size_z"],
            "encryption_key": s.get("encryption_key", 0),
            "bottom_light_off_delay_s": s.get("bottom_light_off_delay_s", 1.0),
            "light_off_delay_s": s.get("light_off_delay_s", 1.0),
            "bottom_layers2": s["bottom_layers"],
            "bottom_lift_height_mm": s.get("bottom_lift_height_mm", 5.0),
            "bottom_lift_speed_mmpm": s.get("bottom_lift_speed_mmpm", 65.0),
            "lift_height_mm": s.get("lift_height_mm", 5.0),
            "lift_speed_mmpm": s.get("lift_speed_mmpm", 65.0),
            "retract_speed_mmpm": s.get("retract_speed_mmpm", 150.0),
            "volume_ml": s.get("volume_ml", 0.0),
            "weight_g": s.get("weight_g", 0.0),
            "cost": s.get("cost", 0.0),
            "machine_name_offset": self._machine_name_offset,
            "machine_name_size": s.get("machine_name_size", 0),
            "encryption_mode": 0x1C,
            "modified_timestamp_min": int(time.time() // 60),
            "antialias_level_info": 1,
            "software_version": 0x01060300,
        }
        packed = struct.pack(
            _HEADER_FMT, *[values.get(name, 0) for name, _ in _HEADER_FIELDS])
        self.f.seek(0)
        self.f.write(packed)
        self.f.close()


# --------------------------------------------------------------------- lector

class PhzReader:
    """Lector de .phz para verificación y para reabrir archivos propios."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            data = f.read()
        self.raw = data
        vals = struct.unpack_from(_HEADER_FMT, data, 0)
        self.header = {name: v for (name, _), v in zip(_HEADER_FIELDS, vals)}
        if self.header["magic"] != MAGIC_PHZ:
            raise ValueError("No es un archivo PHZ válido")
        self.machine_name = ""
        off, size = self.header["machine_name_offset"], self.header["machine_name_size"]
        if off and size:
            self.machine_name = data[off:off + size].decode("ascii", "replace")
        self.layerdefs = []
        off = self.header["layers_definition_offset"]
        for i in range(self.header["layer_count"]):
            vals = struct.unpack_from(_LAYERDEF_FMT, data, off + i * LAYERDEF_SIZE)
            self.layerdefs.append({
                "position_z": vals[0], "exposure_s": vals[1],
                "light_off_s": vals[2], "addr": vals[3], "size": vals[4],
                "page": vals[5],
            })

    def read_layer(self, index):
        ld = self.layerdefs[index]
        start = ld["page"] * PAGE_SIZE + ld["addr"]
        blob = self.raw[start:start + ld["size"]]
        key = self.header["encryption_key"]
        if key:
            blob = layer_rle_crypt(key, index, blob)
        return decode_layer_rle7(
            blob, self.header["resolution_x"], self.header["resolution_y"])

    def read_preview(self, which="large"):
        off = self.header[f"preview_{which}_offset"]
        if not off:
            return None
        rx, ry, img_off, img_len, *_ = struct.unpack_from(_PREVIEW_FMT, self.raw, off)
        return decode_preview_rgb15(self.raw[img_off:img_off + img_len], rx, ry)
