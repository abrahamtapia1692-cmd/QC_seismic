# TRS local: carga, primeros arribos y revisión

Fecha: 2026-10-19. Ampliación solicitada a APP-LOCAL-0.1.
[Decisión de alcance](adr/0005-local-trs-diagnostic.md).

La Web distingue **TRS: refracción y primeros arribos** de **MASW: dispersión
superficial**. Cada run congela su técnica, protocolo y motor. El worker comprueba
que el sidecar declare la técnica/onda solicitadas; no convierte automáticamente
TRS en MASW. Las adquisiciones ya cargadas y dosieres anteriores se conservan.

Las ejecuciones nuevas integran QC común por traza, evaluación del registro y
del conjunto, formas de onda y picking/ramas TRS. Opcionalmente admiten un JSON
QC con ventanas y protocolos de ruido/similitud explícitos. La
[comparación metodológica](app_local_trs_methodology.md) identifica también las
condiciones pendientes de repetibilidad, reciprocidad, calibración y suficiencia.

## QC por traza

En el formulario TRS, seleccionar `examples/km_app/demo_trs_f1/trace_qc_operational.json` en
**QC por traza JSON**, requerido por la Web para el dosier completo. El contrato
del backend conserva el recorrido opcional de integridad básica. Este archivo contiene `protocol` (QCProtocol), `noise`
(NoiseProtocol opcional) y `config` (perfil de proyecto opcional). Sin un perfil
de proyecto no se inventan objetivo, profundidad ni umbrales de aceptación;
la evaluación diagnóstica usa la política de trazas DRAFT del protocolo.

Si se omite el archivo, el worker construye únicamente la ventana envolvente del
registro desde los relojes de las muestras. Ejecuta QC común e integridad digital;
SNR, clipping y similitud conservan sus estados de aplicabilidad y faltantes.
El protocolo resultante y su origen quedan congelados en el dosier.

En KM la referencia posterior [1.5,2) s permite diagnósticos **condicionales** de
ruido, con potencias por bloques, PSD, banda LF soportada y líneas candidatas.
No es pretrigger ni demuestra transferencia a la señal. SNR válida conserva sus
guardas de independencia/estacionariedad; clipping requiere rails/escala. La
similitud conserva comparabilidad no verificada en este ejemplo. La coherencia LF
entre canales contiguos informa el soporte insuficiente cuando corresponde.

La vista muestra evaluación por traza, intervalo de porcentaje bueno, forma de
onda y examen de canal antes de los resultados del picker. La envolvente min/max
y el máximo por grupo espectral son reducciones para presentación; los cálculos
usan muestras completas y el JSON científico conserva los diagnósticos nativos.
`qc-traces` pagina proyecciones de hasta 256 KiB con unidades y digest del dosier.
El conjunto suma trazas y no promedia porcentajes entre registros.

El perfil `trace_qc_operational.json` añade `operational_policy` y mantiene la
evaluación estricta sin cambios. Sus estimaciones y reglas de cobertura están en
[la metodología diagnóstica](trs_operational_quality.md). `trace_qc.json` sigue
disponible para el recorrido anterior. Los nuevos resultados muestran primero
calificación diagnóstica condicional y después QC estricto, sin mezclar sus
conteos ni presentar la cobertura como confianza estadística.

### Dosier visual de calidad

La vista integra el recorrido de `evidence/trace_quality` usando los resultados
de la adquisición seleccionada: resumen por registro/tendido y distribución de
calidad; criterios y umbrales congelados; ventanas y condiciones de aplicabilidad;
gráficas por canal de SNR válida/condicional, clipping, similitud/consenso,
RMS/MAD, razón LF y potencias por bloques; candidatos espectrales; formas de onda;
tabla filtrable con motivos y acciones; inspección de canal y PSD; comparación
visual con canales contiguos; evidencia pendiente y cobertura metodológica.
Los primeros arribos y las ramas se presentan después de ese recorrido QC.

Los conteos visuales usan `assessment_grade`, no la categoría histórica que
agrupaba faltantes como regulares. F1 tiene 21 canales en revisión y tres solo
no evaluables; los 24 conservan evidencia pendiente. El conjunto permanece
NO_EVALUABLE con intervalo de buenas 0–100 %, sin fallas demostradas.

El HTML exportado es autónomo, incluye los mismos renderizadores y funciona sin
servidor ni credenciales. Su CSP habilita únicamente el script incorporado por
hash; los datos se presentan como texto. El PDF presenta criterios, gráficas,
formas de onda, diagnóstico por canal, cobertura, arribos y procedencia. Los
vectores completos se conservan en JSON/CSV y dentro del HTML; el PDF los resume
para su lectura. Los hashes de recursos y proyecciones forman parte de la
referencia del renderizador. La exportación nunca recalcula calidad ni picking.

