# MiniSlicer — laminador simple para la Phrozen Sonic Mini

Convierte modelos **STL u OBJ exportados de Blender** en archivos **`.phz`**
listos para imprimir en la Phrozen Sonic Mini. Sin registros, sin nube, sin
menús enredados: abrir, ajustar, exportar.

## Cómo usarlo

1. Doble clic en **`MiniSlicer.bat`** (o `python -m minislicer` desde esta carpeta).
2. **📂 Abrir STL/OBJ…** y elige tu modelo.
3. Revisa la pieza en la pestaña **Modelo 3D** (arrastra con el mouse para rotar)
   y las secciones en la pestaña **Capas** (deslizador).
4. Ajusta exposición y demás parámetros según tu resina.
5. **⚙ Laminar y exportar .phz**, copia el archivo al pendrive y a imprimir.

Los parámetros quedan guardados en `ajustes.json` para la próxima vez.

## Exportar desde Blender

- `Archivo → Exportar → STL (.stl)`.
- Blender trabaja en metros pero el STL se interpreta en **milímetros**
  (la convención habitual): un cubo de 1 m en Blender = 1 mm... En la práctica,
  modela con `Unit Scale` en `0.001` (milímetros) o simplemente verifica el
  tamaño que MiniSlicer muestra al cargar y corrige con el campo **Escala**.
- Aplica las transformaciones antes de exportar (`Ctrl+A → All Transforms`).
- La malla debe ser **cerrada** (estanca). En Blender: modo edición,
  `Seleccionar → Todo por rasgo → Bordes sueltos` para revisar; el modificador
  *Remesh* o `Merge by Distance` ayudan a sellar mallas problemáticas.
- **Soportes y vaciado se hacen en Blender** (este programa solo lamina).

## Parámetros por defecto (resina gris estándar, 0.05 mm)

| Parámetro | Valor |
|---|---|
| Altura de capa | 0.05 mm |
| Exposición normal | 2.5 s |
| Capas base | 5 |
| Exposición base | 35 s |
| Lift | 5 mm a 65 mm/min |
| Retracción | 150 mm/min |

Ajusta la exposición según el fabricante de tu resina (para la Sonic Mini
suele estar entre 1.5 y 3 s por capa de 0.05 mm).

## Detalles técnicos

- Perfil de máquina: LCD 1080×1920 px, placa 67.8 × 120 × 130 mm, imagen
  espejada en X (`lcd_mirror`), formato `.phz` versión 2 de ChiTu.
  Todo editable en «Perfil de impresora (avanzado)».
- El formato de archivo sigue la implementación de referencia de
  [UVtools](https://github.com/sn4k3/UVtools) y la documentación de
  [catibo](https://github.com/cbiffle/catibo/blob/master/doc/cbddlp-ctb.adoc).
- Laminado por scanline con regla par-impar: agujeros y cavidades internas
  de mallas cerradas salen correctos sin configurar nada.
- Modo línea de comandos:
  `python -m minislicer --cli pieza.stl pieza.phz --altura-capa 0.05 --exposicion 2.5`

## Requisitos

- Python 3.12 con `numpy` y `pillow` (ya instalados).

## Primera impresión: recomendación

Imprime primero `ejemplos/cubo20.stl` (cubo de calibración de 20 mm):
si sale de 20.0 mm por lado y con el texto/orientación correcta (no en espejo),
el perfil está bien. Si algo sale invertido, cambia la casilla
«Espejar imagen en X».
