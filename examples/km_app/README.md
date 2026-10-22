# Preparación de registros KM para la aplicación local

Para entender cómo se conecta este ejemplo con el código y cómo modificar o ampliar
el sistema, consultar el [manual de arquitectura y mantenimiento](../../docs/manual_mantenimiento.md).

Fecha: 2026-10-19. **Usar la copia TRS para refracción y primeros arribos.**
La aplicación actual admite SEG-Y rev0/1 con sidecar de adquisición validado y
protocolo de la técnica seleccionada. Los originales KM son SEG-2; cambiarles la
extensión no los convierte.

## Cargar KM como TRS

Reiniciar API y worker si estaban abiertos antes de esta ampliación, y recargar la
Web. Seleccionar **TRS · refracción y primeros arribos** en el formulario.

| Campo | Archivo/valor |
| --- | --- |
| Proyecto | `project_id` de `.local/credentials.json` |
| Nombre | `KM 40+672 F1 · TRS EXPLORATORIO` |
| SEG-Y | [km40_f1_trs_exploratory.sgy](demo_trs_f1/km40_f1_trs_exploratory.sgy) |
| Sidecar | [km40_f1_trs_exploratory.sgy.json](demo_trs_f1/km40_f1_trs_exploratory.sgy.json) |
| Protocolo TRS | [protocol.json](demo_trs_f1/protocol.json) |
| QC por traza con estimaciones (recomendado) | [trace_qc_operational.json](demo_trs_f1/trace_qc_operational.json) |
| Receptor excluido | No aplica; se oculta en TRS |

Estos archivos están en `examples/km_app/demo_trs_f1/`. **No seleccionar
assumptions.json como sidecar**: ese archivo documenta la preparación, no es el
contrato de adquisición. No mezclar los sidecars/protocolos MASW de demo_flat_f1
con los TRS de demo_trs_f1.

El ejemplo TRS conserva las hipótesis de cotas/incertidumbre cero y amplitud/stack
provisionales. Como no hay pretrigger, usa 1,5–2 s como referencia posterior de
ruido explícitamente no validada en campo. El dosier conserva abstenciones y
no asigna sigmas temporales sin calibración.
El protocolo QC añade evaluación por traza, espectro/ruido condicional y formas
de onda. Conserva independencia/estacionariedad desconocidas y comparabilidad
instrumental sin verificar; no convierte la referencia tardía en pretrigger.
La Web exige un perfil QC para solicitar el dosier TRS completo.
`trace_qc_operational.json` añade calificación diagnóstica, cobertura, contraste
por bloques, similitud estimada y mesetas digitales; conserva la evaluación
estricta y los metadatos desconocidos. El perfil anterior `trace_qc.json` sigue
disponible. Véanse [criterios, fuentes y límites](../../docs/trs_operational_quality.md).
El backend admite solicitudes sin ese archivo para el recorrido de integridad
básica, que conserva sus limitaciones. Los dosieres anteriores
se conservan sin agregarles resultados retrospectivamente.

La API y el worker deben estar activos. Una ejecución en `QUEUED` todavía no
tiene un dosier nuevo: iniciar el worker con
`.\.venv\Scripts\python.exe -m geoqc_app worker` en otra terminal.
Al terminar, usar el UUID del dosier generado por esa ejecución; abrir el UUID
de un dosier anterior vuelve a mostrar ese resultado histórico.
[Guía completa de carga y alcance TRS](../../docs/app_local_trs.md).

```powershell
.\.venv\Scripts\python.exe tools/build_km_demo.py --technique TRS --output .local/km_trs_nuevo
```

## Acceso al dosier y vigencia de la sesión

En **Sesión local → Token personal**, pegar `operator.token` de
`.local/credentials.json` y pulsar **Conectar**. El token vence a las ocho horas;
no es un UUID y no corresponde al campo **Run**. Para abrir un resultado existente
basta pegar su UUID en **Dosier** y pulsar **Abrir**, con una sesión vigente.

