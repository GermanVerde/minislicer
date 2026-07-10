# MiniSlicer for Blender

Add-on de Blender que **lamina el objeto activo y exporta archivos nativos
(`.phz` / `.ctb`)** listos para imprimir en impresoras de resina
**Phrozen**, sin salir de Blender y sin software intermedio.

*Blender add-on that slices the active object and exports native
`.phz` / `.ctb` files for Phrozen resin printers, directly from Blender.*

**Gratis y de código abierto.** Si MiniSlicer te resulta útil, puedes
apoyar su desarrollo con una donación en Ko-fi:
[ko-fi.com/micotico36213](https://ko-fi.com/micotico36213) ☕

*Free and open source. If MiniSlicer is useful to you, you can support its
development with a donation on Ko-fi.*

## Impresoras compatibles

| Modelo | Resolución | Placa (mm) | Formato | Estado |
|---|---|---|---|---|
| Sonic Mini | 1080×1920 | 67.8×120×130 | `.phz` | ✅ Probada en hardware |
| Sonic | 1080×1920 | 67.8×120×170 | `.phz` | 🧪 Beta |
| Transform | 3840×2160 | 291.8×164.2×400 | `.phz` | 🧪 Beta |
| Sonic Mini 4K | 3840×2160 | 134.4×75.6×130 | `.ctb` | 🧪 Beta |
| Sonic Mini 8K | 7500×3240 | 165×71.3×180 | `.ctb` | 🧪 Beta |
| Sonic 4K | 3840×2160 | 134.4×75.6×200 | `.ctb` | 🧪 Beta |
| Sonic XL 4K | 3840×2400 | 192×120×200 | `.ctb` | 🧪 Beta |
| Sonic Mighty 4K | 3840×2400 | 200×125×220 | `.ctb` | 🧪 Beta |
| Sonic Mighty 8K | 7680×4320 | 218×123×235 | `.ctb` | 🧪 Beta |
| Sonic Mega 8K | 7680×4320 | 330×185×400 | `.ctb` | 🧪 Beta |
| Sonic Mini 8K S | 7536×3240 | 165.8×71.3×170 | `.prz` | 🚧 Próximamente |
| Sonic Mighty 12K | 11520×5120 | 218.9×123.1×235 | `.prz` | 🚧 Próximamente |
| Sonic Mega 8K S | 7680×4320 | 330×185×300 | `.prz` | 🚧 Próximamente |

**Sobre el estado beta**: los perfiles provienen de las especificaciones
publicadas por Phrozen y los archivos generados están validados contra las
implementaciones de referencia (relectura píxel a píxel, UVtools, uv3dp),
pero por ahora solo la **Sonic Mini** está verificada con impresiones
reales. Si imprimes con otro modelo, [abre un issue][issues] contando cómo
te fue — con eso el perfil pasa de beta a verificado. Los modelos `.prz`
(2023+) aparecen en el panel pero aún no tienen escritor de archivo.

[issues]: ../../issues

## Características

- **Panel integrado**: barra lateral del viewport 3D (tecla `N`), pestaña
  «MiniSlicer», interfaz traducida a 10 idiomas.
- **13 perfiles Phrozen** con el volumen de impresión dibujado en el
  viewport; la pieza se centra sola al laminar.
- **Visor de capas**: muestra la imagen exacta de cada capa a la
  resolución nativa del LCD del perfil elegido, navegable capa por capa.
- **Laminado directo del objeto activo**: los modificadores (Boolean,
  Remesh, soportes…) se aplican automáticamente; la escala y rotación del
  objeto se respetan.
- **Exportación sin congelar la interfaz**: operador modal con avance en la
  barra de estado (`Esc` cancela).
- Relleno por scanline con regla **par-impar**: agujeros y cavidades
  internas de mallas cerradas salen correctos sin configurar nada.
- Estimación de resina (ml) y tiempo de impresión; aviso si la pieza no
  cabe en la placa; miniaturas para la pantalla de la impresora.
- **Cero dependencias y cero red**: solo usa el numpy incluido en Blender,
  sin claves de activación, sin telemetría, sin conexión a nada.

## Requisitos

- Blender **4.2 o superior** (probado en 5.1.2).
- Una impresora de resina Phrozen de la tabla de arriba.

## Instalación

1. Descarga `MiniSlicer_Blender.zip` (o constrúyelo, ver abajo).
2. En Blender: `Edit → Preferences → Add-ons → ▼ → Install from Disk…`
   y elige el zip.
3. Verifica que la casilla del add-on quede **marcada**.
4. En el viewport 3D presiona `N` → pestaña **MiniSlicer**.

## Uso

1. Elige tu **impresora** en el desplegable del panel.
2. Selecciona tu pieza (malla cerrada/estanca, con soportes ya modelados).
3. **Cargar / actualizar modelo** — revisa tamaño en mm, capas y tiempo.
4. **Abrir visor de capas** — inspecciona las secciones antes de exportar.
5. Ajusta exposición según tu resina (típico: 1.5–3 s por capa de 0.05 mm;
   base 30–40 s).
6. **Exportar** (`.phz` o `.ctb` según el perfil) → copia el archivo al
   pendrive → imprime.

**Unidades**: por defecto usa las de la escena (1 m = 1000 mm). Si modelas
con la convención «1 unidad = 1 mm», cámbialo en el selector del panel.

## Construir el zip desde el código

```
blender --command extension build --source-dir minislicer_blender --output-filepath MiniSlicer_Blender.zip
```

## Detalles técnicos de los formatos

Los formatos `.phz` y `.ctb` (ChiTu) están implementados según la
implementación de referencia de [UVtools](https://github.com/sn4k3/UVtools)
y la documentación de
[catibo](https://github.com/cbiffle/catibo/blob/master/doc/cbddlp-ctb.adoc):

- Cabecera y tabla de capas binarias según cada spec.
- Imagen de capa: RLE de gris de 7 bits (`.phz`) / RLE del formato `.ctb`;
  soporte de cifrado XOR (se escribe sin cifrar, `EncryptionKey=0`).
- Vistas previas RGB15 + RLE (400×300 y 200×125).

Los archivos generados fueron validados por ida y vuelta (relectura píxel a
píxel) y con [uv3dp](https://github.com/ezrec/uv3dp) como lector
independiente.

## Primera impresión

Imprime primero un cubo de calibración de 20 mm: si mide 20.0 mm por lado y
la orientación es correcta (nada en espejo), el perfil está bien. Si algo
sale invertido, destilda «Espejar imagen en X».

## Licencia

[GPL-3.0-or-later](LICENSE) — como todos los add-ons de Blender. Gratis,
sin claves de activación ni registro.

Este software se ofrece sin garantía; verifica siempre la primera impresión
con una pieza pequeña.
