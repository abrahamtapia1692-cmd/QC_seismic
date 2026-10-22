# GeoQC — especificación inicial de la aplicación local

Versión: APP-LOCAL-0.1. Fecha: 2026-10-14.

Ampliación del 19 de octubre: el usuario solicitó procesar los KM como TRS.
El [ADR 0005](docs/adr/0005-local-trs-diagnostic.md) y el
[recorrido TRS local](docs/app_local_trs.md) definen esta extensión con técnica,
protocolo y dosier propios. Los requisitos MASW originales se conservan; la
ampliación no acredita aceptación científica u operativa TRS.
Estado: adaptador científico implementado; backend/worker y cliente Web local implementados con verificaciones propias; cierre integrado pendiente. Ver [adaptador](docs/app_local_adapter.md), [avance del backend](docs/app_local_backend.md) y [cliente Web](docs/app_local_web.md).
Primer hito: **cargar un registro MASW con metadatos → procesarlo → consultar el dosier → registrar una revisión humana**.

Esta especificación reemplaza la propuesta preliminar como plan de la aplicación. No modifica la especificación científica v1.4/MASW-R1 ni acredita sus gates. El original se conserva en [la propuesta archivada](docs/archive/app_propuesta_2026_10_14.md); sus referencias históricas están en [la auditoría de arquitectura](docs/auditoria_arquitectura_app_2026_10_14.md). Las decisiones iniciales se registran en [ADR 0004](docs/adr/0004-local-masw-scope.md).

## 1. Objetivo y alcance del primer hito

Construir un recorrido local reproducible, con estado confirmado en el servidor y un motor científico reutilizable por CLI y worker. La primera interfaz será Web. Android consumirá después los mismos contratos, con almacenamiento local y recuperación tras desconexión.

| Capacidad | Incluida en el primer hito |
| --- | --- |
| Técnica | MASW diagnóstica Rayleigh vertical aparente; ampliación TRS/P diagnóstica según ADR 0005 |
| Formato de entrada de la aplicación | SEG-Y rev0/1 en el subconjunto ya soportado por el lector, más sidecar JSON obligatorio |
| Proyecto y usuarios | Un proyecto de demostración y usuarios locales autenticados; permisos por membresía, sin rol global implícito |
| Carga | Un archivo por sesión y su sidecar; lote de hasta cuatro registros; verificación de bytes y metadatos |
| Cálculo | Worker separado de HTTP, protocolo y política fijados por run, estado y errores recuperables |
| Resultado | JSON científico y manifiesto obligatorios; resumen, curvas, bandas, motivos y procedencia |
| Exportación | CSV, HTML y PDF derivados, con estado propio; no bloquean el resultado científico listo |
| Revisión | Anotación humana con alcance, justificación, salvedades y control de versión |
| Recuperación | Reintentos idempotentes, trabajos persistentes y consulta de estado después de reiniciar |
| Sincronización inicial | Lectura HTTP periódica/condicional; dos sesiones Web deben converger |
| Suficiencia | Estado NOT_DEMONSTRATED, separado de calidad y revisión; sin transición a demostrada en este hito |

La aprobación humana es una anotación diagnóstica en desarrollo local. No libera automáticamente una estación o cuadrilla ni transforma un resultado DRAFT en aceptación científica.

### 1.1 Capacidades posteriores

TRS diagnóstica se incorporó mediante ADR 0005 a petición del usuario. SEG-2, SU, importación ASCII general, inversión/Vs30, evaluación demostrada de suficiencia, aplicación Android, iOS, cálculo en móvil sin conexión, push, WebSockets, cargas resumibles, MinIO/S3, gestión completa de directivas, políticas editables, C++ y autoescalado quedan para hitos posteriores. Se conservan límites de integración que permitan agregarlas sin cambiar el significado del resultado inicial.

SEG-2 ya existe en el núcleo, pero no forma parte del contrato de carga inicial. SU no está habilitado en el lector general examinado. No se anunciará soporte de un formato por su extensión sin parser y pruebas correspondientes.

## 2. Datos de referencia y límites de lo que demuestran

