# -*- coding: utf-8 -*-
"""MiniSlicer for Blender — slices the active object and exports native
resin-printer files (.phz / .ctb) for Phrozen printers, with a built-in
layer viewer and a build-volume overlay.

Panel: 3D viewport sidebar (N key), "MiniSlicer" tab.
UI strings are in English and translated via bpy.app.translations
(see traducciones.py).
"""

import os
import time

import bpy
import gpu
import numpy as np
from bpy.app.translations import pgettext_iface as T_
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup
from bpy_extras.io_utils import ExportHelper
from gpu_extras.batch import batch_for_shader

from . import ctb, licencia, perfiles, phz, slicer, traducciones

IMG_NAME = "MiniSlicer_Layer"

# caché del último objeto preparado (triángulos ya en mm, centrados)
_cache = {"tris": None, "obj": "", "sig": None}


# ------------------------------------------------------------- geometría

def _mm_factor(context, props):
    if props.units == "MM":
        base = 1.0
    else:
        base = context.scene.unit_settings.scale_length * 1000.0
    return base * props.scale_pct / 100.0


def _perfil(props):
    return perfiles.perfil(props.printer)


def _gather_tris(context, ob, props):
    """Extrae los triángulos del objeto evaluado (modificadores incluidos),
    en milímetros, centrados en la placa y apoyados en Z=0."""
    if ob is None or ob.type != "MESH":
        raise ValueError(T_("Select a mesh object"))
    deps = context.evaluated_depsgraph_get()
    ob_eval = ob.evaluated_get(deps)
    me = ob_eval.to_mesh()
    try:
        me.calc_loop_triangles()
        nv = len(me.vertices)
        nt = len(me.loop_triangles)
        if nt == 0:
            raise ValueError(T_("The mesh has no faces"))
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
            if ob else (), props.units, round(props.scale_pct, 3),
            props.printer)


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
    profile = _perfil(p)
    n = slicer.layer_count(tris, p.layer_height)
    index = min(max(p.layer_index, 1), n)
    z = (index - 0.5) * p.layer_height
    arr = slicer.slice_layer(tris, z, profile)  # fila 0 = abajo
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


def _on_printer_change(self, context):
    # la resolución y la placa cambian: invalida el caché y refresca todo
    _cache.update(tris=None, obj="", sig=None)
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type in ("VIEW_3D", "IMAGE_EDITOR"):
                area.tag_redraw()


def _on_show_bed(self, context):
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


# ------------------------------------------------- área de impresión (3D)

_bed_handler = None


def _draw_bed():
    context = bpy.context
    scene = getattr(context, "scene", None)
    props = getattr(scene, "minislicer", None) if scene else None
    if props is None or not props.show_bed:
        return
    profile = perfiles.perfil(props.printer)
    try:
        f = 1.0 / _mm_factor(context, props)  # unidades Blender por mm
    except ZeroDivisionError:
        return
    hx = profile["bed_x"] * f / 2.0
    hy = profile["bed_y"] * f / 2.0
    z = profile["bed_z"] * f

    base = [(-hx, -hy, 0), (hx, -hy, 0), (hx, hy, 0), (-hx, hy, 0)]
    top = [(x, y, z) for x, y, _ in base]

    lines = []
    for i in range(4):
        lines += [base[i], base[(i + 1) % 4]]          # placa
    for i in range(4):
        lines += [top[i], top[(i + 1) % 4]]            # techo
        lines += [base[i], top[i]]                     # aristas verticales

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(2.0)

    batch = batch_for_shader(shader, "LINES", {"pos": [v for v in lines[:8]]})
    shader.uniform_float("color", (1.0, 0.55, 0.1, 1.0))
    batch.draw(shader)

    batch = batch_for_shader(shader, "LINES", {"pos": [v for v in lines[8:]]})
    shader.uniform_float("color", (1.0, 0.55, 0.1, 0.25))
    batch.draw(shader)

    gpu.state.line_width_set(1.0)
    gpu.state.blend_set("NONE")


# ------------------------------------------------------------- miniaturas

def _nearest_resize(arr, new_h, new_w):
    h, w = arr.shape[:2]
    yi = (np.arange(new_h) * h / new_h).astype(np.int64)
    xi = (np.arange(new_w) * w / new_w).astype(np.int64)
    return arr[yi][:, xi]


