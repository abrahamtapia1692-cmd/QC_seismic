# Lectura paginada del dosier MASW

Fecha: 2026-10-16. Avance del paso 3 de [APP-LOCAL-0.1](../app.md).

Las vistas de detalle son proyecciones del JSON científico confirmado. Conservan
su digest, orden, valores, unidades, soporte y abstenciones. No ejecutan MASW ni
modifican la revisión humana. La cabecera y las páginas tienen ETag de su propia
representación HTTP; ese ETag no sustituye al digest científico ni al de ReviewCase.

## Rutas

| GET | Contenido |
| --- | --- |
| /v1/dossiers/{id} | Cabecera científica, manifiesto y ReviewCase asociado, sin arrays de puntos |
| /v1/dossiers/{id}/records | Resúmenes por registro, metadatos nativos, estimadores, direcciones y conteos originales |
| /v1/dossiers/{id}/records/{index}/points | Usabilidad aparente de rejilla, con dirección, índice y punto original en `value` |
| /v1/dossiers/{id}/records/{index}/native-points | Valores de las curvas nativas refinadas, por curva/índice/frecuencia |
| /v1/dossiers/{id}/records/{index}/bands | Bandas aparentes originales con límites, motivos y receptores de soporte |
| /v1/dossiers/{id}/records/{index}/traces | Observaciones originales por receptor, incluidos faltantes/exclusiones |

`index` es el índice de registro de base cero dentro del dosier inmutable, cuya
identidad y digest acompañan cada página. No se utiliza el nombre del tiro como
identificador HTTP ni se asume que la geometría coincida con Oysand.

El resumen de registros ya no devuelve `curves` ni arrays de puntos completos.
Las páginas usan `detail_schema_version=geoqc-dossier-detail-1` y conservan el campo
`records` o el nombre de la colección (`points`, `bands`, `traces`, `native_points`).
Incluyen `next_cursor`, `total_items`, contexto, unidades, scope, estado científico,
suficiencia y elegibilidad. Los conteos de bins no se convierten en porcentajes
de calidad. Un `null` científico permanece `null`.

En `native-points`, `values` contiene el elemento de cada vector original bajo su
nombre de origen, por ejemplo `values.velocities_ms` es la velocidad de ese punto,
en m/s. También se proyectan los controles de banda, geometría cercana y significancia
de ese índice, conservando sus estados sin calibración. No se sustituye esa velocidad
refinada por `grid_velocity_ms`, ni se interpreta sensibilidad como sigma.

## Cursores, filtros y límites

Todas las colecciones aceptan `limit` entre 1 y 100 (50 por defecto) y `cursor`.
La primera petición omite cursor; para continuar se envía `next_cursor` sin editarlo.
Se puede cambiar el tamaño de página, conservando colección, registro y filtros.

`points`, `native-points` y `bands` admiten:

- `direction=-1` o `1`; omitirlo conserva todas las direcciones en su orden original.
- `frequency_min_hz` y `frequency_max_hz`, finitas y no negativas. Los puntos usan
  límites inclusivos; las bandas se seleccionan cuando su intervalo se solapa con
  el solicitado, conservando sus límites originales sin recortarlos.

Registros y trazas rechazan filtros de dirección/frecuencia. Un rango sin elementos
devuelve colección vacía y `next_cursor=null`, sin inventar soporte. Un registro
inexistente devuelve 404; filtros inválidos, límites inválidos o un cursor incompatible
devuelven 422 con código estable.

Cada cursor se firma con HMAC-SHA-256 y se vincula a versión de vista, dosier,
digest científico, colección, registro y filtros. Cambiar cualquiera de ellos o
alterar el token provoca `INVALID_DETAIL_CURSOR`. El token es opaco para el cliente,
pero no está cifrado ni concede permisos. La autorización de proyecto/objeto se
revalida antes de procesarlo, incluso al recuperar una página tras reiniciar.

La clave se publica atómicamente en `.cursor-key`, dentro de la raíz privada de
almacenamiento y fuera de los blobs descargables. Se conserva al reiniciar la API;
no se incluye en evidencia, código ni exportaciones. Perderla/cambiarla invalida
los cursores anteriores. Una clave dañada causa fallo explícito, sin regeneración
silenciosa. Se debe conservar con la configuración privada del entorno.