Ejemplo publicado: dosier `6518ff41-fef1-4e6b-8721-342841e4e905`.
Copias del mismo digest: [HTML](../evidence/app_local/km_trs_quality_full/dossier.html)
y [PDF](../evidence/app_local/km_trs_quality_full/dossier.pdf).
Los controles sintéticos y los datos Oysand/Chevremont de la referencia mantienen
sus propios resultados; no se incorporan como mediciones del KM. El filtrado
experimental, la repetibilidad y la reciprocidad señalan explícitamente la
evidencia o los grupos físicos que todavía requieren.

Los dosieres históricos sin QC siguen legibles y no se modifican. Para incluir
la nueva etapa se crea otro run sobre la misma revisión de adquisición. Hay que
reiniciar API y worker al actualizar el código; un run pendiente fijado a otra
versión del motor puede rechazarse con `ENGINE_MISMATCH` y requiere una nueva
ejecución sobre la revisión vigente.

## Cargar el ejemplo KM como TRS

Si API/worker estaban funcionando antes de esta ampliación, detenerlos con Ctrl+C
en sus terminales y volver a iniciarlos desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m geoqc_app serve
```

En otra terminal:

```powershell
.\.venv\Scripts\python.exe -m geoqc_app worker
```

Recargar la página `http://127.0.0.1:8000/` y conectar el token del operador.
No es necesario crear credenciales/proyecto otra vez. Esta ampliación no cambia
el esquema SQL ni exige recalcular resultados anteriores.

| Campo | Archivo/valor |
| --- | --- |
| Técnica | **TRS · refracción y primeros arribos** |
| Proyecto | `project_id` de `.local/credentials.json` |
| Nombre | `KM 40+672 F1 · TRS EXPLORATORIO` |
| SEG-Y | `examples/km_app/demo_trs_f1/km40_f1_trs_exploratory.sgy` |
| Sidecar | `examples/km_app/demo_trs_f1/km40_f1_trs_exploratory.sgy.json` |
| Protocolo TRS | `examples/km_app/demo_trs_f1/protocol.json` |
| Exclusión de receptor | No aplica a TRS; el campo se oculta |

Pulsar `Cargar y procesar`. Al llegar a SUCCEEDED, elegir `Primeros arribos TRS`
o `Ramas tiempo-distancia TRS` en el detalle del dosier. Se muestran offsets en
metros y onsets/sigmas en segundos, con estados, motivos y valores nulos originales.
No se inventa una llegada donde el picker se abstiene.

`assumptions.json` es la preparación completa con hipótesis, **no es el sidecar**.
La Web detecta ese error antes de crear adquisición/carga. También detecta
sidecars/protocolos de una técnica distinta a la seleccionada. El servidor sigue
validando el contrato completo de manera independiente.

Los archivos de `demo_flat_f1` corresponden al recorrido anterior MASW; para TRS
usar los de `demo_trs_f1`. Los originales SEG-2 continúan intactos.

Una [ejecución offline del ejemplo](../evidence/app_local/trs_demo_dossier.json)
produjo 5 onsets sin calibrar, 17 abstenciones AMBIGUOUS y 2 MISSING. Es un
snapshot diagnóstico, no una publicación en la base de desarrollo ni garantía
de identificar las 24 llegadas. Las abstenciones requieren revisión de señal y
protocolo; no se relajan controles para rellenar los tiempos faltantes.

## Motor y supuestos

El adaptador TRS usa `trs_diagnostics` del núcleo: STA/LTA y refinamiento AIC,
abstenciones nativas y ajuste de ramas. No introduce otro picker ni calibra
incertidumbres con estos datos. Sin calibración, `sigma_s` permanece null.
La revisión ACCEPTED sigue siendo una anotación diagnóstica y no modifica el
resultado, la suficiencia NOT_DEMONSTRATED ni la elegibilidad false.

Para KM F1 se conservan las hipótesis acordadas: cotas cero, incertidumbre cero
como omisión de su propagación, orden de receptores según cabecera y un golpe por
archivo con muestras interpretadas provisionalmente como voltios. Estas hipótesis
están en el sidecar y protocolo, sin cambiar STACK=0 del original.

No hay pretrigger. Para este ejemplo se declara ruido de referencia en **1,5–2 s**
y búsqueda en **0–0,5 s** mediante `noise_position=DECLARED_POST_SIGNAL`. Esa
ventana final se asume sin señal útil, pero no está validada en campo. El dosier
incluye `POST_SIGNAL_NOISE_WINDOW_NOT_FIELD_VALIDATED` como evidencia pendiente.
No se simula ruido anterior al golpe ni se trasladan muestras en el tiempo.

