# Exportaciones locales del dosier MASW

Fecha: 2026-10-15. Avance del paso 3 de [APP-LOCAL-0.1](../app.md).

Actualización del 19 de octubre: el renderizador admite también el
[dosier TRS local](app_local_trs.md), con su método y primeros arribos, conservando
las transacciones y verificaciones descritas aquí.

CSV, HTML y PDF son derivados de un dosier científico confirmado. Cada exportación
identifica el dosier, su digest, el SHA-256 del JSON de origen y el código/versiones
del renderizador. No invoca el adaptador MASW, no modifica el dosier ni incorpora
dictámenes humanos posteriores. Un dosier histórico puede exportarse con su digest
original; eso no lo convierte en resultado vigente para revisar.

## Formatos

| Formato | Contenido |
| --- | --- |
| CSV UTF-8 | Snapshot completo como `scientific_digest,json_pointer,value_json`; cada valor conserva su tipo JSON, incluidos `null` y colecciones vacías |
| HTML | Snapshot JSON completo escapado, con estado DRAFT y CSP sin scripts ni recursos externos |
| PDF | Snapshot JSON completo paginado, digest/estado en cada página; Unicode representado mediante escapes JSON para evitar depender de fuentes locales |

Son exportaciones técnicas del snapshot, todavía sin maquetación de informe de
campo, gráficas ni tablas de presentación. Las magnitudes y unidades mantienen los
nombres originales. `native_diagnostics` y la usabilidad de rejilla permanecen en
campos distintos; no se transforman bins en porcentajes de calidad, sensibilidad
en sigma ni bandas aparentes en bandas validadas. CSV/HTML conservan texto Unicode;
PDF muestra los escapes `\u` de las cadenas Unicode. El dictamen humano se consulta
en ReviewCase, separado de estos archivos.

El renderizador exige un digest científico verificable y el esquema local conocido,
con suficiencia NOT_DEMONSTRATED y elegibilidad falsa. Los textos del dosier se
escapan en HTML; las cadenas de CSV se codifican como valores JSON, evitando
emitir texto de procedencia directamente como fórmulas de una hoja de cálculo.

