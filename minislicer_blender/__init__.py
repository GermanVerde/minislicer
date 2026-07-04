# -*- coding: utf-8 -*-
"""MiniSlicer para Blender — lamina el objeto activo y exporta .phz
para la Phrozen Sonic Mini, con visor de capas integrado.

Panel: barra lateral (tecla N) del viewport 3D, pestaña «MiniSlicer».
"""

import os
import time

import bpy
import numpy as np
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup
from bpy_extras.io_utils import ExportHelper

from . import licencia, phz, slicer

IMG_NAME = "MiniSlicer_Capa"

# caché del último objeto preparado (triángulos ya en mm, centrados)
_cache = {"tris": None, "obj": "", "sig": None}


# ------------------------------------------------------------- geometría

def _mm_factor(context, props):
    if props.units == "MM":
        base = 1.0
    else:
        base = context.scene.unit_settings.scale_length * 1000.0
    return base * props.scale_pct / 100.0


def _gather_tris(context, ob, props):
    """Extrae los triángulos del objeto evaluado (modificadores incluidos),
    en milímetros, centrados en la placa y apoyados en Z=0."""
    if ob is None or ob.type != "MESH":
        raise ValueError("Selecciona un objeto de tipo malla")
    deps = context.evaluated_depsgraph_get()
    ob_eval = ob.evaluated_get(deps)
    me = ob_eval.to_mesh()
    try:
        me.calc_loop_triangles()
        nv = len(me.vertices)
        nt = len(me.loop_triangles)
        if nt == 0:
            raise ValueError("La malla no tiene caras")
        co = np.empty(nv * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        idx = np.empty(nt * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("vertices", idx)
    finally:
        ob_eval.to_mesh_clear()

    m = np.array(ob.matrix_world, dtype=np.float64)
    co = co.astype(np.float64).reshape(-1, 3)
    co = co @ m[:3, :3].T + m[:3, 3]
    tris = co[idx.reshape(-1, 3).astype(np.int64)]
    tris *= _mm_factor(context, props)
    return slicer.transform_mesh(tris, scale=1.0, rot_z_deg=0.0)


def _signature(context, ob, props):
    return (ob.name if ob else "", tuple(np.array(ob.matrix_world).ravel())
            if ob else (), props.units, round(props.scale_pct, 3))


def _params_from_props(p):
    return {
        "layer_height_mm": p.layer_height,
        "exposure_s": p.exposure,
        "bottom_exposure_s": p.bottom_exposure,
        "bottom_layers": p.bottom_layers,
        "light_off_delay_s": p.light_off,
        "bottom_light_off_delay_s": p.bottom_light_off,
        "lift_height_mm": p.lift_height,
        "lift_speed_mmpm": p.lift_speed,
        "bottom_lift_height_mm": p.bottom_lift_height,
        "bottom_lift_speed_mmpm": p.bottom_lift_speed,
        "retract_speed_mmpm": p.retract_speed,
        "mirror_x": p.mirror_x,
    }


# --------------------------------------------------------- visor de capas

def _ensure_image(w, h):
    img = bpy.data.images.get(IMG_NAME)
    if img is None:
        img = bpy.data.images.new(IMG_NAME, width=w, height=h, alpha=False)
        img.colorspace_settings.name = "Non-Color"
    elif tuple(img.size) != (w, h):
        img.scale(w, h)
    return img


def _update_layer_image(context):
    tris = _cache["tris"]
    if tris is None:
        return
    p = context.scene.minislicer
    profile = slicer.SONIC_MINI
    n = slicer.layer_count(tris, p.layer_height)
    index = min(max(p.layer_index, 1), n)
    z = (index - 0.5) * p.layer_height
    arr = slicer.slice_layer(tris, z, profile)  # (1920, 1080), fila 0 = abajo
    h, w = arr.shape
    img = _ensure_image(w, h)
    rgba = np.empty((h, w, 4), dtype=np.float32)
    v = arr.astype(np.float32) / 255.0
    rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = v
    rgba[..., 3] = 1.0
    img.pixels.foreach_set(rgba.ravel())
    img.update()
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "IMAGE_EDITOR":
                area.tag_redraw()


def _on_layer_index(self, context):
    if _cache["tris"] is not None:
        _update_layer_image(context)


# ------------------------------------------------------------- miniaturas

def _nearest_resize(arr, new_h, new_w):
    h, w = arr.shape[:2]
    yi = (np.arange(new_h) * h / new_h).astype(np.int64)
    xi = (np.arange(new_w) * w / new_w).astype(np.int64)
    return arr[yi][:, xi]


def _thumbnails(tris, n_layers, layer_height):
    """Miniaturas para la pantalla de la impresora: mapa de alturas cenital."""
    prof = dict(slicer.SONIC_MINI)
    prof["resolution_x"] = 216
    prof["resolution_y"] = 384
    hm = np.zeros((384, 216), dtype=np.float32)
    samples = min(48, n_layers)
    for k in range(samples):
        i = int((k + 0.5) * n_layers / samples)
        z = (i + 0.5) * layer_height
        sl = slicer.slice_layer(tris, z, prof)
        level = (i + 1) / n_layers
        hm[(sl > 0) & (hm < level)] = level

    # apaisado para la pantalla (rota 90°)
    hm = hm.T[::-1]
    bg = np.array([24, 27, 34], dtype=np.float32)
    tone = np.array([90, 160, 235], dtype=np.float32)

    def compose(hh, ww):
        sc = min(ww / hm.shape[1], hh / hm.shape[0])
        rh, rw = max(1, int(hm.shape[0] * sc)), max(1, int(hm.shape[1] * sc))
        small = _nearest_resize(hm, rh, rw)
        canvas = np.empty((hh, ww, 3), dtype=np.float32)
        canvas[:] = bg
        y0 = (hh - rh) // 2
        x0 = (ww - rw) // 2
        region = canvas[y0:y0 + rh, x0:x0 + rw]
        mask = small > 0
        shade = (0.35 + 0.65 * small[mask])[:, None] * tone[None, :]
        region[mask] = shade
        return np.clip(canvas, 0, 255).astype(np.uint8)

    return compose(125, 200), compose(300, 400)


# ------------------------------------------------------------ exportación

def _prepare_export(context, filepath):
    p = context.scene.minislicer
    ob = context.active_object
    tris = _gather_tris(context, ob, p)
    _cache.update(tris=tris, obj=ob.name, sig=_signature(context, ob, p))

    params = _params_from_props(p)
    profile = slicer.SONIC_MINI
    lh = params["layer_height_mm"]
    n = slicer.layer_count(tris, lh)
    fits = slicer.fits_on_bed(tris, profile)
    print_time = slicer.estimate_print_time(n, params)

    settings = {
        "resolution_x": profile["resolution_x"],
        "resolution_y": profile["resolution_y"],
        "bed_size_x": profile["bed_x"],
        "bed_size_y": profile["bed_y"],
        "bed_size_z": profile["bed_z"],
        "layer_height_mm": lh,
        "exposure_s": params["exposure_s"],
        "bottom_exposure_s": params["bottom_exposure_s"],
        "bottom_layers": int(params["bottom_layers"]),
        "light_off_delay_s": params["light_off_delay_s"],
        "bottom_light_off_delay_s": params["bottom_light_off_delay_s"],
        "lift_height_mm": params["lift_height_mm"],
        "lift_speed_mmpm": params["lift_speed_mmpm"],
        "bottom_lift_height_mm": params["bottom_lift_height_mm"],
        "bottom_lift_speed_mmpm": params["bottom_lift_speed_mmpm"],
        "retract_speed_mmpm": params["retract_speed_mmpm"],
        "projector_type": 1 if params["mirror_x"] else 0,
        "machine_name": profile["name"],
        "layer_count": n,
        "overall_height_mm": n * lh,
        "print_time_s": int(print_time),
        "encryption_key": 0,
    }
    writer = phz.PhzWriter(filepath, settings)
    small, large = _thumbnails(tris, n, lh)
    writer.write_previews(small, large)
    writer.begin_layers()

    return {
        "writer": writer, "tris": tris, "params": params, "profile": profile,
        "n": n, "i": 0, "filled": 0, "filepath": filepath, "fits": fits,
        "print_time": print_time,
    }


def _export_step(state, budget_s=0.15):
    """Lamina y escribe capas durante ~budget_s. Devuelve True al terminar."""
    t0 = time.monotonic()
    p = state["params"]
    profile = state["profile"]
    lh = p["layer_height_mm"]
    bottom = int(p["bottom_layers"])
    while state["i"] < state["n"]:
        i = state["i"]
        z = (i + 0.5) * lh
        img = slicer.slice_layer(state["tris"], z, profile)
        state["filled"] += int(np.count_nonzero(img))
        if p["mirror_x"]:
            img = np.ascontiguousarray(np.fliplr(img))
        if i < bottom:
            exp, off = p["bottom_exposure_s"], p["bottom_light_off_delay_s"]
        else:
            exp, off = p["exposure_s"], p["light_off_delay_s"]
        state["writer"].write_layer(img, (i + 1) * lh, exp, off)
        state["i"] += 1
        if time.monotonic() - t0 > budget_s:
            break
    return state["i"] >= state["n"]


def _finish_export(state):
    p = state["params"]
    profile = state["profile"]
    pitch_x = profile["bed_x"] / profile["resolution_x"]
    pitch_y = profile["bed_y"] / profile["resolution_y"]
    volume_ml = state["filled"] * pitch_x * pitch_y * p["layer_height_mm"] / 1000.0
    w = state["writer"]
    w.s["volume_ml"] = volume_ml
    w.s["weight_g"] = volume_ml * 1.1
    w.close()
    return volume_ml


def _abort_export(state):
    try:
        state["writer"].f.close()
    except Exception:
        pass
    try:
        os.remove(state["filepath"])
    except OSError:
        pass


# ------------------------------------------------------------- licencia

def _prefs(context):
    return context.preferences.addons[__package__].preferences


def _exigir_licencia(op, context):
    """True si se puede exportar; si no, reporta el error una sola vez."""
    if licencia.licencia_ok(_prefs(context)):
        return True
    op.report({"ERROR"},
              "MiniSlicer no está activado: ingresa tu clave de compra en "
              "Edit → Preferences → Add-ons → MiniSlicer")
    return False


class MiniSlicerPrefs(AddonPreferences):
    bl_idname = __package__

    license_key: StringProperty(
        name="Clave de licencia",
        description="La clave que recibiste en tu página de descarga "
                    "después de comprar")
    activated: BoolProperty(default=False)
    last_check: FloatProperty(default=0.0)
    status_msg: StringProperty(default="")

    def draw(self, context):
        layout = self.layout
        if self.activated:
            layout.label(text=self.status_msg or "Licencia activada",
                         icon="CHECKMARK")
        else:
            layout.label(text="Ingresa la clave de tu compra para "
                              "desbloquear la exportación .phz",
                         icon="KEY_HLT")
        row = layout.row(align=True)
        row.prop(self, "license_key", text="")
        row.operator("minislicer.activar",
                     icon="FILE_REFRESH" if self.activated else "UNLOCKED")
        if self.status_msg and not self.activated:
            layout.label(text=self.status_msg, icon="INFO")


class MINISLICER_OT_activar(Operator):
    bl_idname = "minislicer.activar"
    bl_label = "Activar"
    bl_description = "Comprueba la clave de compra contra la tienda"

    def execute(self, context):
        prefs = _prefs(context)
        clave = prefs.license_key.strip()
        if not licencia.clave_valida_en_forma(clave):
            prefs.status_msg = "El formato de la clave no es válido"
            self.report({"ERROR"}, prefs.status_msg)
            return {"CANCELLED"}
        estado, msg = licencia.verificar(clave)
        if estado is True:
            prefs.activated = True
            prefs.last_check = time.time()
            prefs.status_msg = (f"Activado — compra de {msg}"
                                if msg else "Activado")
            bpy.ops.wm.save_userpref()
            self.report({"INFO"}, "MiniSlicer activado. ¡Gracias por tu compra!")
            return {"FINISHED"}
        prefs.status_msg = msg
        if estado is None:
            self.report({"WARNING"}, msg)
        else:
            prefs.activated = False
            self.report({"ERROR"}, msg)
        return {"CANCELLED"}


# ------------------------------------------------------------- operadores

class MINISLICER_OT_actualizar(Operator):
    bl_idname = "minislicer.actualizar"
    bl_label = "Cargar / actualizar modelo"
    bl_description = ("Toma el objeto activo (con modificadores aplicados) "
                      "y lo prepara para laminar")

    def execute(self, context):
        p = context.scene.minislicer
        try:
            tris = _gather_tris(context, context.active_object, p)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        _cache.update(tris=tris, obj=context.active_object.name,
                      sig=_signature(context, context.active_object, p))
        n = slicer.layer_count(tris, p.layer_height)
        p.layer_index = min(max(p.layer_index, 1), n)
        _update_layer_image(context)
        size = slicer.mesh_size(tris)
        self.report({"INFO"},
                    f"{_cache['obj']}: {size[0]:.1f} × {size[1]:.1f} × "
                    f"{size[2]:.1f} mm, {n} capas")
        return {"FINISHED"}


class MINISLICER_OT_abrir_visor(Operator):
    bl_idname = "minislicer.abrir_visor"
    bl_label = "Abrir visor de capas"
    bl_description = "Abre una ventana con la imagen de la capa seleccionada"

    def execute(self, context):
        if _cache["tris"] is None:
            bpy.ops.minislicer.actualizar()
            if _cache["tris"] is None:
                return {"CANCELLED"}
        _update_layer_image(context)
        img = bpy.data.images.get(IMG_NAME)
        bpy.ops.wm.window_new()
        win = context.window_manager.windows[-1]
        area = win.screen.areas[0]
        area.type = "IMAGE_EDITOR"
        area.spaces.active.image = img
        return {"FINISHED"}


class MINISLICER_OT_exportar(Operator, ExportHelper):
    bl_idname = "minislicer.exportar"
    bl_label = "Exportar .phz"
    bl_description = "Lamina el objeto activo y guarda el archivo .phz"

    filename_ext = ".phz"
    filter_glob: StringProperty(default="*.phz", options={"HIDDEN"})

    _timer = None
    _state = None

    def invoke(self, context, event):
        if not _exigir_licencia(self, context):
            return {"CANCELLED"}
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        if not _exigir_licencia(self, context):
            return {"CANCELLED"}
        try:
            self._state = _prepare_export(context, self.filepath)
        except (ValueError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not self._state["fits"]:
            self.report({"WARNING"},
                        "El modelo no cabe en la placa: se recortará")
        wm = context.window_manager
        wm.progress_begin(0, self._state["n"])
        self._timer = wm.event_timer_add(0.02, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        st = self._state
        if event.type == "ESC":
            self._cleanup(context)
            _abort_export(st)
            self.report({"WARNING"}, "Exportación cancelada")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}

        try:
            done = _export_step(st)
        except Exception as exc:  # noqa: BLE001
            self._cleanup(context)
            _abort_export(st)
            self.report({"ERROR"}, f"Error al laminar: {exc}")
            return {"CANCELLED"}

        wm = context.window_manager
        wm.progress_update(st["i"])
        context.workspace.status_text_set(
            f"MiniSlicer: capa {st['i']}/{st['n']}  (Esc para cancelar)")

        if done:
            volume = _finish_export(st)
            self._cleanup(context)
            mins = int(st["print_time"] // 60)
            self.report({"INFO"},
                        f"Exportado: {os.path.basename(st['filepath'])} — "
                        f"{st['n']} capas, {volume:.1f} ml, "
                        f"{mins // 60} h {mins % 60:02d} min")
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _cleanup(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        context.workspace.status_text_set(None)


# ------------------------------------------------------------- propiedades

class MiniSlicerProps(PropertyGroup):
    layer_height: FloatProperty(
        name="Altura de capa (mm)", default=0.05, min=0.01, max=0.2, step=1,
        precision=3, description="Altura de cada capa en mm")
    exposure: FloatProperty(
        name="Exposición (s)", default=2.5, min=0.1, max=60.0, precision=2)
    bottom_layers: IntProperty(
        name="Capas base", default=5, min=0, max=20)
    bottom_exposure: FloatProperty(
        name="Exposición base (s)", default=35.0, min=1.0, max=180.0,
        precision=1)
    light_off: FloatProperty(
        name="Reposo sin luz (s)", default=1.0, min=0.0, max=30.0, precision=1)
    bottom_light_off: FloatProperty(
        name="Reposo base (s)", default=1.0, min=0.0, max=30.0, precision=1)
    lift_height: FloatProperty(
        name="Altura lift (mm)", default=5.0, min=1.0, max=15.0, precision=1)
    lift_speed: FloatProperty(
        name="Vel. lift (mm/min)", default=65.0, min=10.0, max=300.0,
        precision=0)
    bottom_lift_height: FloatProperty(
        name="Lift base (mm)", default=5.0, min=1.0, max=15.0, precision=1)
    bottom_lift_speed: FloatProperty(
        name="Vel. lift base", default=65.0, min=10.0, max=300.0, precision=0)
    retract_speed: FloatProperty(
        name="Vel. retracción", default=150.0, min=10.0, max=400.0,
        precision=0)
    mirror_x: BoolProperty(
        name="Espejar imagen en X", default=True,
        description="Necesario en la Sonic Mini (lcd_mirror)")
    units: EnumProperty(
        name="Unidades",
        items=[("ESCENA", "Según escena (m → mm)",
                "Usa las unidades de Blender: 1 m = 1000 mm"),
               ("MM", "1 unidad = 1 mm",
                "Trata cada unidad de Blender como un milímetro")],
        default="ESCENA")
    scale_pct: FloatProperty(
        name="Escala (%)", default=100.0, min=0.1, max=100000.0, precision=1)
    layer_index: IntProperty(
        name="Capa", default=1, min=1, soft_max=2600,
        description="Capa mostrada en el visor", update=_on_layer_index)


# ------------------------------------------------------------------ panel

class VIEW3D_PT_minislicer(Panel):
    bl_label = "MiniSlicer — Sonic Mini"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MiniSlicer"

    def draw(self, context):
        p = context.scene.minislicer
        layout = self.layout
        profile = slicer.SONIC_MINI

        prefs = _prefs(context)
        if not prefs.activated:
            box = layout.box()
            box.label(text="Add-on sin activar", icon="LOCKED")
            box.label(text="La exportación .phz requiere tu clave de compra")
            op = box.operator("preferences.addon_show",
                              text="Activar licencia…", icon="KEY_HLT")
            op.module = __package__

        col = layout.column(align=True)
        col.operator("minislicer.actualizar", icon="FILE_REFRESH")

        tris = _cache["tris"]
        box = layout.box()
        if tris is None:
            box.label(text="Sin modelo preparado", icon="INFO")
        else:
            size = slicer.mesh_size(tris)
            n = slicer.layer_count(tris, p.layer_height)
            t = slicer.estimate_print_time(n, _params_from_props(p))
            box.label(text=f"{_cache['obj']}", icon="MESH_DATA")
            box.label(text=f"{size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm")
            box.label(text=f"{n} capas — {int(t // 3600)} h "
                           f"{int(t % 3600 // 60):02d} min")
            if not slicer.fits_on_bed(tris, profile):
                box.label(text="¡No cabe en la placa!", icon="ERROR")

        col = layout.column(align=True)
        col.prop(p, "units", text="")
        col.prop(p, "scale_pct")

        layout.separator()
        col = layout.column(align=True)
        col.prop(p, "layer_height")
        col.prop(p, "exposure")
        col.prop(p, "bottom_layers")
        col.prop(p, "bottom_exposure")
        col.prop(p, "light_off")
        col.prop(p, "bottom_light_off")

        col = layout.column(align=True)
        col.prop(p, "lift_height")
        col.prop(p, "lift_speed")
        col.prop(p, "bottom_lift_height")
        col.prop(p, "bottom_lift_speed")
        col.prop(p, "retract_speed")

        layout.prop(p, "mirror_x")

        layout.separator()
        col = layout.column(align=True)
        col.operator("minislicer.abrir_visor", icon="RENDERLAYERS")
        if tris is not None:
            n = slicer.layer_count(tris, p.layer_height)
            row = col.row(align=True)
            row.prop(p, "layer_index")
            row.label(text=f"/ {n}")
            col.label(text=f"z = {(min(p.layer_index, n) - 0.5) * p.layer_height:.3f} mm")

        layout.separator()
        layout.operator("minislicer.exportar", icon="EXPORT")

        box = layout.box()
        box.label(text=f"{profile['name']}", icon="SETTINGS")
        box.label(text=f"{profile['resolution_x']}×{profile['resolution_y']} px — "
                       f"{profile['bed_x']:.1f}×{profile['bed_y']:.0f}×"
                       f"{profile['bed_z']:.0f} mm")


# ------------------------------------------------------------------ registro

_classes = (
    MiniSlicerPrefs,
    MINISLICER_OT_activar,
    MiniSlicerProps,
    MINISLICER_OT_actualizar,
    MINISLICER_OT_abrir_visor,
    MINISLICER_OT_exportar,
    VIEW3D_PT_minislicer,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.minislicer = PointerProperty(type=MiniSlicerProps)


def unregister():
    del bpy.types.Scene.minislicer
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
