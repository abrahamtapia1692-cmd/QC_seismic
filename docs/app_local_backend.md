# Backend MASW local: implementación y comprobaciones

Fecha: 2026-10-15. Alcance: avance del paso 3 de [APP-LOCAL-0.1](../app.md).

El paquete `geoqc_app` implementa API FastAPI, PostgreSQL, almacenamiento local
verificado y worker con cálculo en un subproceso. El paquete científico conserva
su independencia. El [cliente Web local](app_local_web.md) ya consume estos contratos;
el cierre del hito integrado sigue pendiente.

La [ampliación TRS local](app_local_trs.md) reutiliza estas transacciones y añade
técnica/protocolo/dosier propios, con comprobación de método al publicar.

## Recorrido disponible

Crear adquisición, cargar waveform SEG-Y y sidecar, confirmar hashes, congelar
revisión, encolar run, ejecutar worker, consultar dosier y registrar una anotación
humana condicionada por ETag. Los comandos guardan respuesta y hash del contenido
en la misma transacción que su efecto; los reintentos revalidan autorización.

El worker reclama trabajos con `FOR UPDATE SKIP LOCKED`, lease y token exclusivo.
Un intento vencido o cancelado pierde el permiso de heartbeat, fallo y publicación.
La publicación confirma artefacto, dosier, ReviewCase, estado y outbox juntos en
PostgreSQL, después de verificar el archivo. Los originales se promueven con un
enlace exclusivo y se identifican por SHA-256 y tamaño.

La raíz de almacenamiento queda ligada a la configuración de base/esquema mediante
un marcador publicado sin sobrescritura. Otra configuración no puede reutilizarla.
Los comandos y las escrituras de referencias toman un bloqueo compartido de
PostgreSQL; el reconciliador toma el bloqueo exclusivo hasta terminar su inventario
y borrado. Esto evita confirmar referencias nuevas durante la selección de huérfanos.

Cada decisión requiere rol OFFICE_REVIEWER, digest vigente, caso pendiente y
versión coincidente. ACCEPTED exige salvedades y conserva suficiencia
NOT_DEMONSTRATED y elegibilidad falsa. El administrador no recibe el rol de
revisor implícitamente. Las identidades de desarrollo usan bearer tokens aleatorios
con hash en base y caducidad de ocho horas.

## Ejecución local en Windows