| Caso | Archivos y función | Criterio |
| --- | --- | --- |
| OYSAND-REGRESSION | Cuatro registros ASCII, manifiesto de descarga y protocolo del dosier actual | Referencia de regresión del procesamiento existente; cuatro registros y 96 trazas de un mismo sitio |
| E5-LOCAL | SEG-Y, sidecar y protocolo de [examples/e5](examples/e5/README.md) | Primer recorrido por la ingesta validada y la aplicación; 24 receptores, señal sintética y parámetros explícitos |
| INDEPENDENT-TECHNICAL | E5 y controles sintéticos con parámetros distintos de Oysand | Comprobar que cálculo y adaptador no dependen de rutas, nombres o constantes del conjunto de campo |
| SECOND-FIELD-SITE | Conjunto MASW de otro sitio, todavía sin seleccionar | Ampliación posterior de validación de campo; E5 no sustituye un segundo sitio real |

Oysand se usa en la caracterización de regresión y conserva su cargador exploratorio fuera del endpoint de carga inicial. Sus metadatos incompletos impiden presentarlo como un Shot validado sin trabajo adicional. No se convertirá a SEG-Y inventando unidad de amplitud, CRS, incertidumbre, trigger o referencia temporal.

La comparación Oysand identifica equivalencia de extracción y clasificación bajo su protocolo original. E5 comprueba ingesta y ejecución general; usa su propio protocolo. No se exige igualdad de curvas entre conjuntos ni entre protocolos diferentes.

La política inicial es [MASW_APPARENT_USABILITY_V1_DRAFT](configs/masw_usability_v1.json). Los protocolos son entradas explícitas, tipadas y congeladas por ejecución; no se fuerza el protocolo Oysand sobre E5. La reconciliación entre el protocolo del dosier y MASWProtocol debe documentarse en el adaptador, conservando bins, dirección, variantes y refinamiento de cresta de cada recorrido.

Los datos originales y la evidencia histórica permanecen intactos. La evidencia de la aplicación se guardará en su propio directorio por ejecución. No se reinterpretarán los controles sintéticos como calibración de campo.

## 3. Vocabulario y reglas de dominio

| Concepto | Significado |
| --- | --- |
| Acquisition | Evento físico o experimento sintético; identidad estable y pertenencia a proyecto |
| AcquisitionRevision | Snapshot inmutable de metadatos y registros seleccionados |
| RawArtifact | Original verificado, hash y referencia estable al contenido |
| Shot | Contrato científico actual: muestras, máscaras, tiempos, geometría y adquisición explícitos |
| ProcessingRun | Solicitud lógica de cálculo con entradas, protocolo, política y motor fijados |
| ProcessingAttempt | Intento de ejecutar un run; lease, token, fases y error propios |
| ScientificDossier | Resultado científico inmutable de un run publicado |
| ArtifactManifest | Inventario de artefactos verificados con tamaño, hash, formato y estado |
| ReviewCase | Estado revisable y versión propia; apunta a un resultado y alcance concretos |
| ReviewDecision | Anotación humana inmutable que conserva lo que se decidió y sobre qué evidencia |
| Sufficiency | Evaluación independiente respecto de un objetivo ingenieril; no demostrada en este hito |

### 3.1 Invariantes obligatorias

1. Calidad diagnóstica, revisión humana y suficiencia son dimensiones independientes.
2. UTILIZABLE, REVISAR, NO_UTILIZABLE y NO_EVALUABLE conservan el significado del núcleo. El asterisco de “Utilizable*” pertenece a la etiqueta visual, no al enum.
3. Una ausencia, invalidez, abstención o falta de calibración no se transforma en cero ni en calidad buena.
4. Ningún endpoint de revisión modifica métricas, bandas, política ni elegibilidad del resultado.
5. eligible_for_acceptance permanece false; validated_bands no se llena para satisfacer el flujo de aplicación.
6. Toda operación está autorizada por usuario y proyecto. El actor y la hora confirmada los determina el servidor.
7. Una corrección de metadatos crea otra revisión; otro cálculo crea otro run; una repetición física crea otra adquisición con vínculo explícito al padre.
8. Una revisión nunca se hereda automáticamente al resultado nuevo. Aprobar uno histórico no aprueba el vigente.
9. Presencia en pantalla y progreso visual no modifican contenido científico ni bloquean revisores.
10. Archivos, metadatos, política, protocolo y entorno usados quedan identificados por versión/hash.
11. Un resultado se hace visible solamente después de confirmar su manifiesto y registro SQL.
12. Reentregar un comando o trabajo no duplica sus efectos confirmados.

