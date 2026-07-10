# Blender Plugin PHZ — MiniSlicer para Phrozen Sonic Mini

Add-on de Blender que **lamina el objeto activo y exporta archivos `.phz`**
listos para imprimir en la impresora de resina **Phrozen Sonic Mini**, sin
salir de Blender y sin software intermedio.

*Blender add-on that slices the active object and exports `.phz` files for
the Phrozen Sonic Mini resin printer, directly from Blender.*

**Gratis y de código abierto.** Si MiniSlicer te resulta útil, puedes
apoyar su desarrollo con una donación en Ko-fi:
[ko-fi.com/micotico36213](https://ko-fi.com/micotico36213) ☕

*Free and open source. If MiniSlicer is useful to you, you can support its
development with a donation on Ko-fi.*

## Características

- **Panel integrado**: barra lateral del viewport 3D (tecla `N`), pestaña
  «MiniSlicer», interfaz en español.
- **Visor de capas**: muestra la imagen exacta de cada capa (1080×1920) tal
  como la proyectará el LCD, navegable capa por capa.
- **Laminado directo del objeto activo**: los modificadores (Boolean,
  Remesh, soportes…) se aplican automáticamente; la escala y rotación del
  objeto se respetan.
- **Exportación sin congelar la interfaz**: operador modal con avance en la
  barra de estado (`Esc` cancela).
- Relleno por scanline con regla **par-impar**: agujeros y cavidades
  internas de mallas cerradas salen correctos sin configurar nada.
- Estimación de resina (ml) y tiempo de impresión; aviso si la pieza no
  cabe en la placa; miniaturas para la pantalla de la impresora.
- **Cero dependencias**: solo usa el numpy incluido en Blender.

## Requisitos

- Blender **4.2 o superior** (probado en 5.1.2).
- Impresora Phrozen Sonic Mini (LCD 1080×1920, placa 67.8×120×130 mm,
  formato `.phz`, imagen espejada en X).

## Instalación

1. Descarga `MiniSlicer_Blender.zip` (o constrúyelo, ver abajo).
2. En Blender: `Edit → Preferences → Add-ons → ▼ → Install from Disk…`
   y elige el zip.
3. Verifica que la casilla del add-on quede **marcada**.
4. En el viewport 3D presiona `N` → pestaña **MiniSlicer**.

## Uso

1. Selecciona tu pieza (malla cerrada/estanca, con soportes ya modelados).
2. **Cargar / actualizar modelo** — revisa tamaño en mm, capas y tiempo.
3. **Abrir visor de capas** — inspecciona las secciones antes de exportar.
4. Ajusta exposición según tu resina (típico: 1.5–3 s por capa de 0.05 mm;
   base 30–40 s).
5. **Exportar .phz** → copia el archivo al pendrive → imprime.

**Unidades**: por defecto usa las de la escena (1 m = 1000 mm). Si modelas
con la convención «1 unidad = 1 mm», cámbialo en el selector del panel.

## Construir el zip desde el código

```
blender --command extension build --source-dir minislicer_blender --output-filepath MiniSlicer_Blender.zip
```

## Detalles técnicos del formato

El formato `.phz` (ChiTu, versión 2) está implementado según la
implementación de referencia de [UVtools](https://github.com/sn4k3/UVtools)
(`PHZFile.cs`) y la documentación de
[catibo](https://github.com/cbiffle/catibo/blob/master/doc/cbddlp-ctb.adoc):

- Cabecera de 216 bytes, tabla de capas de 36 bytes por capa.
- Imagen de capa: RLE de gris de 7 bits con corte de corridas a mitad de
  fila; soporte de cifrado XOR (se escribe sin cifrar, `EncryptionKey=0`).
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