Requiere PostgreSQL instalado; el helper usa por defecto los binarios de la versión
18. Configuración, credenciales, cluster y archivos de ejecución viven en `.local/`,
excluido de Git. No compartir esos archivos.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[app,app-test]"
.\.venv\Scripts\python.exe tools/start_local_postgres.py
.\.venv\Scripts\python.exe -m geoqc_app migrate
.\.venv\Scripts\python.exe -m geoqc_app bootstrap
.\.venv\Scripts\python.exe -m geoqc_app serve
```

En otra terminal, desde el mismo entorno y repositorio:

```powershell
.\.venv\Scripts\python.exe -m geoqc_app worker
```

Las exportaciones tienen un proceso separado, `geoqc_app export-worker`, descrito
en [app_local_exports.md](app_local_exports.md). PDF requiere el extra `app-export`.

La API escucha en `127.0.0.1:8000`; `/` sirve el cliente Web y `/docs` contiene su contrato OpenAPI.
`bootstrap` escribe `.local/credentials.json` sin sobrescribirlo. Para renovar un
token de una identidad existente, usar `token --user-id UUID --output ARCHIVO_NUEVO`.
`worker --once` procesa como máximo un run. No es necesario ejecutar `bootstrap`
al reiniciar API o worker.

## Cancelación y vencimiento de cargas

La migración `002_upload_lifecycle.sql` añade EXPIRED/CANCELLED, `expires_at`,
`closed_at` y motivo de cancelación. Ejecutar `geoqc_app migrate` antes de arrancar
esta versión; las migraciones se aplican una sola vez y en una transacción.
Para sesiones anteriores se fija el vencimiento a creación + 24 horas, conservando
sus IDs, estados, referencias y bytes. No se inventa una hora de cierre histórica
para las cargas ya verificadas. Con las exportaciones, `/health` exige la versión 3 del esquema.

Las sesiones nuevas vencen a las 24 horas por defecto. `upload_ttl_seconds` en la
configuración local permite entre 60 segundos y siete días; afecta solo a nuevas
sesiones. El servidor devuelve `expires_at` al crearlas. La fecha procede de
PostgreSQL, es fija y no se prolonga al transferir o repetir un comando.

`POST /v1/upload-sessions/{id}/cancellations` recibe `{"reason":"motivo"}` y exige
bearer token, rol FIELD_OPERATOR y `Idempotency-Key`. Solo cancela una carga abierta
y vigente. Repetir la misma clave/contenido recupera la respuesta; cambiar el
contenido de esa clave devuelve 409. Otra clave sobre una carga ya cancelada no
modifica su motivo ni genera otro evento. Una carga VERIFIED no se cancela.

```powershell
.\.venv\Scripts\python.exe -m geoqc_app expire-uploads --limit 100
```

El comando cierra hasta 100 cargas vencidas por defecto (máximo 1000), usando
`FOR UPDATE SKIP LOCKED`. Estado y evento outbox se confirman juntos; varios
ejecutores no repiten la transición. El worker también procesa un lote al comenzar
cada ciclo, incluso sin trabajos científicos. Si se ejecuta el comando manual y
devuelve el límite, repetirlo para avanzar sobre el resto del lote.

Una carga vencida rechaza la recepción/finalización inmediatamente con
`UPLOAD_EXPIRED`, aunque su estado durable siga UPLOADING hasta el siguiente ciclo.
Una cancelada rechaza la transferencia con `UPLOAD_FINALIZED`. Se comprueba la
sesión antes de reservar disco y otra vez al vincular los bytes recibidos; si se
cierra durante la transferencia, los bytes no se vinculan. Completar y cancelar
la misma sesión concurrentemente confirma una sola transición. Las cargas
EXPIRED/CANCELLED no entran en revisiones nuevas. Los originales ya vinculados
se conservan y siguen protegidos frente a la limpieza.

## Reconciliación de almacenamiento

```powershell
.\.venv\Scripts\python.exe -m geoqc_app reconcile
.\.venv\Scripts\python.exe -m geoqc_app reconcile --apply
```

El primer comando solo informa. `--apply` elimina únicamente blobs de nombre
interno válido, sin referencia en `artifacts` y con al menos 24 horas por defecto;
`--minimum-age-hours` permite cambiar la retención con un mínimo de una hora.
Se comprueban hashes/tamaños de todos los artefactos referenciados, incluidos los
originales reemplazados en una sesión, que se conservan. Si hay una carga UPLOADING,
un run en cola/ejecución/reintento o un error de integridad, el borrado se rechaza.
Las rutas enlazadas o ajenas a la carpeta de blobs no se eliminan.

El reconciliador no borra temporales ni carpetas de intentos; el hijo de un worker
muerto todavía podría escribir allí. El informe tampoco cambia estados. Para
liberar sesiones abandonadas, cancelar las vigentes o ejecutar `expire-uploads`
para las vencidas antes de `reconcile --apply`; no se debe editar la base manualmente
para forzar una limpieza. Una raíz se usa con una única
base/esquema y configuración de conexión explícita, sin cambiar variables de
entorno que alteren el destino de PostgreSQL.

## Recuperación y trazas operativas

Las pruebas de recuperación ejecutan procesos reales de API y worker. La API se
termina abruptamente después del commit y antes de consumir el cuerpo de respuesta;
al reiniciar, la misma clave devuelve la decisión confirmada y conserva un único
historial/evento. Otro caso mata el worker después de reclamar el trabajo y lanzar
el cálculo, espera el vencimiento natural del lease y ejecuta otro proceso worker:
el primer intento queda EXPIRED y el segundo publica un único dosier.

Esto demuestra recuperación de esos procesos con PostgreSQL disponible; no prueba
reinicio del servidor PostgreSQL, corte eléctrico ni todos los puntos posibles de caída.

Los logs de API y servicio relacionan request_id, proyecto, actor, operación,
hash de clave idempotente y recurso confirmado después del commit. El worker
registra proyecto, run, número de intento, token de fencing y duración. No se
imprimen bearer tokens, claves originales, textos de dictamen ni muestras.
Los despachadores concurrentes tienen una prueba de unicidad y avance de cursor.

## Pruebas y evidencia

```powershell
.\.venv\Scripts\python.exe -m pytest tools/tests/test_app_backend.py -q --junitxml=evidence/app_local/backend_tests.xml
.\.venv\Scripts\python.exe -m ruff check geoqc_app tools/start_local_postgres.py tools/tests/test_app_backend.py
.\.venv\Scripts\python.exe -m mypy geoqc geoqc_app
```

Para repetir la ampliación de recuperación y archivar su evidencia:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/tests/test_app_backend.py -q --junitxml=evidence/app_local/backend_recovery_tests.xml
.\.venv\Scripts\python.exe tools/summarize_app_backend.py
```

