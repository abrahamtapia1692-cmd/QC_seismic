# Semáforo diagnóstico de datos de campo

Criterio local **FIELD_DIAGNOSTIC_V1 · borrador sin calibrar**. No habilita aceptación de campo ni Vs30.

Un mini conjunto es un registro multicanal, formado por varias trazas. Los 11 registros pertenecen a **dos sitios**, no a 11 sitios independientes.

- **Oysand / P1:** r1–r4, offsets 10/15/20/30 m, 24 trazas por registro; referencia MASW compuesta del sitio.
- **Chevremont:** siete fuentes 0–60 m, 48 trazas por registro, cada archivo apila 3 impactos. Solo la fuente 0 m tiene 43 anotaciones TRS.

Verde = dimensión comprobada; amarillo = revisión; rojo = problema según criterio diagnóstico; gris = evidencia insuficiente. El rojo TRS describe cobertura del procesamiento actual, no prueba que la adquisición sea mala.

| Registro | Técnica | Lectura | Proceso | Referencia | Diagnóstico |
|---|---|---|---|---|---|
| Oysand · r1 · offset 10 m | MASW | Verde | Amarillo | Amarillo | Amarillo |
| Oysand · r2 · offset 15 m | MASW | Verde | Amarillo | Amarillo | Amarillo |
| Oysand · r3 · offset 20 m | MASW | Verde | Amarillo | Amarillo | Amarillo |
| Oysand · r4 · offset 30 m | MASW | Verde | Amarillo | Amarillo | Amarillo |
| Chevremont · Fuente 0 m · 0m.sg2 | TRS | Verde | Rojo | No evaluable | Rojo |
| Chevremont · Fuente 10 m · 10m.sg2 | TRS | Verde | Rojo | No evaluable | Rojo |
| Chevremont · Fuente 20 m · 20m.sg2 | TRS | Verde | Rojo | No evaluable | Rojo |
| Chevremont · Fuente 30 m · 30m.sg2 | TRS | Verde | Rojo | No evaluable | Rojo |
| Chevremont · Fuente 40 m · 40m.sg2 | TRS | Verde | Rojo | No evaluable | Rojo |
| Chevremont · Fuente 50 m · 50m.sg2 | TRS | Verde | Rojo | No evaluable | Rojo |
| Chevremont · Fuente 60 m · 60m.sg2 | TRS | Verde | Rojo | No evaluable | Rojo |

## Reglas y alcance

Lectura: hashes verificados, comprobaciones técnicas por registro y muestras finitas; canales cero o constantes impiden verde. No certifica respuesta instrumental o saturación.

TRS: cobertura = onsets / todas las trazas del registro. Verde ≥80 %, amarillo ≥50 % y <80 %, rojo <50 %. Límites locales provisionales para disponibilidad, no exactitud. Cambiar los límites requiere editar y versionar `examples/field/quality_criteria.json`.

MASW: soporte candidato c > 2·f·dx; soporte vacío rojo, soporte parcial o modo sin verificar amarillo. La curva compuesta permite diferencias numéricas, sin un umbral de aceptación calibrado. No se asignan las listas de curvas del repositorio a disparos sin una correspondencia documentada.

Referencia TRS: sin etiquetas o sin reloj/definición de onset verificados, gris. No se convierte `err` del SGT en incertidumbre calibrada. El promedio de diferencias siempre se acompaña de cobertura y abstenciones.

Diagnóstico: peor dimensión evaluada; faltantes obligatorios impiden verde. Aceptación de campo, inversión y Vs30 permanecen pendientes.

## Detalle por registro

### Oysand · r1 · offset 10 m

Archivo: `examples/field/raw/oysand/examples/Data/Oysand_dx_2m_x1_10m_forward.dat`. 24 canales × 2201 muestras; 1000 Hz.

Registro multicanal; no sitio independiente.

58/143 bins candidatos sin alias espacial. Identidad modal aparente y papel del canal trigger pendientes.

57 bins comparados: mediana absoluta 0.78 m/s; RMS 7.17 m/s. Referencia compuesta del mismo sitio; sin etiquetas individuales ni umbral de exactitud calibrado.

Siguiente revisión: Confirmar canal 1/trigger y modo; comparar sensibilidad a ventanas en la banda admisible.

### Oysand · r2 · offset 15 m

Archivo: `examples/field/raw/oysand/examples/Data/Oysand_dx_2m_x1_15m_forward.dat`. 24 canales × 2201 muestras; 1000 Hz.

Registro multicanal; no sitio independiente.

59/143 bins candidatos sin alias espacial. Identidad modal aparente y papel del canal trigger pendientes.

58 bins comparados: mediana absoluta 1.19 m/s; RMS 5.76 m/s. Referencia compuesta del mismo sitio; sin etiquetas individuales ni umbral de exactitud calibrado.

Siguiente revisión: Confirmar canal 1/trigger y modo; comparar sensibilidad a ventanas en la banda admisible.

### Oysand · r3 · offset 20 m

Archivo: `examples/field/raw/oysand/examples/Data/Oysand_dx_2m_x1_20m_forward.dat`. 24 canales × 2201 muestras; 1000 Hz.

Registro multicanal; no sitio independiente.

59/143 bins candidatos sin alias espacial. Identidad modal aparente y papel del canal trigger pendientes.

58 bins comparados: mediana absoluta 1.20 m/s; RMS 4.95 m/s. Referencia compuesta del mismo sitio; sin etiquetas individuales ni umbral de exactitud calibrado.

Siguiente revisión: Confirmar canal 1/trigger y modo; comparar sensibilidad a ventanas en la banda admisible.

### Oysand · r4 · offset 30 m

