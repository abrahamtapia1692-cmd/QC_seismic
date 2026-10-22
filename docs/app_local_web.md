# Cliente Web MASW local

Fecha: 2026-10-19. Paso 4 de [APP-LOCAL-0.1](../app.md).

Actualización: la interfaz incorpora selección de técnica y un
[recorrido TRS propio](app_local_trs.md) para refracción/primeros arribos. El
recorrido MASW documentado abajo se conserva; no se mezclan sus protocolos.
Las ejecuciones TRS nuevas añaden QC por traza y formas de onda; el protocolo
opcional `trace_qc.json` solicita ruido y similitud bajo guardas explícitas.
Los dosieres históricos siguen legibles sin agregarles cálculos retrospectivos.

La API sirve la interfaz en `http://127.0.0.1:8000/`. No requiere Node, compilación,
servicios externos ni publicación. Los recursos estáticos se distribuyen dentro
de `geoqc_app`; los endpoints científicos mantienen su autenticación y permisos.

## Ejecución

Desde el repositorio y con PostgreSQL instalado:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[app,app-export,app-test,app-web-test]"
.\.venv\Scripts\python.exe tools/start_local_postgres.py
.\.venv\Scripts\python.exe -m geoqc_app migrate
.\.venv\Scripts\python.exe -m geoqc_app serve
```

En otras terminales:

```powershell
.\.venv\Scripts\python.exe -m geoqc_app worker
.\.venv\Scripts\python.exe -m geoqc_app export-worker
```

Si aún no existen identidades locales, ejecutar `geoqc_app bootstrap` una sola vez.
Tomar el ID del proyecto y el token correspondiente de `.local/credentials.json`;
no compartir ni incluir ese archivo en evidencia. Los tokens duran ocho horas.
Para renovarlos, usar el comando `token` descrito en [backend](app_local_backend.md).

1. Abrir `/` y conectar el token del operador. La interfaz elimina el texto del
   campo y conserva el token solo en memoria. Cargar un token no afirma que haya
   sido validado: cada recurso comprueba su autorización en el servidor.
2. Declarar proyecto, nombre, hasta cuatro parejas SEG-Y/sidecar, protocolo JSON
   y un receptor excluido por registro, en el mismo orden. No hay metadatos ni
   protocolos implícitos. Para E5 usar `examples/e5/masw_plane.sgy`, su sidecar,
   `examples/e5/protocol.json` y exclusión `r0`.
3. Cargar/procesar; conservar el ID del run. Si se pierde una respuesta, reintentar
   en la misma pestaña: se mantienen claves y etapas ya confirmadas. Una sesión
   terminada no recibe de nuevo sus bytes. `Nueva carga` inicia otra operación;
   no cancela las sesiones anteriores, que conservan su vencimiento del servidor.
4. Consultar estado confirmado del run y abrir su dosier. Otra pestaña puede
   recuperarlo pegando el ID del run o del dosier, con un token autorizado.
   Al abrirlo, la página se desplaza a Evidencia científica y carga el resumen
   de registros; en Colección se elige después el detalle de interés.
   En TRS aparece una vista gráfica con selector de registro, geometría declarada
   proyectada sobre X, tiempos registrados frente a offset, estados por receptor
   y tabla interactiva en milisegundos. Los tiempos null no se representan como
   cero ni se conectan con un ajuste inferido. Los motivos de ramas e inversión
   se muestran tal como están publicados. El panel Detalle técnico conserva JSON,
   protocolo, unidades y paginación. La vista automática recorre hasta 2000
   elementos por colección e indica si hay más; no modifica el dosier científico.
5. Consultar registros, puntos de rejilla, curvas nativas, bandas o trazas. Los
   filtros de dirección/frecuencia se aplican solo a colecciones compatibles;
   `Página siguiente` transmite el cursor opaco. La presentación conserva JSON,
   unidades, nulos, motivos y soporte, sin convertir conteos en porcentajes.
6. Descargar el JSON científico o solicitar CSV/HTML/PDF derivados. La exportación
   muestra su estado separado y habilita la descarga al llegar a READY. Una
   solicitud sin respuesta conserva su clave; otra solicitud confirmada crea
   otra exportación. El reintento de una exportación FAILED sigue disponible en
   la API; la Web permite solicitar una nueva.
7. En una sesión con token de revisor, abrir el dosier, indicar dictamen, alcance,
   justificación y salvedades. ACCEPTED requiere salvedades. El servidor exige
   OFFICE_REVIEWER; un token de operador o administrador no concede ese rol.

Los originales de las carpetas KM son SEG-2 y no se cargan directamente como
SEG-Y. Su [preparación e inventario](../examples/km_app/README.md) incluyen ahora
una copia exploratoria de F1 lista para cargar, con cotas/incertidumbres cero
asumidas y salvedades de amplitud/apilamiento documentadas. Las plantillas para
verificación de campo se conservan aparte. En el formulario, Proyecto es `project_id` de las
credenciales, no un número de línea como `0001` ni el token del operador. La Web
comprueba el formato UUID antes de enviar. Si la primera solicitud recibe
`422 INVALID_REQUEST` sin etapas confirmadas, habilita la corrección de datos
conservando los archivos. Los errores de transporte mantienen la misma carga y
su clave para reintentar.

## Concurrencia y recuperación

Cada pestaña mantiene su cache de lectura con ETag por URL completa. Las vistas
activas consultan HTTP cada tres segundos, al recuperar foco y al volver la
conexión. Un error deja visible que la lectura puede estar desactualizada.
El ETag de ReviewCase se mantiene separado del de las representaciones científicas.

El primer cambio al formulario fija la versión base del borrador. Las lecturas
posteriores actualizan historial/estado sin reemplazar el texto ni esa versión.
Si cambia la revisión, se muestra conflicto y se bloquea el envío. También se
conserva el borrador ante HTTP 412, recargando el historial autorizado.

Si el caso vuelve a PENDING tras una reapertura explícita, el revisor puede releer
la evidencia y pulsar `Actualizar versión del borrador`. Esto permite emitir un
comando nuevo con la versión leída; nunca modifica una decisión anterior. La
reapertura se realiza mediante la API, con su motivo y versión esperada.

Una respuesta perdida después del commit mantiene cuerpo, If-Match y clave de
idempotencia originales. El formulario queda bloqueado para edición hasta
recuperar la confirmación al reintentar, incluso si un poll ya observa DECIDED.
Los errores definitivos de contrato/conflicto conservan el texto para corregirlo.
Un estado o esquema científico desconocido se muestra y bloquea el dictamen.

El transporte (`transport.js`), cache/repositorio (`repository.js`), comandos y
caso de carga (`usecases.js`) están separados de la coordinación de vistas
(`app.js`). Las respuestas de una selección/sesión anterior no reemplazan el
estado actual. El contenido científico y el historial se insertan como texto;
ninguna cadena del dosier o la justificación se ejecuta como HTML.

No se persisten tokens, cache, archivos ni borradores en localStorage/sessionStorage.
Recargar o desconectar pierde el borrador y las claves de operaciones pendientes;
antes de repetir una operación desde cero se debe consultar su estado confirmado.
No hay recuperación móvil/offline ni cola durable de cliente. Un token vencido
requiere una nueva sesión. Estos límites siguen dentro del alcance Web local.

## Verificación

Las pruebas usan Chromium real, API local, PostgreSQL con esquema aleatorio y
workers científicos/de exportación reales. El fixture elimina únicamente su
esquema aislado; no modifica adquisiciones de desarrollo. Requieren el navegador:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest tools/tests/test_app_web.py tools/tests/test_app_backend.py tools/tests/test_app_dossiers.py tools/tests/test_app_exports.py -q --junitxml=evidence/app_local/web_regression_tests.xml
.\.venv\Scripts\python.exe -m ruff check geoqc_app tools/tests/test_app_web.py tools/summarize_app_backend.py
.\.venv\Scripts\python.exe -m mypy geoqc geoqc_app
```