### 3.2 Revisión humana inicial

Se reutiliza el significado de OperatorDecision: ACCEPTED, REPEAT y EXTEND; PENDING representa un borrador o ausencia de decisión. ACCEPTED exige responsable autenticado, alcance, justificación y salvedades explícitas. Su presentación debe indicar “Anotación diagnóstica aceptada”, sin certificación de campo.

ReviewCase tiene estados PENDING y DECIDED. Una reapertura autorizada devuelve el caso a PENDING, incrementa su versión y agrega historia. Las decisiones previas permanecen inmutables.

El revisor puede registrar observaciones y acciones solicitadas como parte del alcance anotado. El ciclo formal de ejecución/verificación de directivas se implementará después; no se incluye un booleano que cierre automáticamente una acción de campo.

## 4. Entrada y salida del adaptador científico

Este contrato se implementa en MASWAdapterInput y MASWAdapterResult dentro del paquete, sin dependencias HTTP, SQL ni rutas de ejemplos. La documentación del adaptador detalla su entrada explícita de exclusiones de sensibilidad, el envelope de salida y las responsabilidades del ejecutor.

### 4.1 Entrada conceptual

| Campo | Regla |
| --- | --- |
| schema_version | Versión del contrato de aplicación, independiente del schema científico existente |
| acquisition_revision_id | Referencia inmutable con pertenencia y orden de tiros explícitos |
| shots | Uno o más Shot validados; orden estable y IDs únicos |
| protocol | Protocolo MASW tipado, procedencia y hash |
| usability_policy | Política tipada, versión, estado DRAFT y hash |
| engine_reference | Versión de código y entorno fijados por ejecución |
| scope | Qué se evalúa y qué preguntas quedan fuera de soporte |

La ingesta debe preservar unidades, CRS, incertidumbre, fuente, receptores, roles de canales, tiempos por canal, autoridad header/sidecar, hashes y motivos de máscara ya exigidos por el núcleo. No completar faltantes con dx, dt, t0 o número de canales de un sitio conocido.

El adaptador no lee políticas globales al importar ni busca archivos en examples/. El cargador Oysand de regresión termina antes de esta frontera o se conserva como recorrido de caracterización independiente, sin falsificar un Shot.

### 4.2 Salida conceptual

| Campo | Regla |
| --- | --- |
| schema_version, method, scope | Versión de salida, método y alcance explícitos |
| input_manifest | Hashes y orden de datos, sidecars, geometría, protocolo y política |
| diagnostic_quality | Resultados por registro/frecuencia/banda, soporte activo, códigos y motivos |
| missing_evidence | Faltantes que permanecen visibles aunque existan bandas utilizables |
| scientific_status | Completitud y advertencias científicas; distinto del estado de ejecución |
| sufficiency | NOT_DEMONSTRATED y motivos; ninguna inferencia desde la revisión |
| eligible_for_acceptance | false |
| scientific_digest | Digest del contenido científico canónico, sin el propio digest |
| provenance | Versión del motor, dependencias y parámetros numéricos relevantes |

Matrices y arrays extensos se guardan como artefactos científicos versionados; HTTP entrega resúmenes y detalle paginado. Todo JSON es estricto: sin NaN/Infinity; un faltante lleva null y motivo.

No se exige que PDF/HTML sean idénticos byte a byte entre entornos. La equivalencia científica se comprueba por campos y tolerancias justificadas, fijadas antes de evaluar regresión. El digest identifica un contenido concreto; no sustituye esa comprobación cuando cambia el entorno.

