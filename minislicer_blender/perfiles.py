# -*- coding: utf-8 -*-
"""Perfiles de impresoras Phrozen.

Cada perfil define la resolución del LCD, el volumen de impresión en mm y el
formato de archivo nativo. Los valores provienen de las especificaciones
publicadas por Phrozen. `formato` decide qué writer usa la exportación:
"phz" y "ctb" están implementados; "prz" (modelos 2023+) aún no.
"""

# id → perfil. El id es estable (se guarda en la escena .blend).
PERFILES = {
    # --- generación .phz (ChiTu DLP clásico) ---
    "SONIC_MINI": {
        "name": "Phrozen Sonic Mini",
        "resolution_x": 1080, "resolution_y": 1920,
        "bed_x": 67.8, "bed_y": 120.0, "bed_z": 130.0,
        "formato": "phz",
    },
    "SONIC": {
        "name": "Phrozen Sonic",
        "resolution_x": 1080, "resolution_y": 1920,
        "bed_x": 67.8, "bed_y": 120.0, "bed_z": 170.0,
        "formato": "phz",
    },
    "TRANSFORM": {
        "name": "Phrozen Transform",
        "resolution_x": 3840, "resolution_y": 2160,
        "bed_x": 291.8, "bed_y": 164.2, "bed_z": 400.0,
        "formato": "phz",
    },
    # --- generación .ctb ---
    "SONIC_MINI_4K": {
        "name": "Phrozen Sonic Mini 4K",
        "resolution_x": 3840, "resolution_y": 2160,
        "bed_x": 134.4, "bed_y": 75.6, "bed_z": 130.0,
        "formato": "ctb",
    },
    "SONIC_MINI_8K": {
        "name": "Phrozen Sonic Mini 8K",
        "resolution_x": 7500, "resolution_y": 3240,
        "bed_x": 165.0, "bed_y": 71.3, "bed_z": 180.0,
        "formato": "ctb",
    },
    "SONIC_4K": {
        "name": "Phrozen Sonic 4K",
        "resolution_x": 3840, "resolution_y": 2160,
        "bed_x": 134.4, "bed_y": 75.6, "bed_z": 200.0,
        "formato": "ctb",
    },
    "SONIC_XL_4K": {
        "name": "Phrozen Sonic XL 4K",
        "resolution_x": 3840, "resolution_y": 2400,
        "bed_x": 192.0, "bed_y": 120.0, "bed_z": 200.0,
        "formato": "ctb",
    },
    "SONIC_MIGHTY_4K": {
        "name": "Phrozen Sonic Mighty 4K",
        "resolution_x": 3840, "resolution_y": 2400,
        "bed_x": 200.0, "bed_y": 125.0, "bed_z": 220.0,
        "formato": "ctb",
    },
    "SONIC_MIGHTY_8K": {
        "name": "Phrozen Sonic Mighty 8K",
        "resolution_x": 7680, "resolution_y": 4320,
        "bed_x": 218.0, "bed_y": 123.0, "bed_z": 235.0,
        "formato": "ctb",
    },
    "SONIC_MEGA_8K": {
        "name": "Phrozen Sonic Mega 8K",
        "resolution_x": 7680, "resolution_y": 4320,
        "bed_x": 330.0, "bed_y": 185.0, "bed_z": 400.0,
        "formato": "ctb",
    },
    # --- generación .prz (aún sin writer) ---
    "SONIC_MINI_8K_S": {
        "name": "Phrozen Sonic Mini 8K S",
        "resolution_x": 7536, "resolution_y": 3240,
        "bed_x": 165.8, "bed_y": 71.3, "bed_z": 170.0,
        "formato": "prz",
    },
    "SONIC_MIGHTY_12K": {
        "name": "Phrozen Sonic Mighty 12K",
        "resolution_x": 11520, "resolution_y": 5120,
        "bed_x": 218.9, "bed_y": 123.1, "bed_z": 235.0,
        "formato": "prz",
    },
    "SONIC_MEGA_8K_S": {
        "name": "Phrozen Sonic Mega 8K S",
        "resolution_x": 7680, "resolution_y": 4320,
        "bed_x": 330.0, "bed_y": 185.0, "bed_z": 300.0,
        "formato": "prz",
    },
}

FORMATOS_SOPORTADOS = ("phz", "ctb")

# El orden del desplegable: primero la familia clásica, luego por tamaño.
ORDEN = [
    "SONIC_MINI", "SONIC", "TRANSFORM",
    "SONIC_MINI_4K", "SONIC_MINI_8K", "SONIC_4K", "SONIC_XL_4K",
    "SONIC_MIGHTY_4K", "SONIC_MIGHTY_8K", "SONIC_MEGA_8K",
    "SONIC_MINI_8K_S", "SONIC_MIGHTY_12K", "SONIC_MEGA_8K_S",
]


def perfil(clave):
    return PERFILES.get(clave, PERFILES["SONIC_MINI"])


def items_enum():
    """Items para el EnumProperty del panel."""
    out = []
    for clave in ORDEN:
        p = PERFILES[clave]
        etiqueta = p["name"].replace("Phrozen ", "")
        extra = "" if p["formato"] in FORMATOS_SOPORTADOS else " (soon)"
        out.append((clave, f"{etiqueta} — .{p['formato']}{extra}",
                    f"{p['resolution_x']}×{p['resolution_y']} px, "
                    f"{p['bed_x']:g}×{p['bed_y']:g}×{p['bed_z']:g} mm"))
    return out


def pitch_mm(p):
    """Tamaño de píxel (x, y) en mm."""
    return p["bed_x"] / p["resolution_x"], p["bed_y"] / p["resolution_y"]
