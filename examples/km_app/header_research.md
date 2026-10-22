# Investigación de cabeceras y documentación instrumental

Fecha: 2026-10-19. Caso piloto: KM 40+672 / F1.

El usuario confirmó fuente de mazo (`HAMMER`), componente vertical y offset
longitudinal inicial de 15 m. Están registrados en la preparación parcial.
Confirmó también que se utilizó **interruptor del mazo**; se registró como
referencia del trigger. Con DELAY=0 se obtiene un cero nominal respecto al pulso
del interruptor. Esto no constituye calibración de latencia respecto al contacto
mecánico. El usuario confirmó después **ausencia de pretrigger (0 s)**.
La preparación parcial declara `SIDECAR_AUTHORITATIVE` con `t0_s=0` para los
24 canales y procedencia explícita de esta referencia nominal al interruptor.

La cabecera del piloto identifica `INSTRUMENT=SEISMIC_SOURCE_CO`, sin modelo ni
serie. Contiene `DELAY=0`, `DESCALING_FACTOR=1000` y `STACK=0`; no incluye
`SOURCE`, `RECEIVER`, `RECEIVER_SPECS` ni `FIXED_GAIN`.
La [revisión de cabeceras](preparation/header_audit.json) resume el inventario
existente y la inspección directa del piloto. Los hashes de originales permanecen
en `preparation/inventory.json`; no se afirma una nueva lectura binaria completa.

## Significado documentado

Según el [estándar SEG-2, apartados C1/C2](https://seg.org/wp-content/uploads/2025/11/seg_2.pdf),
`UNITS` describe unidades de longitud. Su valor NONE no informa la unidad de
amplitud. `DELAY` relaciona primera muestra y pulso de arranque. La conversión
definida es `mV = muestra × DESCALING_FACTOR / STACK`, con STACK positivo.
Por tanto, el cero presente requiere aclarar la exportación; no se reemplaza
automáticamente por uno. Tampoco se identifica el pulso con el golpe por tener
DELAY cero.

Esto corrige la interpretación inicial que vinculaba UNITS=NONE con amplitud.

## Manual localizado y alcance de su uso

El [manual DAQLink 4, de Seismic Source](https://geodevice.uz/upload/iblock/86a/DAQLink-4-Manual.pdf)
es documentación del fabricante alojada por un distribuidor. Sus apartados 4.2.1,
4.3.2 y 5.4.8 describen disparo por interruptor de martillo, otras opciones de
trigger y visualización en voltios u otras unidades configuradas. No establece
cuál de esas opciones se utilizó en estos archivos ni resuelve su STACK cero.

El usuario confirmó después que el equipo utilizado es **DAQLink 4**. El manual
corresponde al modelo confirmado; se confirmó interruptor de mazo, pero siguen
sin identificarse versión de software y convención de exportación.
El usuario confirmó pretrigger de 0 s. No se aplica su configuración
por defecto como hecho de adquisición.

## Evidencia que resolvería lo pendiente

El modelo ya está identificado; falta software/versión de adquisición.
La configuración original o la base de proyecto de VScope, si fue ese
software, permitiría comprobar el modo de trigger, pretrigger, calibración y
apilamiento/exportación. Una foto legible de la placa del sismógrafo también
serviría para identificar modelo, sin establecer por sí sola esos ajustes.

Las cuatro fotos de campo examinadas no permitieron identificar una placa del
sismógrafo. No se contactó al fabricante ni se instaló software de adquisición.

No se escalaron muestras, se corrigieron tiempos ni se creó un sidecar listo
para ingesta a partir de estas hipótesis.

Actualización posterior: el usuario indicó asumir cotas e incertidumbres cero.
Se creó una [copia exploratoria para carga](README.md#cargar-km-como-trs)
que declara explícitamente esos supuestos y las hipótesis de un golpe/voltios,
conservando los valores originales de cabecera. No resuelve la incertidumbre
instrumental ni certifica metadatos de campo.