## 5. Arquitectura local y dependencias

Un backend modular y procesos worker separados comparten casos de uso y contratos, con PostgreSQL como autoridad transaccional. El paquete geoqc conserva su independencia de la aplicación.

~~~mermaid
flowchart TB
    CLI[CLI y pruebas del adaptador] --> ENGINE[Motor científico geoqc]
    WEB[Cliente Web] --> API[API local y autorización]
    API --> DOMAIN[Casos de uso y dominio]
    DOMAIN --> DB[(PostgreSQL)]
    API --> STORE[Puerto de almacenamiento]
    STORE --> FILES[(Archivos locales verificados)]
    DB --> JOBS[Trabajos persistentes y outbox]
    JOBS --> WORKER[Worker con lease y límites]
    WORKER --> ENGINE
    WORKER --> STORE
    WORKER --> DOMAIN
    API -->|estado y lectura condicional| WEB
~~~

- Etapa del adaptador: Python y el entorno científico actual; sin instalar servidor, base o Docker.
- Etapa de backend: FastAPI como transporte inicial, PostgreSQL y almacenamiento local detrás de un puerto. Docker Compose podrá facilitar PostgreSQL; no se presupone que esté instalado.
- Trabajos iniciales: reclamación durable en PostgreSQL con lease, token y restricciones; sin broker externo obligatorio para esta carga local. La API de procesamiento no depende de esa elección.
- El outbox y el registro de cambios se escriben con el dominio. Un despachador local materializa avisos/bandeja; el estado confirmado no depende de avisos.
- Puertos mínimos: ArtifactStore, JobRepository, RunPublisher, ReviewRepository y ChangeReader. No se abstraen todas las funciones de todos los proveedores.
- Matplotlib y renderizado se declaran como dependencias específicas al implementar exportaciones; no se convierten en requisito del cálculo puro.
- API y worker se vinculan a localhost por defecto. Credenciales locales se configuran fuera del código y no se aceptan IDs de usuario como autenticación.

La combinación de broker, transporte push, proveedor de objetos y framework móvil se decidirá al incorporar esas capacidades. No es necesaria para implementar el adaptador ni el primer flujo central.

### 5.1 Organización prevista

| Área | Responsabilidad |
| --- | --- |
| geoqc/ | Contratos y cálculo científico reutilizables; adaptador de dosier desacoplado |
| Backend de aplicación | Usuarios/proyectos, carga, runs, revisión, transacciones y API |
| Worker de aplicación | Reclamación, aislamiento, invocación del adaptador y publicación |
| Cliente Web | Transporte, repositorio/cache, casos de uso y presentación separados |
| Contratos y fixtures | Ejemplos científicos y de API con estados/faltantes consistentes |
| tools/ | Utilidades y generación histórica; no se ejecutan como API pública de cálculo |

La ubicación concreta de los módulos del backend se fija al crear su esqueleto. No se mueve código científico por una preferencia de carpetas antes de demostrar equivalencia.

## 6. Carga, procesamiento y publicación

### 6.1 Estados separados

| Agregado | Estados iniciales |
| --- | --- |
| UploadSession | CREATED, UPLOADING, VERIFYING, VERIFIED, REJECTED, EXPIRED, CANCELLED |
| ProcessingRun | QUEUED, VALIDATING, RUNNING, RETRY_WAIT, SUCCEEDED, FAILED, CANCELLED |
| Export | PENDING, RUNNING, READY, FAILED |
| ReviewCase | PENDING, DECIDED |
| Sufficiency | NOT_DEMONSTRATED |

~~~mermaid
stateDiagram-v2
    [*] --> QUEUED
    QUEUED --> VALIDATING: intento reclama lease
    VALIDATING --> RUNNING: contratos y soporte compatibles
    VALIDATING --> FAILED: entrada invalida o metodo no aplicable
    RUNNING --> SUCCEEDED: manifiesto y resultado confirmados
    RUNNING --> FAILED: fallo permanente
    VALIDATING --> RETRY_WAIT: fallo transitorio
    RUNNING --> RETRY_WAIT: fallo transitorio
    RETRY_WAIT --> QUEUED: reintento limitado
    QUEUED --> CANCELLED: cancelacion autorizada
    VALIDATING --> CANCELLED: cancelacion autorizada
    RUNNING --> CANCELLED: publicacion pierde permiso
    RETRY_WAIT --> CANCELLED: cancelacion autorizada