Para repetir la ampliación de ciclo de vida de cargas:

```powershell
.\.venv\Scripts\python.exe -m pytest tools/tests/test_app_backend.py -q --junitxml=evidence/app_local/backend_upload_lifecycle_tests.xml
.\.venv\Scripts\python.exe tools/summarize_app_backend.py --report evidence/app_local/backend_upload_lifecycle_tests.xml --scope LOCAL_UPLOAD_LIFECYCLE
```

Las pruebas requieren `.local/backend.json` y PostgreSQL accesible. Cada prueba
crea un esquema aleatorio y lo elimina al terminar; no modifica el esquema de
desarrollo. No sustituyen PostgreSQL por SQLite ni simulan las transacciones.
La evidencia JUnit identifica los casos efectivamente ejecutados.

Resultado de esta ejecución: **28 pruebas pasaron** al ejecutar conjuntamente
`test_app_backend.py` (12 casos) y `test_masw_adapter.py` (16 casos), en 63,50 s,
sin fallos ni skips. Reporte: [backend_tests.xml](../evidence/app_local/backend_tests.xml).
Después de armonizar la versión de reapertura como cadena decimal se repitió su
caso de persistencia/reapertura: **1 prueba pasó**, en 8,45 s; reporte
[backend_reopening_tests.xml](../evidence/app_local/backend_reopening_tests.xml).
Ruff pasó para backend, helper y pruebas; mypy pasó para los 75 archivos de
`geoqc` y `geoqc_app`. No se ejecutó la suite científica completa en esta entrega.

La ampliación de recuperación/reconciliación ejecutó **25 pruebas**, todas
satisfactorias, sin skips, en 72,06 s. Incluye procesos reales, tres despachadores,
bloqueo entre mantenimiento y comandos, retención, integridad y arranque paralelo
del marcador de almacenamiento. Ruff pasó para backend, pruebas, helper de
PostgreSQL y colector; mypy pasó para los **77 archivos** actuales de ambos paquetes.
Reporte: [backend_recovery_tests.xml](../evidence/app_local/backend_recovery_tests.xml).
El [archivo de ejecución](../evidence/app_local/backend/runs/20261016T041315Z_d9f703d4/execution.json)
conserva versiones, hashes de fuentes y copia del JUnit. El colector archiva pruebas
ya ejecutadas; su captura de hashes no certifica por sí sola que el reporte proceda
de esas fuentes. No se ejecutó de nuevo la suite científica completa.

