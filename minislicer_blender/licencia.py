# -*- coding: utf-8 -*-
"""Activación de licencia contra la tienda del add-on.

La clave de licencia es el token de descarga que recibe el comprador
tras pagar. Se valida en línea una vez (botón «Activar») y después
se re-verifica en silencio como máximo una vez cada 30 días; si no hay
conexión en ese momento, el add-on sigue funcionando (período de gracia)
y lo vuelve a intentar al día siguiente.
"""

import json
import re
import time
import urllib.error
import urllib.request

# Actualizar cuando la tienda tenga dominio definitivo.
STORE_URL = "https://addon-store.vercel.app"
VERIFY_PATH = "/api/license/verify"

RECHECK_S = 30 * 24 * 3600  # re-verificación silenciosa: 30 días
GRACIA_S = 24 * 3600        # sin conexión: reintentar en 1 día

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def clave_valida_en_forma(clave):
    """Chequeo local de formato antes de molestar al servidor."""
    return bool(_UUID_RE.match(clave.strip()))


def verificar(clave, timeout=6.0):
    """Consulta la tienda.

    Devuelve (estado, mensaje):
      True  -> compra confirmada
      False -> clave rechazada por la tienda
      None  -> no se pudo consultar (sin red / tienda caída): indeterminado
    """
    datos = json.dumps({"key": clave.strip()}).encode("utf-8")
    req = urllib.request.Request(
        STORE_URL + VERIFY_PATH,
        data=datos,
        headers={"Content-Type": "application/json",
                 "User-Agent": "MiniSlicer-Blender"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cuerpo = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 503:
            return None, "La tienda no está disponible en este momento"
        return False, f"Respuesta inesperada de la tienda ({exc.code})"
    except Exception as exc:  # noqa: BLE001 — sin red, DNS, timeout…
        return None, f"Sin conexión con la tienda ({exc.__class__.__name__})"

    if cuerpo.get("valid"):
        return True, cuerpo.get("email", "")
    return False, "Clave no válida o compra no encontrada"


def licencia_ok(prefs):
    """Puerta usada por los operadores. Nunca bloquea por falta de red.

    `prefs` son las AddonPreferences (activated, license_key, last_check).
    """
    if not prefs.activated:
        return False
    ahora = time.time()
    if ahora - prefs.last_check < RECHECK_S:
        return True
    estado, _ = verificar(prefs.license_key, timeout=3.0)
    if estado is True:
        prefs.last_check = ahora
        return True
    if estado is None:
        # sin conexión: gracia de un día antes de reintentar
        prefs.last_check = ahora - RECHECK_S + GRACIA_S
        return True
    # la tienda rechazó la clave explícitamente
    prefs.activated = False
    return False