~~~

SUCCEEDED expresa ejecución y publicación correctas; no calidad buena ni suficiencia. Un canal muerto puede producir un resultado diagnóstico exitoso con hallazgo negativo.

### 6.2 Protocolo obligatorio

1. Crear adquisición y sesión autorizadas; recibir waveform y sidecar en zona temporal con límites.
2. Verificar tamaño y SHA-256 del contenido completo en servidor. Mover/promover a una referencia final no sobrescribible antes de confirmar VERIFIED. El cliente no puede escribir esa referencia.
3. Congelar revisión y crear run/trabajo junto con evento outbox en una transacción. Su verificación científica se realiza en el worker.
4. Reclamar intento con lease/token; validar Shot, protocolo y compatibilidad científica; ejecutar fuera del proceso HTTP.
5. Guardar JSON y artefactos obligatorios en rutas exclusivas del intento; verificar hashes y crear manifiesto.
6. Confirmar resultado, estado SUCCEEDED, ReviewCase y cambio/outbox mediante el publicador, condicionado al token vigente y a que el run no esté cancelado.
7. Generar exportaciones derivadas separadamente. Su fallo queda registrado y se puede reintentar sin recalcular ciencia.
8. Reconciliar objetos huérfanos y trabajos con lease vencido. Nunca eliminar archivos de runs activos o resultados referenciados.

Errores de metadatos, formato no soportado o dominio no aplicable son permanentes para esas entradas. Errores transitorios de base/disco permiten reintentos limitados. Una corrección crea entradas/run nuevos. Deben conservarse las muestras originales y la causa de abstención: ingesta válida no equivale a soporte suficiente para MASW.

### 6.3 Límites iniciales de admisión

Valores de desarrollo, configurables y todavía sin capacidad medida: hasta cuatro registros por run, 32 MiB por waveform, 1 MiB por sidecar, 64 canales y 65 536 muestras por canal. Las rejillas no exceden 256 frecuencias y 512 velocidades; procesamiento secuencial de tiros y un intento científico concurrente por worker.

Antes de reservar arrays se comprueban dimensiones, tamaño, tiempo solicitado y coste estimado. El número de bins solicitado no implica banda validada. Al implementar el worker se fijarán también RAM/disco/timeout y presupuesto de reintentos a partir de mediciones; admitir entradas generales queda bloqueado hasta aplicar esos límites. Estos valores no son una promesa de rendimiento ni reglas geofísicas.

## 7. Revisión, autorización e idempotencia

| Rol por proyecto | Facultades iniciales |
| --- | --- |
| FIELD_OPERATOR | Crear cargas/adquisiciones y consultar sus resultados dentro del proyecto autorizado |
| OFFICE_REVIEWER | Consultar evidencia y registrar/reabrir anotaciones dentro de su alcance |
| PROJECT_ADMIN | Gestionar membresías y configuración operativa; no editar políticas científicas publicadas por ese solo rol |

La demostración usa identidades distintas de operador y revisor. Un administrador solo revisa si también tiene ese rol. Cada lectura, descarga y comando verifica pertenencia y objeto, incluso si solo hay un proyecto precargado.

La revisión protege ReviewCase, con versión positiva propia, separada de acquisition_revision_id y scientific_digest. La versión se conserva como BIGINT y se transporta como cadena decimal. El ETag fuerte es opaco y pertenece a la representación de ReviewCase, no al archivo ni al resultado científico.

Para confirmar una revisión, en una transacción:

