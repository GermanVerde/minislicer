# -*- coding: utf-8 -*-
"""Punto de entrada: GUI por defecto, o modo línea de comandos con --cli."""

import argparse
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--cli" not in argv:
        from . import gui
        gui.run()
        return 0

    argv.remove("--cli")
    parser = argparse.ArgumentParser(
        prog="minislicer",
        description="Lamina un STL/OBJ y genera un .phz para la Phrozen Sonic Mini")
    parser.add_argument("entrada", help="archivo STL u OBJ")
    parser.add_argument("salida", help="archivo .phz de salida")
    parser.add_argument("--altura-capa", type=float, default=0.05)
    parser.add_argument("--exposicion", type=float, default=2.5)
    parser.add_argument("--exposicion-base", type=float, default=35.0)
    parser.add_argument("--capas-base", type=int, default=5)
    parser.add_argument("--escala", type=float, default=100.0, help="porcentaje")
    parser.add_argument("--rotacion", type=float, default=0.0, help="grados en Z")
    parser.add_argument("--sin-espejo", action="store_true")
    args = parser.parse_args(argv)

    from . import export, slicer, stl_loader

    tris = stl_loader.load_mesh(args.entrada)
    tris = slicer.transform_mesh(tris, args.escala / 100.0, args.rotacion)
    size = slicer.mesh_size(tris)
    profile = dict(slicer.SONIC_MINI)
    print(f"Modelo: {len(tris)} triángulos, "
          f"{size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f} mm")
    if not slicer.fits_on_bed(tris, profile):
        print("ADVERTENCIA: el modelo no cabe en la placa; se recortará.")

    params = dict(slicer.DEFAULT_PRINT)
    params.update({
        "layer_height_mm": args.altura_capa,
        "exposure_s": args.exposicion,
        "bottom_exposure_s": args.exposicion_base,
        "bottom_layers": args.capas_base,
        "mirror_x": not args.sin_espejo,
    })

    def progress(done, total):
        if done % 25 == 0 or done == total:
            print(f"  capa {done}/{total}")
        return True

    stats = export.export_phz(tris, profile, params, args.salida, progress)
    print(f"Listo: {args.salida}")
    print(f"  Capas: {stats['layers']}  Altura: {stats['height_mm']:.2f} mm")
    print(f"  Resina estimada: {stats['volume_ml']:.2f} ml")
    print(f"  Tiempo estimado: {stats['print_time_s'] / 3600:.2f} h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