Para emitir otro token del mismo usuario, sin recrear proyecto ni dosieres:

```powershell
$kmCredentials = Get-Content .local/credentials.json -Raw | ConvertFrom-Json
.\.venv\Scripts\python.exe -m geoqc_app token --user-id $kmCredentials.operator.user_id --output .local/operator-token-nuevo.json
```

Copiar entonces `token` del archivo nuevo a **Token personal**. El comando requiere
un nombre de salida que todavía no exista. No imprimir ni compartir el token.

El dosier con QC y estimaciones publicado en la aplicación es
`6f2fd889-6ce5-4394-8e78-7eab9fcf7f1a`. La vista y las exportaciones incorporan
resumen por tendido, criterios, gráficas de calidad/ruido, formas de onda, motivos
por canal, acciones y evidencia pendiente, antes de los primeros arribos.
Copias del mismo resultado: [HTML completo](../../evidence/app_local/km_trs_operational/dossier.html)
y [PDF de calidad](../../evidence/app_local/km_trs_operational/dossier.pdf).
Recargar con Ctrl+F5 para usar la interfaz actualizada y volver a conectar la sesión.

[Abrir directamente el dosier con estimaciones](http://127.0.0.1:8000/?dossier=6f2fd889-6ce5-4394-8e78-7eab9fcf7f1a).
Al conectar el token, el enlace abre automáticamente ese resultado. El botón
**Ver informe completo de calidad** abre en otra pestaña el informe autónomo con
calificaciones por traza/tendido, criterios, gráficas y motivos, sin copiar el
token a la dirección ni depender del worker de exportación. Si se abre un dosier
histórico, **Abrir dosier vigente** lleva al resultado actual de esa adquisición;
el resultado histórico se conserva sin modificaciones.

Resultado del escenario operativo: **2 buenas diagnósticas (ch07/ch11), 22 en
revisión, sin fallas demostradas y sin trazas no evaluables**; cobertura de
comprobaciones 75 %. El tendido es MALA por 8.33 % de buenas según los cortes
90/75. La evaluación estricta conserva NO_EVALUABLE. Esto no equivale a 22
sensores averiados. La [auditoría de sensibilidad](../../evidence/app_local/km_trs_operational_sensitivity/sensitivity.csv)
mantiene la categoría del tendido en ocho variantes; cambian algunos conteos.

La primera continuación del ejemplo conserva una ejecución **offline**, sin publicación
en la base, en [HTML](../../evidence/app_local/km_trs_qc_resume/dossier.html),
[PDF](../../evidence/app_local/km_trs_qc_resume/dossier.pdf) y
[JSON](../../evidence/app_local/km_trs_qc_resume/dossier.json). Las exportaciones
presentan la calificación por traza y registro/tendido antes del JSON científico.
F1 tiene 24 trazas con evidencia pendiente, cero fallas demostradas e intervalo
de buenas de 0–100 %: el tendido es **NO_EVALUABLE** con este protocolo.
Esto no acredita que las trazas sean buenas ni que sean malas. Repetibilidad y
reciprocidad continúan pendientes de grupos de impactos y pares físicos explícitos.

## Copia MASW anterior: exploración de dispersión

El usuario indicó usar cero donde no se reportaron cotas e incertidumbres.
Se generó [demo_flat_f1](demo_flat_f1/manifest.json) con los originales intactos y
las muestras conservadas exactamente. Los ceros son una idealización explícita,
no datos topográficos medidos ni una declaración de precisión perfecta.

| Campo de la Web | Archivo o valor |
| --- | --- |
| Técnica | MASW · dispersión superficial |
| Proyecto | `project_id` de `.local/credentials.json`, no `0001` |
| Nombre | `KM 40+672 F1 · EXPLORATORIO` |
| SEG-Y | [km40_f1_exploratory.sgy](demo_flat_f1/km40_f1_exploratory.sgy) |
| Sidecar | [km40_f1_exploratory.sgy.json](demo_flat_f1/km40_f1_exploratory.sgy.json) |
| Protocolo | [protocol.json](demo_flat_f1/protocol.json) |
| Receptor excluido | `ch24` |

Los tres archivos están en `examples/km_app/demo_flat_f1/`. Conectar como operador,
mantener API/worker funcionando y pulsar `Cargar y procesar`. La exclusión ch24 es
una variante de sensibilidad; no declara un geófono malo o un canal de trigger.

Se adopta correspondencia por CHANNEL_NUMBER/orden de trazas, un golpe por archivo
y muestras en voltios **como hipótesis exploratorias**, sin confirmar por ello el
significado de STACK=0. Los valores originales de cabecera siguen conservados.
Se reutiliza un registro TRS para explorar MASW aparente; no se certifica la
campaña como adquisición MASW. El sidecar y el protocolo registran estas salvedades;
el dosier conserva el texto en la procedencia de su protocolo.

La referencia nominal de tiempo sigue siendo interruptor del mazo sin pretrigger;
fuente x=-15 m, receptores x=0..115 m, y=z=0 en el modelo local. Incertidumbre cero
significa que este cálculo omite su propagación, no que se haya medido como nula.

Se corrigió además el extremo de la ventana propuesta: **[0, 2 s)** incluye las
16000 muestras y conserva los bins FFT solicitados. Usar 1,999875 s como extremo
exclusivo quitaba la última muestra e impedía ejecutar ese protocolo.

Para generar otra copia sin sobrescribir esta:

```powershell
.\.venv\Scripts\python.exe tools/build_km_demo.py --output .local/km_demo_nuevo
```

La [configuración de hipótesis](demo_flat_f1/assumptions.json) distingue explícitamente
confirmación de configuración exploratoria de verificación de metadatos de campo.
La preparación parcial anterior se conserva como historial de información pendiente.

Verificación ejecutada: **6 pruebas satisfactorias en 10,32 s**, sin skips:
conversión/preparación y copia exploratoria. Incluye carga y procesamiento por
worker real en un esquema PostgreSQL aislado, con SUCCEEDED, hipótesis preservadas,
suficiencia NOT_DEMONSTRATED y elegibilidad false. Ruff pasó.
[Reporte](../../evidence/app_local/km_demo_tests.xml).

```powershell
.\.venv\Scripts\python.exe -m pytest tools/tests/test_km_demo.py tools/tests/test_prepare_km_app.py -q --junitxml=evidence/app_local/km_demo_tests.xml
```

## Notas encontradas

- [KM 40+672: Readme](<../../KM 40+672/Datos/Readme.txt>): TRS con separación de
  5 m, nueve fuentes cada 15 m y 3–4 golpes por fuente. Declara explícitamente
  que la topografía está pendiente.
- [KM 52+500: Observaciones Sísmica](<../../KM 52+500/Datos/Sísmica/Observaciones Sísmica.txt>): 24 geófonos
  a 2,5 m, once fuentes y adquisición MAM.
- No se encontró otro documento de notas en los ZIP originales ni un Readme
  equivalente para KM 44+552.

Las notas respaldan algunos parámetros de adquisición. No identifican componente
vertical, fuente usada, convención temporal del trigger, unidad de amplitud,
semántica de apilamiento, CRS ni incertidumbre de geometría. Tampoco autorizan
reclasificar automáticamente una adquisición TRS/MAM como MASW Rayleigh vertical.

Actualización del 19 de octubre: el usuario confirmó geófonos verticales para el
caso piloto. Se guardó `component=Z` en
[la preparación parcial de KM 40+672/F1](preparation/KM_40_672_F1.metadata.in_progress.json),
sin marcar como confirmados los demás campos.

El usuario confirmó también fuente de **mazo/HAMMER**. La
[investigación de cabeceras y manual](header_research.md) documenta qué información
puede recuperarse del formato. El usuario confirmó **DAQLink 4** como equipo;
la configuración de adquisición/exportación sigue pendiente de verificación.
El [análisis de golpes/apilamiento](stack_analysis.md) examinó los 29 archivos de
KM 40+672: conteos y comparaciones favorecen golpes individuales como hipótesis,
sin certificar el número de golpes de cada archivo ni su escala física.
También confirmó interruptor del mazo y ausencia de pretrigger. La preparación
parcial ya declara cero nominal de tiempo en ese pulso, de acuerdo con DELAY=0
en las cabeceras; no se ha calibrado la latencia del interruptor.

El usuario confirmó después **15 m como offset inicial de F1, antes del primer
geófono sobre la prolongación del tendido**. La preparación parcial usa un eje
local con receptor 1 en x=0, receptores cada 5 m hasta x=115 y fuente F1 en x=-15 m:
offsets horizontales de 15 a 130 m. `y=0` define el eje local; las cotas y sus
incertidumbres continúan sin completar. Esta ubicación procede de la declaración
del usuario; el Readme documenta separación entre fuentes, no explícitamente el
offset inicial. No se han asignado posiciones a F2–F9.

Se revisaron también los tres KMZ de `Track`: contienen referencias de inicio,
fin y/o centro del tendido TRS; no identifican cada disparo F1–F9 ni cada geófono.
En KM 40+672, las cabeceras de los primeros registros de F1 a F9 repiten
`SOURCE_LOCATION=0.0` y receptores desde `0 1 0` hasta `115 1 0`. Ese `1` no
confirma por sí mismo un offset físico de un metro: falta verificar la convención
de coordenadas. El KMZ no resuelve esa ambigüedad. Sus coordenadas tienen tercer
valor cero y no aportan la topografía pendiente indicada por el Readme.

## Archivos generados

[Inventario](preparation/inventory.json): **152 originales**, con SHA-256, tamaño,
canales, muestreo y valores originales de cabeceras; incluye las dos notas
decodificadas y sus hashes. Clasificación por carpetas: 99 registros activos/TRS
y 53 MAM pasivos. La categoría de carpeta no certifica técnica, componente ni
identidad modal.

| Sitio | Registros | Plantilla seleccionada | Protocolo propuesto |
| --- | ---: | --- | --- |
| KM 40+672 | 29 | [F1 / 250122_205932](preparation/KM_40_672_F1.metadata.template.json) | [JSON DRAFT](preparation/KM_40_672_F1.protocol.draft.json) |
| KM 44+552 | 32 | [F1 / 250123_183324](preparation/KM_44_552_F1.metadata.template.json) | [JSON DRAFT](preparation/KM_44_552_F1.protocol.draft.json) |
| KM 52+500 | 91 | [F1 / 250124_180925](preparation/KM_52_500_F1.metadata.template.json) | [JSON DRAFT](preparation/KM_52_500_F1.protocol.draft.json) |

Las plantillas **no son sidecars válidos**: conservan `null` donde no existe
confirmación. `header_candidates_not_validated` contiene valores originales como
`RECEIVER_LOCATION`, `SOURCE_LOCATION`, `DELAY`, `DESCALING_FACTOR`, `STACK` y
`CHANNEL_NUMBER`. Según el estándar SEG-2, `UNITS=NONE` describe las unidades
lineales de coordenadas, no la unidad de amplitud. La amplitud requiere revisar
DESCALING_FACTOR y STACK; el valor STACK=0 impide aplicar directamente la fórmula
estándar de conversión a voltaje.
`DELAY=0` no prueba sincronización con el golpe; `STACK=0` no significa cero golpes.
La separación entre fuentes no fija por sí sola la ubicación de la primera.

Los protocolos son propuestas exploratorias: ventana del registro, 8–80 Hz,
100–1000 m/s, dos direcciones, HANN e identidad APPARENT. No son banda validada,
calibración de campo ni parámetros ajustados a calidad observada. Revisarlos
contra los metadatos antes de usarlos. No se genera protocolo para MAM pasivo.

## Completar y convertir un registro

1. Copiar una plantilla a un nombre nuevo, por ejemplo `km40_f1.reviewed.json`.
2. Completar `context` con metadatos verificados: técnica/onda/componente,
   identificadores de receptores en orden de canales, fuente, amplitud y stack;
   geometría completa en metros con CRS, incertidumbres y procedencia; referencia
   temporal y procedencia de su relación con el golpe. Un sistema local es válido
   si está declarado y documentado; no se asignan cotas cero ni incertidumbres
   ficticias para sustituir topografía ausente.
3. Registrar en `review_notes` la fuente de esa confirmación. Solo después,
   establecer `confirmed=true`. Esa marca es una declaración del responsable,
   no una verificación automática de campo.
4. Ejecutar desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe tools/prepare_km_app.py convert --technique TRS --metadata examples/km_app/km40_f1.reviewed.json --output examples/km_app/converted/km40_f1_trs.sgy
```

La herramienta valida el contrato, hash del original y técnica solicitada. Rechaza
MAM y mezclas entre declaración TRS/MASW sin cambiarlas. Conserva el contexto revisado junto al
archivo de metadatos y usa el lector validado para construir el Shot. Genera el
SEG-Y IEEE y su `.sgy.json`, comprueba la admisión del backend y relee las muestras.
No aplica `DESCALING_FACTOR`, filtros, remuestreo ni recorte. Rechaza pérdidas de
precisión float32 o tiempos no representables en el formato de destino. Las
coordenadas de cabecera se cuantizan a milímetros según el escritor existente;
la geometría original queda en el sidecar. No sobrescribe ni modifica originales.

## Qué colocar en la Web

- **Proyecto (UUID):** `project_id` de `.local/credentials.json`; `0001` no es válido.
- **Nombre:** por ejemplo `KM 40+672 · F1 · prueba diagnóstica`.
- **SEG-Y:** el `.sgy` convertido después de confirmar los metadatos.
- **Sidecar:** su `.sgy.json`, no la plantilla de preparación.
- **Protocolo:** el JSON de la técnica elegida; para el ejemplo TRS, `demo_trs_f1/protocol.json`.
- **Receptor excluido:** solo en MASW; un ID declarado en `acquisition.receiver_ids`, elegido
  explícitamente para la prueba de sensibilidad. No se asume que sea trigger o
  receptor defectuoso. En MASW se necesita uno por registro en el mismo orden; en TRS no aplica.

Para reproducir el recorrido sintético MASW, el ejemplo E5 existente conserva
sus propios archivos y parámetros:

| Campo | Archivo/valor desde la raíz |
| --- | --- |
| SEG-Y | `examples/e5/masw_plane.sgy` |
| Sidecar | `examples/e5/masw_plane.sgy.json` |
| Protocolo | `examples/e5/protocol.json` |
| Receptor excluido | `r0` |

E5 comprueba el recorrido de la aplicación; no representa los sitios KM.

## Reproducción y comprobaciones

```powershell
.\.venv\Scripts\python.exe tools/prepare_km_app.py inspect --output .local/km_preparation_nueva
.\.venv\Scripts\python.exe -m pytest tools/tests/test_prepare_km_app.py -q --junitxml=evidence/app_local/km_preparation_tests.xml
.\.venv\Scripts\python.exe -m ruff check tools/prepare_km_app.py tools/tests/test_prepare_km_app.py
```

El inventario recorre todos los originales disponibles sin modificarlos y rechaza
sobrescribir una preparación. **Cuatro pruebas satisfactorias en 1,43 s**, sin
skips, comprueban plantillas bloqueadas, separación MAM, conservación de muestras
y tiempo en una conversión sintética explícita, hashes, rechazo de TRS y ausencia
de inferencia del trigger. Ruff pasó.
[Reporte](../../evidence/app_local/km_preparation_tests.xml).
Esa ejecución inicial no convirtió ningún KM con metadatos de campo verificados.
La copia exploratoria posterior descrita al inicio sí se convirtió y procesó,
con las hipótesis explícitas y sin acreditar validación de campo.