El cuerpo de cabecera/página no supera **256 KiB UTF-8**. Si el límite de elementos
produciría más bytes, el servidor reduce la página y continúa desde el siguiente
elemento pendiente. Si un único elemento excede el presupuesto, devuelve 413
`DETAIL_ITEM_TOO_LARGE`; el JSON científico completo permanece disponible mediante
su artefacto autorizado. No se truncan motivos, soporte ni observaciones.

La implementación lee/verifica el dosier completo en cada petición, con un límite
de origen de 64 MiB. La paginación limita la respuesta, no elimina ese coste de I/O
y parseo. Indexación/cache de lectura y capacidad medida siguen pendientes; no se
prometen latencia, tamaño fijo de resumen ni consumo máximo de la API.

## Lectura condicional y compatibilidad

La cabecera y cada página devuelven un ETag fuerte calculado sobre su representación.
`If-None-Match` coincidente produce 304 sin cuerpo; se admiten listas, comparación
débil en GET y `*`. Autorización y verificación del archivo se realizan antes del
304: revocar la membresía o dañar el original no queda oculto por la cache.
Las respuestas mantienen `Cache-Control: private, no-cache`.

El cliente conserva el ETag junto con la URL y sus parámetros. Otra página o filtro
es otra representación. El ETag de estas vistas no sirve como `If-Match` al decidir
ReviewCase; esa operación sigue usando su versión/ETag propios.

El antiguo `offset` del prototipo devuelve 422 `OFFSET_PAGINATION_REMOVED`, incluido
`offset=0`, para evitar que un cliente repita silenciosamente la primera página.
`next_offset` se reemplaza por `next_cursor`. No hay migración SQL ni cambios al
esquema científico o a las exportaciones completas. Los cursores del registro de
cambios por proyecto siguen su protocolo anterior; este cambio no acredita Android,
snapshots, bajas ni retención de ese registro.

## Verificación

```powershell
.\.venv\Scripts\python.exe -m pytest tools/tests/test_app_dossiers.py -q --junitxml=evidence/app_local/backend_detail_tests.xml
.\.venv\Scripts\python.exe -m pytest tools/tests/test_app_backend.py tools/tests/test_app_exports.py -q --junitxml=evidence/app_local/backend_detail_regression_tests.xml
.\.venv\Scripts\python.exe -m ruff check geoqc_app tools/tests/test_app_dossiers.py tools/summarize_app_backend.py
.\.venv\Scripts\python.exe -m mypy geoqc geoqc_app
```

Las pruebas recorren los puntos de rejilla/nativos, bandas, trazas y cuatro resúmenes
de registros sin pérdida/duplicados; conservan valores originales, motivos, soporte
y nulos. También comprueban reducción por bytes, cursores alterados/reutilizados,
filtros, arranque paralelo de la clave, continuidad al reiniciar API, ETag/304,
revocación de permisos y fallo de integridad antes de devolver una cache válida.

Resultado ejecutado: **17 pruebas de detalle** satisfactorias en **26,31 s** y
**52 regresiones de backend/exportaciones** satisfactorias en **175,10 s**, sin
fallos, errores ni skips. Ruff pasó y mypy verificó **82 archivos** de ambos paquetes.
La [ejecución archivada](../evidence/app_local/backend/runs/20261016T134244Z_197836da/execution.json)
conserva ambos JUnit, sus hashes, versiones y hashes de fuentes. El colector archiva
reportes ya ejecutados; su captura no demuestra por sí sola que procedan de esas fuentes.

```powershell
.\.venv\Scripts\python.exe tools/summarize_app_backend.py --report evidence/app_local/backend_detail_tests.xml --report evidence/app_local/backend_detail_regression_tests.xml --scope LOCAL_DOSSIER_DETAIL
```

Estas pruebas prepararon el contrato consumido por el [cliente Web local](app_local_web.md).
La evidencia Web de APP-14/15 se documenta por separado; esta ejecución histórica
de detalle no acredita esos casos ni la demostración integrada APP-16. No cambian los gates científicos.