## Instalación y ejecución

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[app,app-export,app-test]"
.\.venv\Scripts\python.exe -m geoqc_app migrate
.\.venv\Scripts\python.exe -m geoqc_app export-worker
```

`app-export` aporta ReportLab para PDF; CSV y HTML usan la biblioteca estándar.
ReportLab no se añade a las dependencias científicas. `app-test` incorpora pypdf
para comprobar el texto del PDF. Sin ReportLab, solicitar PDF puede crear el trabajo,
que termina FAILED con `EXPORT_DEPENDENCY_MISSING`; CSV/HTML siguen disponibles.

La migración `003_exports.sql` añade exports e historial de intentos, sin cambiar
dosieres o revisiones. `/health` exige ahora el esquema 3. El worker científico
continúa con `worker`; `export-worker` atiende solo exportaciones y también despacha
outbox. Ambos se ejecutan separados del proceso HTTP. `export-worker --once`
atiende como máximo una exportación.

## Contrato HTTP

| Ruta | Semántica |
| --- | --- |
| POST /v1/dossiers/{id}/exports | Body `{"format":"CSV"}`, `HTML` o `PDF`; requiere Idempotency-Key; 202 con identidad/estado PENDING |
| GET /v1/exports/{id} | Estado, intento, error seguro, referencia de renderizador y manifiesto cuando está READY |
| POST /v1/exports/{id}/retries | Reencola un FAILED con presupuesto disponible; Idempotency-Key obligatorio |
| GET /v1/exports/{id}/content | Descarga autorizada con MIME/nombre del formato; 409 si no está READY |

Cualquier miembro actual que pueda leer el dosier puede solicitar una exportación.
Cada comando, consulta y descarga comprueba proyecto/objeto. Repetir una clave con
el mismo contenido recupera la respuesta original; otro formato bajo la misma
clave devuelve 409. La respuesta idempotente original puede decir PENDING después
de que el trabajo termine: GET es la fuente del estado actual.

## Durabilidad y fallos

La cola tiene PENDING, RUNNING, READY y FAILED. Se reclama en PostgreSQL con
`FOR UPDATE SKIP LOCKED`, lease y token exclusivo. Un worker muerto permite reclamar
el intento vencido; el anterior no puede renovar, fallar ni publicar el trabajo.
Los intentos quedan registrados y se limitan por `max_attempts` (tres por defecto).

El renderizador se ejecuta en un hijo con límites de timeout y RSS tomados de la
configuración local actual, un único render concurrente por worker y 64 MiB de
salida máxima. Se verifican los hashes del origen antes/después de renderizar,
el digest científico, la referencia de renderizador y el hash de salida.

El publicador comprueba origen/salida y confirma artefacto, manifiesto, estado READY,
intento y outbox en una transacción. También comprueba el vencimiento del lease al
actualizar el estado, después de la verificación de archivos. Si pierde vigencia,
la inserción provisional de artefacto y el manifiesto se revierten. Los archivos
sin referencia quedan para reconciliación, sin cambiar el resultado científico.

Un fallo termina FAILED y requiere reintento explícito; no recalcula ciencia.
Los reintentos conservan el renderizador fijado. Si cambian código o dependencias,
una referencia incompatible falla con `EXPORT_RENDERER_MISMATCH`: se debe crear una
exportación nueva con la versión actual. Agotar intentos también exige una nueva
exportación. Los errores de exportación no cambian SUCCEEDED del run ni ReviewCase.

La reconciliación rechaza borrado mientras haya exportaciones PENDING/RUNNING y
conserva todos los artefactos referenciados, incluidos los derivados READY. No se
eliminan carpetas `export_attempts`; su limpieza sigue pendiente junto con el
control robusto del árbol de procesos y las mediciones de capacidad.

## Verificación

```powershell
.\.venv\Scripts\python.exe -m pytest tools/tests/test_app_exports.py -q --junitxml=evidence/app_local/backend_export_tests.xml
.\.venv\Scripts\python.exe -m pytest tools/tests/test_app_backend.py -q --junitxml=evidence/app_local/backend_export_regression_tests.xml
.\.venv\Scripts\python.exe -m ruff check geoqc_app tools/tests/test_app_exports.py tools/tests/test_app_backend.py tools/summarize_app_backend.py
.\.venv\Scripts\python.exe -m mypy geoqc geoqc_app
```

Las pruebas usan PostgreSQL real y esquemas aislados. Cubren formato y digest,
JSON nulo/tipos/unidades, HTML escapado, PDF leído por pypdf, descarga/permisos,
idempotencia, fallo de disco y reintento sin modificar ciencia/revisión, reclamación
concurrente, presupuesto de intentos, fuente dañada, timeout, lease vencido durante
la publicación y muerte/reinicio de un proceso real de exportación.

Resultado ejecutado: **15 pruebas de exportación** satisfactorias en **84,43 s** y
**37 regresiones del backend** satisfactorias en **97,29 s**, sin fallos, errores
ni skips. Ruff pasó para backend, pruebas y colector; mypy verificó **80 archivos**
de `geoqc` y `geoqc_app`. La base local también se migró al esquema 3 y el comando
`export-worker --once` se ejecutó correctamente sin trabajos pendientes.

La [ejecución archivada](../evidence/app_local/backend/runs/20261016T050954Z_1b949d6f/execution.json)
conserva los dos JUnit, hashes y versiones, además de ejemplos del snapshot E5:
[CSV](../evidence/app_local/backend/runs/20261016T050954Z_1b949d6f/e5_snapshot.csv),
[HTML](../evidence/app_local/backend/runs/20261016T050954Z_1b949d6f/e5_snapshot.html) y
[PDF](../evidence/app_local/backend/runs/20261016T050954Z_1b949d6f/e5_snapshot.pdf).
Estos ejemplos se renderizan desde el dosier E5 archivado; no son una publicación
en la base de desarrollo ni validación de campo. El colector no ejecuta pruebas
y sus hashes capturan las fuentes al archivar; no prueban por sí solos el origen del reporte.

Para archivar ambos reportes de una nueva ejecución, con ejemplos opcionales:

```powershell
.\.venv\Scripts\python.exe tools/summarize_app_backend.py --report evidence/app_local/backend_export_tests.xml --report evidence/app_local/backend_export_regression_tests.xml --scope LOCAL_DOSSIER_EXPORTS --example-dossier evidence/app_local/adapter/runs/20261015T045324Z_2750c032/e5_dossier.json
```

APP-11 incorpora comprobaciones de fallos de exportación. El hito integrado sigue
pendiente de Web, mediciones operativas y demostración completa. La
[paginación del detalle ya tiene implementación propia](app_local_detail.md).
No se acreditan gates científicos ni aceptación operativa de campo.