Archivo: `examples/field/raw/oysand/examples/Data/Oysand_dx_2m_x1_30m_forward.dat`. 24 canales × 2201 muestras; 1000 Hz.

Registro multicanal; no sitio independiente.

59/143 bins candidatos sin alias espacial. Identidad modal aparente y papel del canal trigger pendientes.

58 bins comparados: mediana absoluta 2.09 m/s; RMS 6.39 m/s. Referencia compuesta del mismo sitio; sin etiquetas individuales ni umbral de exactitud calibrado.

Siguiente revisión: Confirmar canal 1/trigger y modo; comparar sensibilidad a ventanas en la banda admisible.

### Chevremont · Fuente 0 m · 0m.sg2

Archivo: `examples/field/raw/chevremont/example/Chevremont/0m.sg2`. 48 canales × 4000 muestras; 2000 Hz.

Registro multicanal apilado de 3 impactos; impactos originales no disponibles.

7/48 onsets (14.6 %); 41 abstenciones. Onsets exploratorios sin calibrar; protocolo fijo aplicado sin ajuste a etiquetas.

6/43 anotaciones con onset comparable; 37 abstenciones. Diferencia absoluta media condicional: 26.34 ms. Reloj y definición de llegada sin adjudicar; exactitud no evaluable.

Siguiente revisión: Adjudicar tiempo de fuente y primeras llegadas; completar sidecar antes de ingesta formal.

### Chevremont · Fuente 10 m · 10m.sg2

Archivo: `examples/field/raw/chevremont/example/Chevremont/10m.sg2`. 48 canales × 4000 muestras; 2000 Hz.

Registro multicanal apilado de 3 impactos; impactos originales no disponibles.

7/48 onsets (14.6 %); 41 abstenciones. Onsets exploratorios sin calibrar; protocolo fijo aplicado sin ajuste a etiquetas.

Sin anotaciones del repositorio para esta fuente; coincidencia no evaluable.

Siguiente revisión: Adjudicar tiempo de fuente y primeras llegadas; completar sidecar antes de ingesta formal.

### Chevremont · Fuente 20 m · 20m.sg2

Archivo: `examples/field/raw/chevremont/example/Chevremont/20m.sg2`. 48 canales × 4000 muestras; 2000 Hz.

Registro multicanal apilado de 3 impactos; impactos originales no disponibles.

15/48 onsets (31.2 %); 33 abstenciones. Onsets exploratorios sin calibrar; protocolo fijo aplicado sin ajuste a etiquetas.

Sin anotaciones del repositorio para esta fuente; coincidencia no evaluable.

Siguiente revisión: Adjudicar tiempo de fuente y primeras llegadas; completar sidecar antes de ingesta formal.

### Chevremont · Fuente 30 m · 30m.sg2

Archivo: `examples/field/raw/chevremont/example/Chevremont/30m.sg2`. 48 canales × 4000 muestras; 2000 Hz.

Registro multicanal apilado de 3 impactos; impactos originales no disponibles.

20/48 onsets (41.7 %); 28 abstenciones. Onsets exploratorios sin calibrar; protocolo fijo aplicado sin ajuste a etiquetas.

Sin anotaciones del repositorio para esta fuente; coincidencia no evaluable.

Siguiente revisión: Adjudicar tiempo de fuente y primeras llegadas; completar sidecar antes de ingesta formal.

### Chevremont · Fuente 40 m · 40m.sg2

Archivo: `examples/field/raw/chevremont/example/Chevremont/40m.sg2`. 48 canales × 4000 muestras; 2000 Hz.

Registro multicanal apilado de 3 impactos; impactos originales no disponibles.

15/48 onsets (31.2 %); 33 abstenciones. Onsets exploratorios sin calibrar; protocolo fijo aplicado sin ajuste a etiquetas.

Sin anotaciones del repositorio para esta fuente; coincidencia no evaluable.

Siguiente revisión: Adjudicar tiempo de fuente y primeras llegadas; completar sidecar antes de ingesta formal.

### Chevremont · Fuente 50 m · 50m.sg2

Archivo: `examples/field/raw/chevremont/example/Chevremont/50m.sg2`. 48 canales × 4000 muestras; 2000 Hz.

Registro multicanal apilado de 3 impactos; impactos originales no disponibles.

17/48 onsets (35.4 %); 31 abstenciones. Onsets exploratorios sin calibrar; protocolo fijo aplicado sin ajuste a etiquetas.

Sin anotaciones del repositorio para esta fuente; coincidencia no evaluable.

Siguiente revisión: Adjudicar tiempo de fuente y primeras llegadas; completar sidecar antes de ingesta formal.

### Chevremont · Fuente 60 m · 60m.sg2

Archivo: `examples/field/raw/chevremont/example/Chevremont/60m.sg2`. 48 canales × 4000 muestras; 2000 Hz.

Registro multicanal apilado de 3 impactos; impactos originales no disponibles.

11/48 onsets (22.9 %); 37 abstenciones. Onsets exploratorios sin calibrar; protocolo fijo aplicado sin ajuste a etiquetas.

Sin anotaciones del repositorio para esta fuente; coincidencia no evaluable.

Siguiente revisión: Adjudicar tiempo de fuente y primeras llegadas; completar sidecar antes de ingesta formal.

## Trazabilidad

Probe: 2026-10-08T04:20:45.573918+00:00. Reporte: 2026-10-08T04:38:40.872699+00:00.

65/65 comprobaciones técnicas del probe pasan. Los hashes de originales y código se verifican nuevamente al generar el reporte.

[Reporte interactivo](quality_report.html) · [Datos del reporte](quality_report.json) · [Resultados del probe](results.json)
