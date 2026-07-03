# -*- coding: utf-8 -*-
"""Render 3D simple (algoritmo del pintor) usando solo PIL + numpy.

Sirve tanto para la vista interactiva de la GUI como para generar las
miniaturas que la impresora muestra en su pantalla.
"""

import math

import numpy as np
from PIL import Image, ImageDraw

BG = (24, 27, 34)
PLATE = (70, 110, 160)
BASE_COLOR = np.array([90, 160, 235], dtype=np.float64)


def _rot_matrix(yaw_deg, elev_deg):
    a = math.radians(yaw_deg)
    b = math.radians(elev_deg)
    rz = np.array([[math.cos(a), -math.sin(a), 0],
                   [math.sin(a), math.cos(a), 0],
                   [0, 0, 1]])
    rx = np.array([[1, 0, 0],
                   [0, math.cos(b), -math.sin(b)],
                   [0, math.sin(b), math.cos(b)]])
    return rx @ rz


def render_mesh(tris, size=(520, 520), yaw=35.0, elev=-65.0,
                profile=None, max_tris=45000, bg=BG):
    """tris: numpy (N,3,3) ya transformada (centrada, apoyada en Z=0)."""
    w, h = size
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)

    if tris is None or not len(tris):
        return img

    t = tris
    if len(t) > max_tris:
        t = t[:: len(t) // max_tris + 1]

    rot = _rot_matrix(yaw, elev)
    pts = t.reshape(-1, 3) @ rot.T
    pts = pts.reshape(-1, 3, 3)

    # también proyecta la placa de impresión si hay perfil
    plate = None
    if profile:
        bx, by = profile["bed_x"] / 2.0, profile["bed_y"] / 2.0
        corners = np.array([[-bx, -by, 0], [bx, -by, 0],
                            [bx, by, 0], [-bx, by, 0]]) @ rot.T
        plate = corners

    u = pts[:, :, 0]
    v = -pts[:, :, 2]
    depth = pts[:, :, 1]

    all_u = u.reshape(-1)
    all_v = v.reshape(-1)
    if plate is not None:
        all_u = np.concatenate([all_u, plate[:, 0]])
        all_v = np.concatenate([all_v, -plate[:, 2]])
    umin, umax = all_u.min(), all_u.max()
    vmin, vmax = all_v.min(), all_v.max()
    span = max(umax - umin, vmax - vmin, 1e-9)
    scale = 0.85 * min(w, h) / span
    cx = (umin + umax) / 2.0
    cy = (vmin + vmax) / 2.0

    def to_screen_arr(uu, vv):
        return (uu - cx) * scale + w / 2.0, (vv - cy) * scale + h / 2.0

    su, sv = to_screen_arr(u, v)

    # placa primero (queda detrás)
    if plate is not None:
        pu, pv = to_screen_arr(plate[:, 0], -plate[:, 2])
        draw.polygon(list(zip(pu, pv)), outline=PLATE,
                     fill=(BG[0] + 8, BG[1] + 10, BG[2] + 14))

    # sombreado plano por normal
    e1 = pts[:, 1] - pts[:, 0]
    e2 = pts[:, 2] - pts[:, 0]
    normals = np.cross(e1, e2)
    norm = np.linalg.norm(normals, axis=1)
    norm[norm == 0] = 1
    normals /= norm[:, None]
    light = np.array([0.35, -0.65, 0.67])
    light /= np.linalg.norm(light)
    shade = np.clip(normals @ light, 0.0, 1.0) * 0.75 + 0.25

    # descarta caras traseras (normal apuntando lejos de la cámara: +y)
    front = normals[:, 1] < 0.15
    order = np.argsort(-depth.mean(axis=1))
    order = order[front[order]]

    colors = np.clip(BASE_COLOR[None, :] * shade[:, None], 0, 255).astype(np.uint8)
    for i in order.tolist():
        draw.polygon(
            [(su[i, 0], sv[i, 0]), (su[i, 1], sv[i, 1]), (su[i, 2], sv[i, 2])],
            fill=tuple(colors[i]))

    return img


def render_thumbnails(tris, profile):
    """Devuelve (pequeña 200x125, grande 400x300) como arrays RGB uint8."""
    large = render_mesh(tris, size=(400, 300), profile=profile)
    small = large.resize((200, 125), Image.LANCZOS)
    return np.asarray(small, dtype=np.uint8), np.asarray(large, dtype=np.uint8)
