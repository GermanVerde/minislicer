# -*- coding: utf-8 -*-
"""Motor de laminado: transforma la malla y rasteriza capas por scanline.

El relleno usa la regla par-impar sobre los cruces de los segmentos del
contorno con el centro de cada fila de píxeles, así que las cavidades y
agujeros de mallas cerradas salen bien sin ensamblar polígonos.
"""

import math

import numpy as np

# Perfil por defecto: Phrozen Sonic Mini (LCD 1080x1920, lcd_mirror, .phz)
SONIC_MINI = {
    "name": "Phrozen Sonic Mini",
    "resolution_x": 1080,
    "resolution_y": 1920,
    "bed_x": 67.8,   # mm
    "bed_y": 120.0,  # mm
    "bed_z": 130.0,  # mm
}

DEFAULT_PRINT = {
    "layer_height_mm": 0.05,
    "exposure_s": 2.5,
    "bottom_exposure_s": 35.0,
    "bottom_layers": 5,
    "light_off_delay_s": 1.0,
    "bottom_light_off_delay_s": 1.0,
    "lift_height_mm": 5.0,
    "lift_speed_mmpm": 65.0,
    "bottom_lift_height_mm": 5.0,
    "bottom_lift_speed_mmpm": 65.0,
    "retract_speed_mmpm": 150.0,
    "mirror_x": True,
}


def transform_mesh(tris, scale=1.0, rot_z_deg=0.0):
    """Escala, rota alrededor de Z, centra en XY y apoya la pieza en Z=0."""
    t = tris * float(scale)
    if rot_z_deg % 360:
        a = math.radians(rot_z_deg)
        c, s = math.cos(a), math.sin(a)
        x = t[:, :, 0].copy()
        y = t[:, :, 1].copy()
        t[:, :, 0] = c * x - s * y
        t[:, :, 1] = s * x + c * y
    mins = t.reshape(-1, 3).min(axis=0)
    maxs = t.reshape(-1, 3).max(axis=0)
    center = (mins + maxs) / 2.0
    t[:, :, 0] -= center[0]
    t[:, :, 1] -= center[1]
    t[:, :, 2] -= mins[2]
    return t


def mesh_size(tris):
    mins = tris.reshape(-1, 3).min(axis=0)
    maxs = tris.reshape(-1, 3).max(axis=0)
    return maxs - mins


def fits_on_bed(tris, profile):
    size = mesh_size(tris)
    return (size[0] <= profile["bed_x"] + 1e-6 and
            size[1] <= profile["bed_y"] + 1e-6 and
            size[2] <= profile["bed_z"] + 1e-6)


def _cross_segments(tris, z):
    """Segmentos (K,2,2) de la intersección malla∩plano z (coordenadas mm)."""
    tz = tris[:, :, 2]
    zmin = tz.min(axis=1)
    zmax = tz.max(axis=1)
    sel = (zmin <= z) & (zmax > z)
    t = tris[sel]
    if not len(t):
        return np.zeros((0, 2, 2))

    a = t  # vértices 0,1,2
    b = t[:, [1, 2, 0], :]  # vértices 1,2,0
    za = a[:, :, 2]
    zb = b[:, :, 2]
    below_a = za <= z
    below_b = zb <= z
    crossing = below_a != below_b  # (M,3), 2 verdaderos por triángulo

    good = crossing.sum(axis=1) == 2
    a, b, za, zb, crossing = a[good], b[good], za[good], zb[good], crossing[good]
    if not len(a):
        return np.zeros((0, 2, 2))

    with np.errstate(divide="ignore", invalid="ignore"):
        # las divisiones por cero caen en bordes que no cruzan (mask False)
        frac = (z - za) / (zb - za)
        px = a[:, :, 0] + frac * (b[:, :, 0] - a[:, :, 0])
        py = a[:, :, 1] + frac * (b[:, :, 1] - a[:, :, 1])
    m = len(a)
    segs = np.empty((m, 2, 2))
    pts_x = px[crossing].reshape(m, 2)
    pts_y = py[crossing].reshape(m, 2)
    segs[:, :, 0] = pts_x
    segs[:, :, 1] = pts_y
    return segs