1. Autorizar actor/proyecto y resolver una repetición idempotente ya confirmada.
2. Verificar digest, alcance y vigencia del resultado. Si apareció un resultado vigente nuevo, rechazar con RESULT_SUPERSEDED; la revisión histórica requerirá una operación explícita posterior.
3. Actualizar ReviewCase condicionando versión/estado en la misma escritura.
4. Insertar decisión inmutable, historial, cambio durable, outbox y resultado del comando.
5. Confirmar y responder. Si otro revisor ganó, conservar el borrador del cliente y devolver conflicto.

If-Match fallido devuelve 412; ausencia de la precondición requerida devuelve 428; conflicto de negocio o reutilización incompatible de una clave devuelve 409. Referencia: [semántica HTTP](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1) y [precondición obligatoria](https://www.rfc-editor.org/rfc/rfc6585.html#section-3).

Idempotency-Key se acota a actor, proyecto y operación, con hash del comando normalizado y reserva única. Misma clave/contenido recupera la respuesta o el recurso en curso; contenido diferente se rechaza. La autorización se revalida al recuperar una respuesta. En la demostración las claves se conservan durante la vida del proyecto; producción requerirá política explícita de retención.

## 8. Contrato HTTP inicial

Rutas orientativas con semántica fijada; los DTO/OpenAPI se implementan antes de conectar las interfaces. No se prometen endpoints existentes.

| Operación | Resultado |
| --- | --- |
| POST /v1/acquisitions | Identidad de adquisición, proyecto autorizado y borrador; idempotente |
| POST /v1/upload-sessions | Sesión con acquisition_id y límites; idempotente |
| PUT /v1/upload-sessions/{id}/waveform | Recepción completa limitada; sesión no finalizada, sin reanudación por partes inicial |
| PUT /v1/upload-sessions/{id}/sidecar | Metadatos originales con límite de tamaño |
| POST /v1/upload-sessions/{id}/complete | Cierre idempotente; verifica/promueve bytes; 202 si verificación pendiente |
| POST /v1/upload-sessions/{id}/cancellations | Cancela una sesión abierta/vigente con motivo e idempotencia; conserva originales |
| GET /v1/upload-sessions/{id} | Estado, hashes confirmados o error de verificación |
| POST /v1/acquisitions/{id}/revisions | Snapshot de sesiones verificadas y selección ordenada; idempotente |
| POST /v1/processing-runs | Revisión, protocolo y política concretos; 202 con run_id y seguimiento |
| GET /v1/processing-runs/{id} | Estado, fase, attempt y error seguro; progreso por fase, sin porcentaje ficticio |
| GET /v1/dossiers/{id} | Cabecera científica, resumen, faltantes y referencias |
| GET /v1/dossiers/{id}/records | Detalle paginado por registro/frecuencia, con unidades y soporte |
| GET /v1/dossiers/{id}/records/{index}/points | Puntos de rejilla por cursor, dirección y rango de frecuencias |
| GET /v1/dossiers/{id}/records/{index}/native-points | Curvas nativas refinadas por cursor, sin sustituirlas por rejilla |
| GET /v1/dossiers/{id}/records/{index}/bands | Bandas aparentes originales por cursor y solapamiento de frecuencia |
| GET /v1/dossiers/{id}/records/{index}/traces | Observaciones por receptor con motivos/faltantes, por cursor |
| GET /v1/review-cases/{id} | Estado actual, alcance, versión y ETag |
| PUT /v1/review-cases/{id} | Decisión condicionada con If-Match e Idempotency-Key |
| POST /v1/review-cases/{id}/reopenings | Reapertura autorizada con expected_version e idempotencia |
| GET /v1/artifacts/{id}/content | Descarga autorizada; el cliente no especifica una ruta del servidor |
| POST /v1/dossiers/{id}/exports | Encola CSV/HTML/PDF derivados con clave idempotente y renderizador fijado |
| GET /v1/exports/{id} | Estado e intento del derivado, error seguro o manifiesto READY |
| POST /v1/exports/{id}/retries | Reintento idempotente de FAILED dentro de su presupuesto, sin recalcular ciencia |
| GET /v1/exports/{id}/content | Descarga autorizada del derivado READY |

Todos los comandos POST y la confirmación de revisión requieren clave de idempotencia. Las recepciones PUT de waveform/sidecar son reemplazables solo antes del cierre, con digest y exclusión de escrituras concurrentes; la finalización bloquea la sesión y fija los bytes que verifica. Repetir la transferencia después de perder la respuesta devuelve el estado correspondiente, sin sobrescribir un original confirmado.

Las sesiones de carga tienen `expires_at` fijado por PostgreSQL (24 horas por defecto,
configurable para nuevas sesiones). Cancelación, finalización y expiración bloquean
la misma fila; una transferencia que pierde vigencia no puede vincular nuevos bytes.
El worker y `expire-uploads` confirman vencimientos por lotes junto con sus eventos.
VERIFIED, EXPIRED y CANCELLED conservan los originales previamente vinculados.

El resultado de error contiene code, message, request_id y detalles seguros; una versión actual se devuelve solo tras autorizar el recurso. No exponer stack traces ni rutas locales. Distinguir errores de sesión, transferencia, validación científica y conflicto.

La paginación lleva cursor opaco y límites del servidor. El resumen no incluye matrices completas ni promete 15 KB/200 ms. Los códigos son estables y las etiquetas se traducen en presentación. La versión APP-LOCAL-0.1 no reemplaza schema_version científico 1.4 ni masw-dossier-2.0; cualquier mapeo conserva su origen.

## 9. Clientes y evolución a Android

El primer cliente Web separa transporte, repositorio/cache, casos de uso y presentación. Muestra estados de servidor, advertencias DRAFT, salvedades y los motivos de cada banda. Un borrador no aparece confirmado antes del commit.

Durante el primer hito, las vistas activas consultan recursos por HTTP con ETag, y recargan al recuperar conexión o foco. No se pierde historia porque no haya socket. Un conflicto conserva el texto del revisor y exige releer evidencia antes de emitir otro comando.

Antes del hito Android se incorporará registro durable de cambios con cursor, snapshot, bajas, permisos y expiración; no usar ingenuamente una secuencia SQL como orden de commits. Android tendrá cache persistente, cola local de comandos, migraciones y estado pendiente/confirmado/conflicto. Push/WebSocket serán avisos para consultar cambios.

Los estados y unidades compartidos se verifican con fixtures. El servidor decide permisos y transiciones; los clientes ofrecen validaciones de usabilidad. Un enum desconocido puede mostrarse como no soportado y bloquea un dictamen que el cliente no entiende. La ventana de versiones móviles soportadas debe fijarse antes de distribuir Android.

## 10. Criterios de aceptación y evidencia

Todos los estados iniciales de esta tabla fueron NOT_RUN. El avance y la evidencia ejecutada se registran en la documentación del [adaptador](docs/app_local_adapter.md), del [backend](docs/app_local_backend.md) y del [cliente Web](docs/app_local_web.md). El backend tiene pruebas PostgreSQL y recuperación de procesos API/worker; la Web incorpora pruebas con Chromium para APP-14/15. La equivalencia CLI/entrada serializada del adaptador es distinta de las pruebas posteriores del worker real.

| ID | Hito | Comprobación exigida |
| --- | --- | --- |
| APP-01 | Adaptador | Caracterización Oysand conserva cuatro registros/96 trazas, códigos, faltantes y no elegibilidad |
| APP-02 | Adaptador | E5 se ingiere por lector validado sin rutas/constantes Oysand |
| APP-03 | Adaptador | Otro control sintético cambia geometría o tamaño y conserva su propio protocolo explícito |
| APP-04 | Adaptador | Misma entrada/protocolo/entorno conserva contenido científico por CLI e invocación de worker |
| APP-05 | Adaptador | Falta de metadatos o soporte produce error/abstención documentados, sin valores inventados |
| APP-06 | Adaptador | JSON estricto y manifiesto incluyen hashes de originales, sidecars, protocolo, política y motor |
| APP-07 | Backend | Carga/revisión repetidas tras perder respuesta no duplican runs ni decisiones |
| APP-08 | Backend | Dos revisores sobre la misma versión confirman exactamente una decisión |
| APP-09 | Backend | Reinicio después del commit conserva trabajo, decisión y eventos pendientes |
| APP-10 | Backend | Worker muerto/lease vencido permite recuperación y bloquea publicación del intento antiguo |
| APP-11 | Backend | Fallo parcial de artefactos no publica resultado listo; fallo de exportación no altera ciencia |
| APP-12 | Backend | Cambiar metadatos crea linaje nuevo; no modifica originales ni hereda revisión |
| APP-13 | Backend | Cambiar ID/proyecto o rol no permite leer, descargar o decidir fuera de alcance |
| APP-14 | Web | Dos sesiones convergen por lectura HTTP; conflicto conserva borrador |
| APP-15 | Web | ACCEPTED no altera calidad, bandas validadas, suficiencia ni elegibilidad |
| APP-16 | Local integrado | Ejecución desde entorno documentado; logs relacionan proyecto, run, intento y comando |

La extracción del adaptador necesita pruebas de caracterización antes de mover lógica; se reutilizan controles existentes cuando prueban el mismo comportamiento. Las tolerancias numéricas y campos excluidos de comparación deben documentarse previamente y justificarse. No relajar una prueba ni actualizar evidencia histórica solo para hacer pasar una refactorización.

La evidencia nueva identifica qué casos corrieron, versiones, entorno y resultado real. Los gates científicos pendientes y las limitaciones de campo permanecen visibles.

## 11. Orden de trabajo y criterio de cierre

| Paso | Entregable | Estado |
| --- | --- | --- |
| 1 | Alcance local, contratos conceptuales, decisiones y aceptación de este documento | DEFINIDO; sin implementación |
| 2 | Adaptador científico MASW y caracterización independiente de rutas/datasets | IMPLEMENTADO; evidencia y límites en docs/app_local_adapter.md |
| 3 | Backend/worker locales, almacenamiento y transacciones de recuperación | EN DESARROLLO; comprobaciones y pendientes en docs/app_local_backend.md |
| 4 | Cliente Web mínimo y revisión concurrente | IMPLEMENTADO; recorrido local y comprobaciones en docs/app_local_web.md |
| 5 | Android, cache persistente y recuperación de cambios | POSTERIOR |
| 6 | Directivas operativas, TRS, suficiencia y ampliación de escala | POSTERIOR |

El primer hito integrado termina cuando APP-01 a APP-16 tienen evidencia ejecutada satisfactoria y el usuario puede repetir el recorrido de carga a revisión después de reiniciar API/worker. No exige que Android o push estén implementados.

El adaptador define sus modelos, caracteriza Oysand/E5 y separa cálculo de carga/renderizado. Backend, workers y Web ya permiten el recorrido local. El trabajo siguiente es **cerrar la demostración integrada reproducible y los límites operativos pendientes del backend**. Las decisiones futuras de framework móvil, proveedor cloud y segundo sitio de campo no bloquean ese paso.

## 12. Relación con los hallazgos de auditoría

| Hallazgo crítico | Tratamiento en el alcance local |
| --- | --- |
| C01: dimensiones acopladas | Invariantes y revisión anotada; suficiencia fija no demostrada |
| C02: OCC no atómico | Agregado ReviewCase y escritura/transacción condicionadas |
| C03: SQL/objetos | Publicación mediante manifiesto verificado y reconciliación |
| C04: outbox ausente | Trabajo/cambio/outbox en transacción, efectos idempotentes |
| C05: workers | Run/Attempt, lease, token vigente y reintento limitado |
| C06: sincronización | Consulta HTTP inicial; recuperación durable antes de Android, sin promesa de push infalible |
| C07: autorización | Membresía por proyecto, actor autenticado y comprobación por objeto |
| C08: scripts específicos | Adaptador explícito, E5 validado y Oysand como regresión exploratoria |

Estos tratamientos son requisitos de diseño. Los hallazgos no se consideran cerrados técnicamente hasta ejecutar sus comprobaciones. La auditoría conserva además los hallazgos altos/medios para los hitos donde corresponden.