Las comprobaciones cubren carga con respuesta perdida sin duplicar adquisición/run,
descarga científica y CSV, dos sesiones que convergen, conflicto real HTTP 412 con
borrador conservado, reapertura externa y actualización explícita de su versión,
revisión confirmada con respuesta perdida, texto HTML escapado, cursores/filtros,
ETag/304, ancho móvil y bloqueo de un estado científico futuro desconocido.

Resultado ejecutado: **76 pruebas satisfactorias en 268,22 s**, sin fallos,
errores ni skips: 7 de Web/Chromium, 37 de backend, 17 de detalle y 15 de
exportaciones. [Reporte JUnit](../evidence/app_local/web_regression_tests.xml).
Ruff pasó y mypy verificó los 82 archivos de ambos paquetes. También se construyó
un wheel y se comprobó que incluye los seis recursos de la interfaz.

La [ejecución archivada](../evidence/app_local/backend/runs/20261020T030348Z_5b731ed1/execution.json)
conserva el JUnit, versiones, hashes de fuentes y capturas
[de escritorio](../evidence/app_local/backend/runs/20261020T030348Z_5b731ed1/web_desktop.png)
y [de ancho móvil](../evidence/app_local/backend/runs/20261020T030348Z_5b731ed1/web_mobile.png).
El colector archiva reportes ya ejecutados; sus hashes capturan las fuentes al
archivar y no certifican por sí solos el origen del reporte. No se ejecutó la suite
científica completa en esta ampliación.

```powershell
.\.venv\Scripts\python.exe tools/summarize_app_backend.py --report evidence/app_local/web_regression_tests.xml --scope LOCAL_WEB_CLIENT
```

APP-14/15 tienen comprobaciones Web específicas. El recorrido E5 por navegador
complementa APP-16, pero el hito integrado conserva pendientes de demostración
tras reinicios y de límites operativos documentados en el backend. No se acreditan
gates científicos, calibración de campo ni suficiencia ingenieril.