def slice_layer(tris, z, profile):
    """Rasteriza el corte a la altura z (mm) → numpy uint8 (res_y, res_x)."""
    w = int(profile["resolution_x"])
    h = int(profile["resolution_y"])
    pitch_x = profile["bed_x"] / w
    pitch_y = profile["bed_y"] / h

    # evita cortar exactamente por un vértice
    guard = 0
    while guard < 8 and np.any(np.abs(tris[:, :, 2] - z) < 1e-12):
        z += 3.7e-8
        guard += 1

    segs = _cross_segments(tris, z)
    img = np.zeros((h, w), dtype=np.uint8)
    if not len(segs):
        return img

    # a coordenadas de píxel (origen: esquina de la placa)
    sx = (segs[:, :, 0] + profile["bed_x"] / 2.0) / pitch_x
    sy = (segs[:, :, 1] + profile["bed_y"] / 2.0) / pitch_y

    y0 = sy.min(axis=1)
    y1 = sy.max(axis=1)
    swap = sy[:, 0] > sy[:, 1]
    x_low = np.where(swap, sx[:, 1], sx[:, 0])
    x_high = np.where(swap, sx[:, 0], sx[:, 1])

    keep = y1 - y0 > 1e-12  # descarta segmentos horizontales
    y0, y1, x_low, x_high = y0[keep], y1[keep], x_low[keep], x_high[keep]
    if not len(y0):
        return img

    r_start = np.clip(np.ceil(y0 - 0.5), 0, h).astype(np.int64)
    r_end = np.clip(np.ceil(y1 - 0.5), 0, h).astype(np.int64)
    counts = r_end - r_start
    valid = counts > 0
    y0, y1, x_low, x_high = y0[valid], y1[valid], x_low[valid], x_high[valid]
    r_start, counts = r_start[valid], counts[valid]
    if not len(counts):
        return img

    total = int(counts.sum())
    seg_idx = np.repeat(np.arange(len(counts)), counts)
    offs = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
    rows = r_start[seg_idx] + offs
    yc = rows + 0.5
    slope = (x_high - x_low) / (y1 - y0)
    xs = x_low[seg_idx] + (yc - y0[seg_idx]) * slope[seg_idx]

    order = np.lexsort((xs, rows))
    rows = rows[order]
    xs = xs[order]

    # posición de cada cruce dentro de su fila (para emparejar entrada/salida)
    row_counts = np.bincount(rows, minlength=h)
    row_first = np.concatenate(([0], np.cumsum(row_counts)))[:-1]
    pos_in_row = np.arange(total) - row_first[rows]
    is_enter = (pos_in_row % 2) == 0
    # si una fila quedó con nº impar de cruces, descarta el último
    odd_rows = (row_counts % 2) == 1
    drop = odd_rows[rows] & (pos_in_row == row_counts[rows] - 1)
    is_enter &= ~drop

    enter_rows = rows[is_enter]
    enter_x = xs[is_enter]
    exit_x = xs[np.flatnonzero(is_enter) + 1]

    c_start = np.clip(np.ceil(enter_x - 0.5), 0, w).astype(np.int64)
    c_end = np.clip(np.ceil(exit_x - 0.5), 0, w).astype(np.int64)
    ok = c_end > c_start
    if not ok.any():
        return img

    diff = np.zeros((h, w + 1), dtype=np.int32)
    np.add.at(diff, (enter_rows[ok], c_start[ok]), 1)
    np.add.at(diff, (enter_rows[ok], c_end[ok]), -1)
    acc = np.cumsum(diff[:, :w], axis=1)
    img[acc > 0] = 255
    return img


def layer_count(tris, layer_height):
    height = float(tris[:, :, 2].max())
    return max(1, int(math.ceil(round(height / layer_height, 6))))


def estimate_print_time(n_layers, params):
    p = params
    normal = max(0, n_layers - int(p["bottom_layers"]))
    bottom = min(n_layers, int(p["bottom_layers"]))

    def motion(lift, lift_speed, retract_speed):
        return (lift / max(lift_speed, 1e-6)) * 60 + (lift / max(retract_speed, 1e-6)) * 60

    t = bottom * (p["bottom_exposure_s"] + p["bottom_light_off_delay_s"] +
                  motion(p["bottom_lift_height_mm"], p["bottom_lift_speed_mmpm"],
                         p["retract_speed_mmpm"]))
    t += normal * (p["exposure_s"] + p["light_off_delay_s"] +
                   motion(p["lift_height_mm"], p["lift_speed_mmpm"],
                          p["retract_speed_mmpm"]))
    return t