El valor por defecto del núcleo sigue siendo ruido previo a búsqueda. La opción
posterior requiere una declaración explícita y rechaza ventanas solapadas. El
valor por defecto se omite al serializar para conservar la forma histórica de
los protocolos; los hashes de estimador/motor cambian con las fuentes de código,
por lo que calibraciones y trabajos fijados a otra versión requieren su entorno.

La primera integración local no admite declarar verificado un modelo horizontal
de dos capas ni habilita inversión/tomografía. Los ajustes tiempo-distancia no
constituyen por sí solos identificación geológica ni velocidades certificadas.

## Contratos y lectura

`POST /v1/processing-runs` acepta `technique=TRS`, un `TRSProtocol` y ninguna
exclusión MASW. Las solicitudes MASW anteriores conservan su técnica por defecto,
forma serializada y semántica de idempotencia. Se mantienen leases, fencing,
publicación verificada, autorización, revisión OCC y almacenamiento de originales.

El dosier TRS usa `app-trs-dossier-0.1` y scope `LOCAL_TRS_DIAGNOSTIC_ONLY`.
La publicación comprueba que esquema/método correspondan al run. El detalle usa
`geoqc-trs-detail-1`, cursores firmados y presupuesto de 256 KiB:

- `/v1/dossiers/{id}/records`: resumen, estados de picking, geometría/procedencia.
- `/v1/dossiers/{id}/records/{index}/arrivals`: llegadas nativas por receptor.
- `/v1/dossiers/{id}/records/{index}/branches`: ramas y límites de interpretación.

Los filtros de frecuencia/dirección se reservan a MASW; TRS los rechaza. ETag y
autorización siguen vigentes. JSON, CSV, HTML y PDF conservan el método TRS y sus
valores completos; exportar sigue siendo un trabajo derivado separado.

## Verificación

```powershell
.\.venv\Scripts\python.exe -m pytest tools/tests/test_app_trs.py tools/tests/test_app_web.py tools/tests/test_app_backend.py tools/tests/test_app_dossiers.py tools/tests/test_app_exports.py tools/tests/test_km_demo.py tools/tests/test_prepare_km_app.py -q --junitxml=evidence/app_local/trs_app_regression_tests.xml
.\.venv\Scripts\python.exe -m pytest tests/unit/test_e4_boundaries.py tests/unit/test_e4_cli.py tests/synthetic/test_e4_picking.py -q -o junit_family=xunit1 --junitxml=evidence/app_local/trs_scientific_regression_tests.xml
.\.venv\Scripts\python.exe -m ruff check geoqc geoqc_app tools/build_km_demo.py tools/prepare_km_app.py tools/tests/test_app_trs.py tools/summarize_app_backend.py
.\.venv\Scripts\python.exe -m mypy geoqc geoqc_app
```

Las pruebas TRS usan PostgreSQL y worker reales, comparación con el JSON nativo
sin excluir campos científicos, paginación completa de 24 llegadas, rechazo de
mezcla de técnicas, revisión sin cambios al resultado, exportación CSV/HTML/PDF y
Chromium desde carga a detalle. La suite compartida comprueba regresión de MASW.
El perfil científico y su aceptación de campo mantienen sus gates pendientes.

Resultado ejecutado: **87 pruebas de aplicación en 316,85 s** y **21 regresiones
científicas TRS en 20,81 s**, todas satisfactorias, sin fallos, errores ni skips.
La primera incluye cinco casos nuevos de TRS y las regresiones compartidas.
Ruff pasó y mypy verificó 84 archivos. El wheel se construyó correctamente.

La [ejecución archivada](../evidence/app_local/backend/runs/20261020T041415Z_53e14d68/execution.json)
conserva ambos JUnit, versiones y hashes de código/recursos/entradas TRS, además
de snapshots offline [CSV](../evidence/app_local/backend/runs/20261020T041415Z_53e14d68/trs_snapshot.csv),
[HTML](../evidence/app_local/backend/runs/20261020T041415Z_53e14d68/trs_snapshot.html) y
[PDF](../evidence/app_local/backend/runs/20261020T041415Z_53e14d68/trs_snapshot.pdf).
Esos snapshots derivan del JSON offline; no publican resultados en la base de
desarrollo. El colector archiva reportes ya ejecutados y captura hashes al archivar;
no certifica por sí solo el origen de los reportes. No se ejecutó toda la suite
científica ni se acreditan gates adicionales.
