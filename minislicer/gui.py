# -*- coding: utf-8 -*-
"""Interfaz gráfica de MiniSlicer (tkinter, en español)."""

import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from . import export, preview3d, slicer, stl_loader

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             "ajustes.json")

VIEW_SIZE = (560, 560)


class MiniSlicerApp:
    def __init__(self, root):
        self.root = root
        root.title("MiniSlicer — Phrozen Sonic Mini")
        root.geometry("1100x780")
        root.minsize(980, 700)

        self.raw_tris = None
        self.tris = None
        self.model_path = None
        self.yaw = 35.0
        self.elev = -65.0
        self._drag_last = None
        self._render_job = None
        self._layer_job = None
        self._export_thread = None
        self._export_queue = queue.Queue()
        self._cancel_export = False

        self.profile = dict(slicer.SONIC_MINI)
        self._build_ui()
        self._load_settings()
        self._render_view()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(main, width=340)
        right.pack(side="right", fill="y", padx=(10, 0))

        # --- lado izquierdo: pestañas con vista 3D y capas
        top_btns = ttk.Frame(left)
        top_btns.pack(fill="x", pady=(0, 6))
        ttk.Button(top_btns, text="📂 Abrir STL/OBJ…",
                   command=self.open_model).pack(side="left")
        self.file_label = ttk.Label(top_btns, text="(ningún modelo cargado)",
                                    foreground="#666")
        self.file_label.pack(side="left", padx=10)

        self.notebook = ttk.Notebook(left)
        self.notebook.pack(fill="both", expand=True)

        tab3d = ttk.Frame(self.notebook)
        self.notebook.add(tab3d, text="  Modelo 3D  ")
        self.view_label = tk.Label(tab3d, bg="#181b22", cursor="fleur")
        self.view_label.pack(fill="both", expand=True)
        self.view_label.bind("<ButtonPress-1>", self._drag_start)
        self.view_label.bind("<B1-Motion>", self._drag_move)
        ttk.Label(tab3d, text="Arrastra con el mouse para rotar la vista",
                  foreground="#888").pack(pady=2)

        tabcapas = ttk.Frame(self.notebook)
        self.notebook.add(tabcapas, text="  Capas  ")
        self.layer_canvas = tk.Label(tabcapas, bg="black")
        self.layer_canvas.pack(fill="both", expand=True)
        bar = ttk.Frame(tabcapas)
        bar.pack(fill="x", pady=4)
        ttk.Label(bar, text="Capa:").pack(side="left")
        self.layer_var = tk.IntVar(value=0)
        self.layer_scale = ttk.Scale(bar, from_=0, to=0, orient="horizontal",
                                     command=self._on_layer_slider)
        self.layer_scale.pack(side="left", fill="x", expand=True, padx=6)
        self.layer_info = ttk.Label(bar, text="—")
        self.layer_info.pack(side="left")
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._update_layer_preview())

        # --- lado derecho: parámetros
        self.vars = {}

        def spin(parent, label, key, default, lo, hi, step, row, unit=""):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                               pady=2)
            var = tk.StringVar(value=str(default))
            self.vars[key] = var
            sb = ttk.Spinbox(parent, textvariable=var, from_=lo, to=hi,
                             increment=step, width=8)
            sb.grid(row=row, column=1, sticky="e", pady=2)
            if unit:
                ttk.Label(parent, text=unit, foreground="#666").grid(
                    row=row, column=2, sticky="w", padx=(4, 0))
            return var

        ft = ttk.LabelFrame(right, text=" Transformación ", padding=8)
        ft.pack(fill="x", pady=(0, 8))
        ft.columnconfigure(1, weight=1)
        spin(ft, "Escala", "scale_pct", 100.0, 1, 10000, 10, 0, "%")
        spin(ft, "Rotación Z", "rot_z", 0, 0, 359, 90, 1, "°")
        for key in ("scale_pct", "rot_z"):
            self.vars[key].trace_add("write", lambda *a: self._schedule_retransform())

        fp = ttk.LabelFrame(right, text=" Parámetros de impresión ", padding=8)
        fp.pack(fill="x", pady=(0, 8))
        fp.columnconfigure(1, weight=1)
        spin(fp, "Altura de capa", "layer_height_mm", 0.05, 0.01, 0.2, 0.01, 0, "mm")
        spin(fp, "Exposición", "exposure_s", 2.5, 0.1, 60, 0.1, 1, "s")
        spin(fp, "Capas base", "bottom_layers", 5, 0, 20, 1, 2)
        spin(fp, "Exposición base", "bottom_exposure_s", 35.0, 1, 180, 1, 3, "s")
        spin(fp, "Reposo sin luz", "light_off_delay_s", 1.0, 0, 30, 0.5, 4, "s")
        spin(fp, "Reposo base", "bottom_light_off_delay_s", 1.0, 0, 30, 0.5, 5, "s")

        fl = ttk.LabelFrame(right, text=" Elevación (lift) ", padding=8)
        fl.pack(fill="x", pady=(0, 8))
        fl.columnconfigure(1, weight=1)
        spin(fl, "Altura lift", "lift_height_mm", 5.0, 1, 15, 0.5, 0, "mm")
        spin(fl, "Velocidad lift", "lift_speed_mmpm", 65.0, 10, 300, 5, 1, "mm/min")
        spin(fl, "Lift capas base", "bottom_lift_height_mm", 5.0, 1, 15, 0.5, 2, "mm")
        spin(fl, "Vel. lift base", "bottom_lift_speed_mmpm", 65.0, 10, 300, 5, 3, "mm/min")
        spin(fl, "Vel. retracción", "retract_speed_mmpm", 150.0, 10, 400, 10, 4, "mm/min")

        self.mirror_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Espejar imagen en X (necesario en la Sonic Mini)",
                        variable=self.mirror_var).pack(anchor="w", pady=(0, 8))

        fi = ttk.LabelFrame(right, text=" Información ", padding=8)
        fi.pack(fill="x", pady=(0, 8))
        self.info_label = ttk.Label(fi, text="Carga un modelo para empezar.",
                                    justify="left")
        self.info_label.pack(anchor="w")

        self.export_btn = ttk.Button(right, text="⚙ Laminar y exportar .phz",
                                     command=self.start_export)
        self.export_btn.pack(fill="x", pady=(4, 4))
        self.cancel_btn = ttk.Button(right, text="Cancelar", state="disabled",
                                     command=self._cancel)
        self.cancel_btn.pack(fill="x")
        self.progress = ttk.Progressbar(right, maximum=100)
        self.progress.pack(fill="x", pady=(8, 2))
        self.status = ttk.Label(right, text="Listo.")
        self.status.pack(anchor="w")

        fperf = ttk.LabelFrame(right, text=" Perfil de impresora (avanzado) ",
                               padding=8)
        fperf.pack(fill="x", pady=(8, 0))
        fperf.columnconfigure(1, weight=1)
        spin(fperf, "Píxeles X", "resolution_x", self.profile["resolution_x"],
             1, 10000, 1, 0, "px")
        spin(fperf, "Píxeles Y", "resolution_y", self.profile["resolution_y"],
             1, 10000, 1, 1, "px")
        spin(fperf, "Ancho placa", "bed_x", self.profile["bed_x"], 1, 500, 0.1, 2, "mm")
        spin(fperf, "Largo placa", "bed_y", self.profile["bed_y"], 1, 500, 0.1, 3, "mm")
        spin(fperf, "Altura máx.", "bed_z", self.profile["bed_z"], 1, 500, 1, 4, "mm")

    # ------------------------------------------------------------- helpers

    def _num(self, key, cast=float):
        try:
            return cast(float(self.vars[key].get().replace(",", ".")))
        except (ValueError, tk.TclError):
            return None

    def _current_profile(self):
        p = dict(self.profile)
        for k, cast in (("resolution_x", int), ("resolution_y", int),
                        ("bed_x", float), ("bed_y", float), ("bed_z", float)):
            v = self._num(k, cast)
            if v:
                p[k] = v
        return p

    def _current_params(self):
        params = dict(slicer.DEFAULT_PRINT)
        for k in ("layer_height_mm", "exposure_s", "bottom_exposure_s",
                  "light_off_delay_s", "bottom_light_off_delay_s",
                  "lift_height_mm", "lift_speed_mmpm", "bottom_lift_height_mm",
                  "bottom_lift_speed_mmpm", "retract_speed_mmpm"):
            v = self._num(k)
            if v is not None:
                params[k] = v
        v = self._num("bottom_layers", int)
        params["bottom_layers"] = v if v is not None else 5
        params["mirror_x"] = self.mirror_var.get()
        if params["layer_height_mm"] <= 0:
            params["layer_height_mm"] = 0.05
        return params

    # --------------------------------------------------------------- modelo

    def open_model(self):
        path = filedialog.askopenfilename(
            title="Abrir modelo",
            filetypes=[("Modelos 3D", "*.stl *.obj"),
                       ("STL", "*.stl"), ("OBJ", "*.obj")])
        if not path:
            return
        try:
            self.raw_tris = stl_loader.load_mesh(path)
        except Exception as exc:
            messagebox.showerror("Error al abrir",
                                 f"No se pudo leer el modelo:\n{exc}")
            return
        self.model_path = path
        self.file_label.config(
            text=f"{os.path.basename(path)}  ({len(self.raw_tris):,} triángulos)")
        self._retransform()

    def _schedule_retransform(self):
        if self._render_job:
            self.root.after_cancel(self._render_job)
        self._render_job = self.root.after(400, self._retransform)

    def _retransform(self):
        self._render_job = None
        if self.raw_tris is None:
            return
        scale = (self._num("scale_pct") or 100.0) / 100.0
        rot = self._num("rot_z") or 0.0
        self.tris = slicer.transform_mesh(self.raw_tris, scale, rot)
        self._update_info()
        self._render_view()
        self._update_layer_range()
        self._update_layer_preview()

    def _update_info(self):
        if self.tris is None:
            return
        p = self._current_profile()
        size = slicer.mesh_size(self.tris)
        params = self._current_params()
        n = slicer.layer_count(self.tris, params["layer_height_mm"])
        t = slicer.estimate_print_time(n, params)
        fits = slicer.fits_on_bed(self.tris, p)
        txt = (f"Tamaño: {size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm\n"
               f"Capas: {n}   Tiempo estimado: {_fmt_time(t)}")
        if not fits:
            txt += "\n⚠ ¡El modelo NO cabe en la placa!"
        self.info_label.config(text=txt,
                               foreground="#b00020" if not fits else "")

    # ------------------------------------------------------------- vista 3D

    def _drag_start(self, ev):
        self._drag_last = (ev.x, ev.y)

    def _drag_move(self, ev):
        if self._drag_last is None:
            return
        dx = ev.x - self._drag_last[0]
        dy = ev.y - self._drag_last[1]
        self._drag_last = (ev.x, ev.y)
        self.yaw = (self.yaw + dx * 0.6) % 360
        self.elev = max(-90.0, min(30.0, self.elev - dy * 0.4))
        self._render_view(fast=True)

    def _render_view(self, fast=False):
        img = preview3d.render_mesh(
            self.tris, size=VIEW_SIZE, yaw=self.yaw, elev=self.elev,
            profile=self._current_profile(),
            max_tris=8000 if fast else 45000)
        self._view_photo = ImageTk.PhotoImage(img)
        self.view_label.config(image=self._view_photo)

    # --------------------------------------------------------------- capas

    def _update_layer_range(self):
        if self.tris is None:
            return
        params = self._current_params()
        n = slicer.layer_count(self.tris, params["layer_height_mm"])
        self.layer_scale.config(to=max(0, n - 1))

    def _on_layer_slider(self, _value):
        if self._layer_job:
            self.root.after_cancel(self._layer_job)
        self._layer_job = self.root.after(120, self._update_layer_preview)

    def _update_layer_preview(self):
        self._layer_job = None
        if self.tris is None:
            return
        try:
            index = int(float(self.layer_scale.get()))
        except tk.TclError:
            return
        params = self._current_params()
        profile = self._current_profile()
        lh = params["layer_height_mm"]
        z = (index + 0.5) * lh
        img = slicer.slice_layer(self.tris, z, profile)
        pil = Image.fromarray(img)
        h = max(200, self.layer_canvas.winfo_height() or 500)
        w = int(pil.width * h / pil.height)
        pil = pil.resize((max(1, w), h), Image.NEAREST)
        self._layer_photo = ImageTk.PhotoImage(pil)
        self.layer_canvas.config(image=self._layer_photo)
        self.layer_info.config(text=f"{index + 1} — z={z:.3f} mm")

    # ---------------------------------------------------------- exportación

    def start_export(self):
        if self.tris is None:
            messagebox.showinfo("MiniSlicer", "Primero abre un modelo STL u OBJ.")
            return
        profile = self._current_profile()
        if not slicer.fits_on_bed(self.tris, profile):
            if not messagebox.askyesno(
                    "Modelo fuera de la placa",
                    "El modelo no cabe en el área de impresión.\n"
                    "¿Exportar de todos modos? (se recortará)"):
                return
        suggested = "modelo.phz"
        if self.model_path:
            suggested = os.path.splitext(os.path.basename(self.model_path))[0] + ".phz"
        out = filedialog.asksaveasfilename(
            title="Guardar archivo para la impresora",
            defaultextension=".phz", initialfile=suggested,
            filetypes=[("Archivo Phrozen/ChiTu", "*.phz")])
        if not out:
            return

        self._save_settings()
        params = self._current_params()
        self._cancel_export = False
        self.export_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.status.config(text="Laminando…")
        tris = self.tris.copy()

        def progress(done, total):
            self._export_queue.put(("progress", done, total))
            return not self._cancel_export

        def worker():
            t0 = time.time()
            try:
                stats = export.export_phz(tris, profile, params, out, progress)
                self._export_queue.put(("done", stats, out, time.time() - t0))
            except export.Cancelled:
                self._export_queue.put(("cancelled", out))
            except Exception as exc:  # noqa: BLE001
                self._export_queue.put(("error", str(exc)))

        self._export_thread = threading.Thread(target=worker, daemon=True)
        self._export_thread.start()
        self.root.after(100, self._poll_export)

    def _cancel(self):
        self._cancel_export = True

    def _poll_export(self):
        try:
            while True:
                msg = self._export_queue.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, done, total = msg
                    self.progress.config(maximum=total, value=done)
                    self.status.config(text=f"Laminando capa {done}/{total}…")
                elif kind == "done":
                    _, stats, out, secs = msg
                    self._export_finished()
                    self.progress.config(value=0)
                    self.status.config(text="Archivo exportado correctamente.")
                    messagebox.showinfo(
                        "Exportación lista",
                        f"Archivo: {out}\n\n"
                        f"Capas: {stats['layers']}\n"
                        f"Altura: {stats['height_mm']:.2f} mm\n"
                        f"Resina estimada: {stats['volume_ml']:.1f} ml\n"
                        f"Tiempo de impresión: {_fmt_time(stats['print_time_s'])}\n"
                        f"(laminado en {secs:.0f} s)")
                    return
                elif kind == "cancelled":
                    self._export_finished()
                    self.progress.config(value=0)
                    self.status.config(text="Exportación cancelada.")
                    try:
                        os.remove(msg[1])
                    except OSError:
                        pass
                    return
                elif kind == "error":
                    self._export_finished()
                    self.status.config(text="Error al exportar.")
                    messagebox.showerror("Error", msg[1])
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll_export)

    def _export_finished(self):
        self.export_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")

    # --------------------------------------------------------------- ajustes

    def _save_settings(self):
        data = {k: v.get() for k, v in self.vars.items()}
        data["mirror_x"] = self.mirror_var.get()
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        for k, v in data.items():
            if k == "mirror_x":
                self.mirror_var.set(bool(v))
            elif k in self.vars:
                self.vars[k].set(str(v))


def _fmt_time(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} min"
    return f"{m} min {s:02d} s"


def run():
    root = tk.Tk()
    try:
        root.iconbitmap(default="")
    except tk.TclError:
        pass
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    MiniSlicerApp(root)
    root.mainloop()