La ampliación de ciclo de vida ejecutó **37 pruebas**, todas satisfactorias,
sin fallos ni skips, en **99,95 s**. Añade migración desde el esquema 1 sin perder
originales, cancelación HTTP con permisos/idempotencia, expiración concurrente por
lotes, vencimiento durante la transferencia/verificación, carrera completar/cancelar,
retención de sesiones verificadas y cambio de TTL solo para nuevas sesiones.
El recorrido HTTP completo de carga y repetición reveló un UUID sin serializar en
las respuestas de transferencia; se corrigió normalizando todos los cuerpos Reply
antes de construir JSONResponse. El caso quedó como regresión permanente.
Reporte: [backend_upload_lifecycle_tests.xml](../evidence/app_local/backend_upload_lifecycle_tests.xml).
Archivo con versiones, hashes y copia del reporte:
[20261016T043151Z_c5e8a8cd](../evidence/app_local/backend/runs/20261016T043151Z_c5e8a8cd/execution.json).
Ruff pasó y mypy verificó los 77 archivos de ambos paquetes. La instancia de desarrollo
local también se migró a la versión 2 y su `/health` devolvió 200. No se ejecutó la
suite científica completa ni se borraron archivos de desarrollo con `--apply`.

La ampliación de exportaciones suma **52 pruebas satisfactorias** (15 nuevas de
exportación y 37 regresiones del backend) y mypy verificó 80 archivos.
Los resultados, límites y ejemplos descargables están en
[app_local_exports.md](app_local_exports.md). El esquema actual de desarrollo es 3.

La ampliación de [lectura paginada](app_local_detail.md) ejecutó **69 pruebas
satisfactorias** (17 del detalle y 52 regresiones), sin skips; Ruff pasó y mypy
verificó los 82 archivos actuales. No exige otra migración SQL ni recalcular dosieres.

Se comprueban E5 en subproceso y lectura HTTP, reintentos de carga/run/decisión,
dos revisores distintos concurrentes, recuperación de lease y bloqueo del intento
anterior, cancelación, persistencia al construir otra instancia del servicio,
outbox, supersesión por revisión nueva, aislamiento de proyecto/rol y fallos de
disco que impiden publicar resultados. También se comprueban integridad y cierre
de carga, errores HTTP seguros y rechazo previo de más de 64 canales.

## Límites pendientes del paso 3

- Las pruebas incluyen terminación abrupta y reinicio de API/worker; falta
  una demostración con reinicio de PostgreSQL y cortes de almacenamiento.
- El worker aplica timeout, límite RSS del hijo y tamaños de entrada/salida;
  falta medir capacidad, disco por intento y límites robustos del árbol de procesos
  antes de admitir entradas generales.
- La reconciliación de blobs huérfanos está implementada con bloqueo y retención;
  las sesiones ya tienen expiración/cancelación. Falta limpieza de temporales/intentos.
- El JSON científico es el único artefacto obligatorio. CSV/HTML/PDF derivados
  tienen trabajos y reintentos propios; falta maquetación de informe de campo/gráficas.
- El [detalle HTTP ya usa cursores firmados y páginas por frecuencia](app_local_detail.md),
  con ETag en cabecera y páginas. Falta medir/indexar/cachear su lectura para cargas mayores.
- El registro de cambios se materializa desde outbox. La asignación del cursor
  se serializa por proyecto con bloqueo hasta commit y se prueba con tres
  despachadores; falta el protocolo de snapshot/bajas necesario para Android.
- El [cliente Web](app_local_web.md) está implementado; falta cerrar la demostración
  repetible completa del primer hito.

APP-07 a APP-13 tienen comprobaciones de backend, incluidas caídas reales de
API/worker para APP-09/10; [APP-11 también tiene pruebas de exportaciones](app_local_exports.md).
APP-14/15 tienen comprobaciones específicas en Chromium, documentadas con la Web.
APP-16 tiene logs y recorrido E5 por navegador, pero carece del cierre integrado completo.
Este avance no cierra el paso 3 ni los gates científicos G5 ampliado, G6 o G9.