def _thumbnails(tris, n_layers, layer_height, profile):
    """Miniaturas para la pantalla de la impresora: mapa de alturas cenital."""
    prof = dict(profile)
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

def _make_writer(filepath, settings, formato):
    if formato == "phz":
        return phz.PhzWriter(filepath, settings)
    if formato in ("ctb", "cbddlp"):
        return ctb.CtbWriter(filepath, settings, kind=formato)
    raise ValueError(
        T_("The .%s format is not supported yet") % formato)


def _prepare_export(context, filepath):
    p = context.scene.minislicer
    ob = context.active_object
    tris = _gather_tris(context, ob, p)
    _cache.update(tris=tris, obj=ob.name, sig=_signature(context, ob, p))

    params = _params_from_props(p)
    profile = _perfil(p)
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
    writer = _make_writer(filepath, settings, profile["formato"])
    small, large = _thumbnails(tris, n, lh, profile)
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
    op.report({"ERROR"}, T_(
        "MiniSlicer is not activated: enter your purchase key in "
        "Edit > Preferences > Add-ons > MiniSlicer"))
    return False


class MiniSlicerPrefs(AddonPreferences):
    bl_idname = __package__

    license_key: StringProperty(
        name="License key",
        description="The key from your download page after purchase")
    activated: BoolProperty(default=False)
    last_check: FloatProperty(default=0.0)
    status_msg: StringProperty(default="")

    def draw(self, context):
        layout = self.layout
        if self.activated:
            layout.label(text=self.status_msg or T_("License active"),
                         icon="CHECKMARK")
        else:
            layout.label(
                text="Enter your purchase key to unlock exporting",
                icon="KEY_HLT")
        row = layout.row(align=True)
        row.prop(self, "license_key", text="")
        row.operator("minislicer.activar",
                     icon="FILE_REFRESH" if self.activated else "UNLOCKED")
        if self.status_msg and not self.activated:
            layout.label(text=self.status_msg, icon="INFO")


class MINISLICER_OT_activar(Operator):
    bl_idname = "minislicer.activar"
    bl_label = "Activate"
    bl_description = "Check the purchase key against the store"

    def execute(self, context):
        prefs = _prefs(context)
        clave = prefs.license_key.strip()
        if not licencia.clave_valida_en_forma(clave):
            prefs.status_msg = T_("The key format is not valid")
            self.report({"ERROR"}, prefs.status_msg)
            return {"CANCELLED"}
        estado, msg = licencia.verificar(clave)
        if estado is True:
            prefs.activated = True
            prefs.last_check = time.time()
            prefs.status_msg = (T_("Activated — purchase by %s") % msg
                                if msg else T_("Activated"))
            bpy.ops.wm.save_userpref()
            self.report({"INFO"},
                        T_("MiniSlicer activated. Thank you for your purchase!"))
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
    bl_label = "Load / Refresh Model"
    bl_description = ("Takes the active object (with modifiers applied) "
                      "and prepares it for slicing")

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
                    f"{size[2]:.1f} mm, {n} " + T_("layers"))
        return {"FINISHED"}


class MINISLICER_OT_abrir_visor(Operator):
    bl_idname = "minislicer.abrir_visor"
    bl_label = "Open Layer Viewer"
    bl_description = "Opens a window with the image of the selected layer"

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


class MINISLICER_OT_capa_paso(Operator):
    bl_idname = "minislicer.capa_paso"
    bl_label = "Step Layer"
    bl_description = "Moves the layer viewer one layer"
    bl_options = {"INTERNAL"}

    delta: IntProperty(default=1)

    def execute(self, context):
        p = context.scene.minislicer
        p.layer_index = max(1, p.layer_index + self.delta)
        return {"FINISHED"}


