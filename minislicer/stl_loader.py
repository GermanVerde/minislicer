# -*- coding: utf-8 -*-
"""Carga de mallas STL (binario y ASCII) y OBJ a numpy (N, 3, 3) float64."""

import os
import struct

import numpy as np


def load_mesh(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        return _load_obj(path)
    if ext == ".stl":
        return _load_stl(path)
    raise ValueError(f"Formato no soportado: {ext} (usa STL u OBJ)")


def _load_stl(path):
    with open(path, "rb") as f:
        header = f.read(84)
        if len(header) < 84:
            return _load_stl_ascii(path)
        n_tris = struct.unpack_from("<I", header, 80)[0]
        expected = 84 + n_tris * 50
        size = os.path.getsize(path)
        # Un STL ASCII empieza con "solid", pero algunos binarios también:
        # decide por el tamaño esperado.
        if header[:5].lower() == b"solid" and size != expected:
            return _load_stl_ascii(path)
        data = np.fromfile(f, dtype=np.uint8, count=n_tris * 50)
    if data.size < n_tris * 50:
        raise ValueError("STL binario truncado")
    records = data.reshape(n_tris, 50)
    floats = records[:, 0:48].copy().view("<f4").reshape(n_tris, 12)
    tris = floats[:, 3:12].reshape(n_tris, 3, 3).astype(np.float64)
    return tris


def _load_stl_ascii(path):
    verts = []
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("vertex"):
                parts = line.split()
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    if not verts or len(verts) % 3:
        raise ValueError("STL ASCII inválido")
    return np.array(verts, dtype=np.float64).reshape(-1, 3, 3)


def _load_obj(path):
    verts = []
    faces = []
    with open(path, "r", errors="replace") as f:
        for line in f:
            if line.startswith("v "):
                p = line.split()
                verts.append((float(p[1]), float(p[2]), float(p[3])))
            elif line.startswith("f "):
                idx = []
                for token in line.split()[1:]:
                    i = token.split("/")[0]
                    i = int(i)
                    idx.append(i - 1 if i > 0 else len(verts) + i)
                for k in range(1, len(idx) - 1):  # triangulación en abanico
                    faces.append((idx[0], idx[k], idx[k + 1]))
    if not faces:
        raise ValueError("OBJ sin caras")
    v = np.array(verts, dtype=np.float64)
    f_arr = np.array(faces, dtype=np.int64)
    return v[f_arr]
