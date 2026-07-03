# -*- coding: utf-8 -*-
"""Laminado completo y escritura del archivo .phz."""

import numpy as np

from . import phz, preview3d, slicer


class Cancelled(Exception):
    pass


def export_phz(tris, profile, params, out_path, progress_cb=None):
    """Lamina la malla ya transformada y escribe el .phz.

    progress_cb(hecho, total) se llama por capa; si devuelve False se cancela.
    Devuelve un dict con estadísticas (capas, volumen_ml, tiempo_s).
    """
    lh = float(params["layer_height_mm"])
    n_layers = slicer.layer_count(tris, lh)
    bottom = int(params["bottom_layers"])
    mirror = bool(params.get("mirror_x", True))

    pitch_x = profile["bed_x"] / profile["resolution_x"]
    pitch_y = profile["bed_y"] / profile["resolution_y"]
    pixel_volume_mm3 = pitch_x * pitch_y * lh

    print_time = slicer.estimate_print_time(n_layers, params)

    settings = {
        "resolution_x": int(profile["resolution_x"]),
        "resolution_y": int(profile["resolution_y"]),
        "bed_size_x": float(profile["bed_x"]),
        "bed_size_y": float(profile["bed_y"]),
        "bed_size_z": float(profile["bed_z"]),
        "layer_height_mm": lh,
        "exposure_s": float(params["exposure_s"]),
        "bottom_exposure_s": float(params["bottom_exposure_s"]),
        "bottom_layers": bottom,
        "light_off_delay_s": float(params["light_off_delay_s"]),
        "bottom_light_off_delay_s": float(params["bottom_light_off_delay_s"]),
        "lift_height_mm": float(params["lift_height_mm"]),
        "lift_speed_mmpm": float(params["lift_speed_mmpm"]),
        "bottom_lift_height_mm": float(params["bottom_lift_height_mm"]),
        "bottom_lift_speed_mmpm": float(params["bottom_lift_speed_mmpm"]),
        "retract_speed_mmpm": float(params["retract_speed_mmpm"]),
        "projector_type": 1 if mirror else 0,
        "machine_name": profile.get("name", "Phrozen Sonic Mini"),
        "layer_count": n_layers,
        "overall_height_mm": n_layers * lh,
        "print_time_s": int(print_time),
        "encryption_key": 0,
    }

    writer = phz.PhzWriter(out_path, settings)
    try:
        small, large = preview3d.render_thumbnails(tris, profile)
        writer.write_previews(small, large)
        writer.begin_layers()

        filled_pixels = 0
        for i in range(n_layers):
            z = (i + 0.5) * lh
            img = slicer.slice_layer(tris, z, profile)
            filled_pixels += int(np.count_nonzero(img))
            if mirror:
                img = np.fliplr(img)
            if i < bottom:
                exp = float(params["bottom_exposure_s"])
                off = float(params["bottom_light_off_delay_s"])
            else:
                exp = float(params["exposure_s"])
                off = float(params["light_off_delay_s"])
            writer.write_layer(np.ascontiguousarray(img), (i + 1) * lh, exp, off)
            if progress_cb is not None and progress_cb(i + 1, n_layers) is False:
                raise Cancelled()

        volume_ml = filled_pixels * pixel_volume_mm3 / 1000.0
        writer.s["volume_ml"] = volume_ml
        writer.s["weight_g"] = volume_ml * 1.1  # densidad típica de resina
        writer.close()
    except BaseException:
        writer.f.close()
        raise

    return {
        "layers": n_layers,
        "volume_ml": volume_ml,
        "print_time_s": print_time,
        "height_mm": n_layers * lh,
    }