class MINISLICER_OT_exportar(Operator, ExportHelper):
    bl_idname = "minislicer.exportar"
    bl_label = "Export for Printer"
    bl_description = "Slices the active object and saves the printer file"

    filename_ext = ".phz"
    filter_glob: StringProperty(default="*.phz;*.ctb;*.cbddlp",
                                options={"HIDDEN"})

    _timer = None
    _state = None

    def invoke(self, context, event):
        if not _exigir_licencia(self, context):
            return {"CANCELLED"}
        p = context.scene.minislicer
        profile = _perfil(p)
        formato = profile["formato"]
        if formato not in perfiles.FORMATOS_SOPORTADOS:
            self.report({"ERROR"}, T_(
                "The .%s format is not supported yet") % formato)
            return {"CANCELLED"}
        self.filename_ext = f".{formato}"
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
                        T_("The model does not fit the plate: it will be cropped"))
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
            self.report({"WARNING"}, T_("Export cancelled"))
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}

        try:
            done = _export_step(st)
        except Exception as exc:  # noqa: BLE001
            self._cleanup(context)
            _abort_export(st)
            self.report({"ERROR"}, T_("Slicing error: %s") % exc)
            return {"CANCELLED"}

        wm = context.window_manager
        wm.progress_update(st["i"])
        context.workspace.status_text_set(
            T_("MiniSlicer: layer %d/%d (Esc to cancel)") % (st["i"], st["n"]))

        if done:
            volume = _finish_export(st)
            self._cleanup(context)
            mins = int(st["print_time"] // 60)
            self.report({"INFO"},
                        T_("Exported: %s — %d layers, %.1f ml, %d h %02d min") % (
                            os.path.basename(st["filepath"]), st["n"],
                            volume, mins // 60, mins % 60))
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _cleanup(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        context.workspace.status_text_set(None)


# ------------------------------------------------------------ propiedades

class MiniSlicerProps(PropertyGroup):
    printer: EnumProperty(
        name="Printer",
        description="Phrozen printer model (resolution, plate and file format)",
        items=perfiles.items_enum(),
        default="SONIC_MINI",
        update=_on_printer_change)
    show_bed: BoolProperty(
        name="Show Build Volume",
        description="Draws the printer plate and height in the viewport "
                    "(the part is auto-centered when slicing)",
        default=False,
        update=_on_show_bed)
    layer_height: FloatProperty(
        name="Layer Height (mm)", default=0.05, min=0.01, max=0.2, step=1,
        precision=3, description="Height of each layer in mm")
    exposure: FloatProperty(
        name="Exposure (s)", default=2.5, min=0.1, max=60.0, precision=2)
    bottom_layers: IntProperty(
        name="Bottom Layers", default=5, min=0, max=20)
    bottom_exposure: FloatProperty(
        name="Bottom Exposure (s)", default=35.0, min=1.0, max=180.0,
        precision=1)
    light_off: FloatProperty(
        name="Light-off Delay (s)", default=1.0, min=0.0, max=30.0, precision=1)
    bottom_light_off: FloatProperty(
        name="Bottom Light-off (s)", default=1.0, min=0.0, max=30.0, precision=1)
    lift_height: FloatProperty(
        name="Lift Height (mm)", default=5.0, min=1.0, max=15.0, precision=1)
    lift_speed: FloatProperty(
        name="Lift Speed (mm/min)", default=65.0, min=10.0, max=300.0,
        precision=0)
    bottom_lift_height: FloatProperty(
        name="Bottom Lift (mm)", default=5.0, min=1.0, max=15.0, precision=1)
    bottom_lift_speed: FloatProperty(
        name="Bottom Lift Speed", default=65.0, min=10.0, max=300.0, precision=0)
    retract_speed: FloatProperty(
        name="Retract Speed", default=150.0, min=10.0, max=400.0,
        precision=0)
    mirror_x: BoolProperty(
        name="Mirror Image in X", default=True,
        description="Required on Phrozen LCD printers (lcd_mirror)")
    units: EnumProperty(
        name="Units",
        items=[("ESCENA", "Scene units (m → mm)",
                "Uses Blender units: 1 m = 1000 mm"),
               ("MM", "1 unit = 1 mm",
                "Treats each Blender unit as one millimeter")],
        default="ESCENA")
    scale_pct: FloatProperty(
        name="Scale (%)", default=100.0, min=0.1, max=100000.0, precision=1)
    layer_index: IntProperty(
        name="Layer", default=1, min=1, soft_max=2600,
        description="Layer shown in the viewer", update=_on_layer_index)


# ----------------------------------------------------------------- paneles

def _draw_layer_slider(layout, p):
    tris = _cache["tris"]
    if tris is None:
        return
    n = slicer.layer_count(tris, p.layer_height)
    row = layout.row(align=True)
    op = row.operator("minislicer.capa_paso", text="", icon="TRIA_LEFT")
    op.delta = -1
    row.prop(p, "layer_index", text="", slider=True)
    op = row.operator("minislicer.capa_paso", text="", icon="TRIA_RIGHT")
    op.delta = 1
    row.label(text=f"/ {n}")
    layout.label(
        text=f"z = {(min(p.layer_index, n) - 0.5) * p.layer_height:.3f} mm")


class VIEW3D_PT_minislicer(Panel):
    bl_label = "MiniSlicer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MiniSlicer"

    def draw(self, context):
        p = context.scene.minislicer
        layout = self.layout
        profile = _perfil(p)

        prefs = _prefs(context)
        if not prefs.activated:
            box = layout.box()
            box.label(text="Add-on not activated", icon="LOCKED")
            box.label(text="Exporting requires your purchase key")
            op = box.operator("preferences.addon_show",
                              text="Activate license…", icon="KEY_HLT")
            op.module = __package__

        col = layout.column(align=True)
        col.prop(p, "printer", text="")
        col.prop(p, "show_bed", icon="MESH_CUBE")

        col = layout.column(align=True)
        col.operator("minislicer.actualizar", icon="FILE_REFRESH")

        tris = _cache["tris"]
        box = layout.box()
        if tris is None:
            box.label(text="No model prepared", icon="INFO")
        else:
            size = slicer.mesh_size(tris)
            n = slicer.layer_count(tris, p.layer_height)
            t = slicer.estimate_print_time(n, _params_from_props(p))
            box.label(text=f"{_cache['obj']}", icon="MESH_DATA")
            box.label(text=f"{size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm")
            box.label(text=f"{n} " + T_("layers") +
                           f" — {int(t // 3600)} h {int(t % 3600 // 60):02d} min")
            if not slicer.fits_on_bed(tris, profile):
                box.label(text="Does not fit the plate!", icon="ERROR")

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
        _draw_layer_slider(col, p)

        layout.separator()
        layout.operator("minislicer.exportar", icon="EXPORT",
                        text=T_("Export .%s") % profile["formato"])

        box = layout.box()
        box.label(text=f"{profile['name']}", icon="SETTINGS")
        box.label(text=f"{profile['resolution_x']}×{profile['resolution_y']} px — "
                       f"{profile['bed_x']:g}×{profile['bed_y']:g}×"
                       f"{profile['bed_z']:g} mm")
        px, py = perfiles.pitch_mm(profile)
        box.label(text=T_("Pixel: %d × %d µm") % (round(px * 1000),
                                                  round(py * 1000)))


class IMAGE_PT_minislicer(Panel):
    """Barra deslizante de capas dentro del visor de imágenes."""
    bl_label = "MiniSlicer"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "MiniSlicer"

    def draw(self, context):
        p = context.scene.minislicer
        layout = self.layout
        if _cache["tris"] is None:
            layout.label(text="No model prepared", icon="INFO")
            layout.operator("minislicer.actualizar", icon="FILE_REFRESH")
            return
        _draw_layer_slider(layout, p)


# ------------------------------------------------------------------ registro

_classes = (
    MiniSlicerPrefs,
    MINISLICER_OT_activar,
    MiniSlicerProps,
    MINISLICER_OT_actualizar,
    MINISLICER_OT_abrir_visor,
    MINISLICER_OT_capa_paso,
    MINISLICER_OT_exportar,
    VIEW3D_PT_minislicer,
    IMAGE_PT_minislicer,
)


def register():
    bpy.app.translations.register(__name__, traducciones.TRANSLATIONS)
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.minislicer = PointerProperty(type=MiniSlicerProps)
    global _bed_handler
    _bed_handler = bpy.types.SpaceView3D.draw_handler_add(
        _draw_bed, (), "WINDOW", "POST_VIEW")


def unregister():
    global _bed_handler
    if _bed_handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_bed_handler, "WINDOW")
        _bed_handler = None
    del bpy.types.Scene.minislicer
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    bpy.app.translations.unregister(__name__)
