Esta arquitectura transforma el protocolo matemático y diagnóstico de GeoQC-Field (Dosier 2.0) en una plataforma distribuida, orientada a eventos y tolerante a fallos. El diseño preserva en el modelo de dominio el Principio de las Dos Evaluaciones Desacopladas (Dimensión 1: Calidad Diagnóstica por Banda/Traza vs. Dimensión 2: Suficiencia del Objetivo Ingenieril) y garantiza consistencia en tiempo real entre la aplicación Android y la Plataforma Web.

1. Arquitectura de Software y Patrones de Escalabilidad
Para evitar que el cálculo intensivo (transformadas de Fourier con ventana de Hann, escaneo direccional 
q∈[−q 
N
​
 ,+q 
N
​
 ], programación dinámica de crestas y picado causal STA/LTA + AIC) bloquee las peticiones HTTP de los usuarios en campo o gabinete, el sistema implementa cuatro patrones arquitectónicos clave:

Desacoplamiento Asíncrono Basado en Colas (Worker Pool Pattern):
La subida de archivos .sg2 / .su desde campo se realiza directamente hacia un almacenamiento de objetos inmutable (MinIO / AWS S3) mediante Pre-signed URLs, calculando al vuelo el hash criptográfico SHA-256. El API principal solo registra los metadatos geométricos (
dx,x 
1
​
 ,dt,T 
pre
​
 ) y publica una tarea en el broker de mensajes (Redis Streams / RabbitMQ). Un clúster auto-escalable de Workers Científicos consume la tarea, ejecuta report_trs_dossier o report_masw_quality y persiste el dossier.json, .pdf, .html y .csv.

Patrón Strategy y Template Method en el Motor Científico:
Tanto MASW como TRS comparten el pipeline estructural de validación inicial (Paso 1: Finitud, 
NaN/Inf, regularidad geométrica 
max 
k
​
 ∣dx 
k
​
 −dx∣≤ϵ; Paso 2: Diagnóstico de canal muerto, RMS nativo y sospecha morfológica de clipping), pero delegan el análisis físico específico a estrategias intercambiables parametrizadas por políticas versionadas (masw_usability_v1.json y TRACE_QUALITY_V1_DRAFT).

Sincronización Bidireccional con Control de Concurrencia Optimista (OCC):
Si el Especialista de Gabinete tiene abierto el mismo dosier en la Web y en la App Android, cada entidad QCDossier mantiene un atributo version (entero incremental) y un etag. Cualquier dictamen enviado desde Android incluye el version leído; al confirmarse la transacción en PostgreSQL, el version se incrementa y se emite un evento por WebSockets y FCM Data Message que actualiza instantáneamente la interfaz Web (y viceversa). Si la otra plataforma intenta enviar un dictamen sobre una versión obsoleta, el backend rechaza la escritura con un estado 409 Conflict e hidrata la vista con la decisión ya tomada.

Transactional Outbox Pattern para Notificaciones Críticas:
Garantiza que ninguna notificación Push a Android se pierda ni se envíe antes de que los artefactos del Dosier 2.0 estén completamente confirmados en almacenamiento.

2. Diagrama de Casos de Uso (UML)
El siguiente diagrama modela la interacción completa entre el Operador de Campo, el Especialista de Gabinete (Revisor), el Administrador de Proyecto, el Motor Científico GeoQC y el Servicio de Sincronización/Notificaciones, contemplando todas las decisiones operativas derivadas del Dosier 2.0:

Fragmento de código
flowchart LR
    %% Actores
    subgraph Actores_Campo ["Terreno (Web / Tablet)"]
        OP(["👷 Operador de Campo"])
    end

    subgraph Actores_Gabinete ["Gabinete (Android App / Web)"]
        REV(["🧑‍🔬 Especialista de Gabinete"])
        ADM(["⚙️ Admin de Proyecto"])
    end

    subgraph Sistemas_Externos ["Sistemas y Motores Internos"]
        ENG(["🧮 Motor Científico GeoQC\n(Microservicio Worker)"])
        SYNC(["🔔 Hub Notificaciones y Sync\n(FCM + WebSockets)"])
    end

    %% Frontera del Sistema
    subgraph Sistema_GeoQC ["Plataforma Distribuida GeoQC-Field 2.0"]
        direction TB
        
        %% Casos de Uso: Ingesta y Campo
        UC_UPLOAD("UC01: Cargar Registros Sísmicos\n(.sg2, .su, ASCII)")
        UC_GEOM("UC02: Declarar Geometría y Metadatos\n(dx, x1, dt, T_pre, canal trigger)")
        UC_HASH("UC03: Verificar Integridad SHA-256\ny Finitud Digital (NaN/Inf)")
        UC_EXEC_DIR("UC04: Ejecutar Directiva de Campo\n(Repetir tiro / Reubicar / Corregir)")

        %% Casos de Uso: Procesamiento Científico
        UC_PROC("UC05: Generar Dosier Diagnóstico 2.0")
        UC_MASW("UC05a: Evaluar Calidad MASW\n(I(f,q), Lóbulo, Rival, Sensibilidad)")
        UC_TRS("UC05b: Evaluar Calidad TRS\n(STA/LTA+AIC, SNR, Fermat, Ramas)")
        UC_DECOUPLE("UC06: Desacoplar Dimensión 1 (Calidad)\nde Dimensión 2 (Suficiencia PENDIENTE)")

        %% Casos de Uso: Revisión y Dictamen (Web & Android)
        UC_NOTIF("UC07: Notificar Dosier Listo\n(Push Android FCM + Alerta Web)")
        UC_VIEW("UC08: Inspeccionar Dosier Interactivo\n(Espectros, Hodógrafas, Alertas Nyquist/Clip)")
        UC_DECIDE("UC09: Emitir Dictamen de Adquisición")
        
        %% Especializaciones de Dictamen
        UC_APP("UC09a: Aprobar Adquisición\n(Liberar Estación/Tendido)")
        UC_OBS("UC09b: Aprobar con Observaciones\n(Bandas REVISAR / Clipping Moderado)")
        UC_REP("UC09c: Reprobar: Solicitar Repetición\n(Baja Repetibilidad r o Baja SNR)")
        UC_RELOC("UC09d: Reprobar: Solicitar Reubicación\n(LOBE_AT_NYQUIST / DIRECTION_UNRESOLVED)")
        UC_FIX("UC09e: Reprobar: Corregir Geometría/Trigger\n(Error Reciprocidad Fermat / Canal 1)")

        %% Suficiencia e Hitos Externos
        UC_SUFF("UC10: Actualizar Suficiencia del Objetivo\n(Anexar Pozo / Cross-hole / Topografía)")
        UC_SYNC("UC11: Sincronizar Estado en Tiempo Real\n(Web <-> Android con Control Optimista)")
        UC_POLICY("UC12: Configurar Políticas de Umbrales\n(masw_usability_v1 / trace_quality_v1)")
    end

    %% Relaciones Operador
    OP --> UC_UPLOAD
    UC_UPLOAD -.->|"<<include>>"| UC_GEOM
    UC_UPLOAD -.->|"<<include>>"| UC_HASH
    OP --> UC_EXEC_DIR
    UC_EXEC_DIR -.->|"<<extend>>\n[Reprobado]"| UC_UPLOAD

    %% Relaciones Motor Científico
    UC_UPLOAD --> UC_PROC
    UC_PROC <-- ENG
    UC_PROC -.->|"<<include>>"| UC_DECOUPLE
    UC_MASW -.->|"es un"| UC_PROC
    UC_TRS -.->|"es un"| UC_PROC

    %% Relaciones Notificación y Revisión
    UC_PROC --> UC_NOTIF
    UC_NOTIF --> SYNC
    SYNC --> REV
    SYNC --> OP

    REV --> UC_VIEW
    REV --> UC_DECIDE
    REV --> UC_SUFF
    ADM --> UC_POLICY

    %% Ramas de Decisión
    UC_APP -.->|"generaliza"| UC_DECIDE
    UC_OBS -.->|"generaliza"| UC_DECIDE
    UC_REP -.->|"generaliza"| UC_DECIDE
    UC_RELOC -.->|"generaliza"| UC_DECIDE
    UC_FIX -.->|"generaliza"| UC_DECIDE

    %% Sincronización Bidireccional
    UC_DECIDE -.->|"<<include>>"| UC_SYNC
    UC_SUFF -.->|"<<include>>"| UC_SYNC
    UC_SYNC --> SYNC
3. Diagrama de Clases de Dominio y Microservicio (UML)
El diseño de clases separa responsabilidades en cuatro paquetes cohesivos:

Gestión de Usuarios, Proyectos y Sincronización (Core & Sync): Maneja RBAC, concurrencia optimista (version), auditoría y despacho multiplataforma (Web + Android).

Ingesta Sísmica y Geometría (Acquisition & Geometry): Representa los archivos .sg2/.su, trazas individuales, estaciones de disparo y validación de regularidad espacial (
ϵ=10 
−9
  m).

Motor Científico Polimórfico (GeoQC Engine Microservice): Encapsula los algoritmos matemáticos sin acoplarlos a la base de datos ni a la interfaz gráfica.

Dosier 2.0 y Dimensiones Desacopladas (Dossier 2.0 Model): Modela explícitamente la separación entre la Dimensión 1 (resultados por banda de frecuencia MASW o por traza/tendido TRS) y la Dimensión 2 (TargetSufficiencyEvaluation), además de las directivas de revisión.

Fragmento de código
classDiagram
    direction TB

    %% ==========================================
    %% PAQUETE 1: USUARIOS, ROLES Y SINCRONIZACIÓN
    %% ==========================================
    class User {
        +UUID id
        +String fullName
        +String email
        +UserRole role
        +List~DeviceToken~ androidFcmTokens
        +authenticate()
    }

    class UserRole {
        <<enumeration>>
        FIELD_OPERATOR
        OFFICE_REVIEWER
        PROJECT_ADMIN
    }

    class SyncEventPayload {
        +UUID eventId
        +UUID dossierId
        +Int8 newVersion
        +String sourcePlatform
        +ReviewStatus currentStatus
        +DateTime timestamp
        +String canonicalDigest
    }

    class NotificationAndSyncHub {
        +publishWebSocketUpdate(UUID projectId, SyncEventPayload payload)
        +sendAndroidPushFCM(List~UUID~ userIds, SyncEventPayload payload)
        +validateOptimisticLock(UUID dossierId, Int8 clientVersion) Boolean
    }

    %% ==========================================
    %% PAQUETE 2: ADQUISICIÓN Y GEOMETRÍA DE CAMPO
    %% ==========================================
    class SeismicSurveyAcquisition {
        +UUID id
        +String projectSlug
        +String stationKmCode
        +SurveyTechnique technique
        +AcquisitionStatus status
        +Int8 version
        +UUID uploadedByOperatorId
        +DateTime acquiredAt
        +validateMinimumInputs() Boolean
    }

    class SurveyTechnique {
        <<enumeration>>
        MASW
        TRS
    }

    class ArrayGeometry {
        +Int numChannels
        +Float64 dxNominal
        +Float64 totalApertureL
        +List~Float64~ receiverCoordsX
        +List~Float64~ receiverCoordsY
        +List~Float64~ receiverCoordsZ
        +Boolean isUniformArray
        +GeometrySupportFlag kernelSupport
        +evaluateRegularity(Float64 epsilon) GeometrySupportFlag
    }

    class GeometrySupportFlag {
        <<enumeration>>
        UNIFORM_SUPPORTED
        KERNEL_UNSUPPORTED
        INCOMPLETE_GEOMETRY
    }

    class SeismicShotRecord {
        +UUID id
        +String filename
        +String sha256Hash
        +String s3ObjectUri
        +Float64 dtSeconds
        +Float64 preTriggerSeconds
        +Float64 sourceCoordinateX
        +Float64 sourceOffsetX1
        +Int triggerChannelIndex
        +Int numSamplesM
        +Boolean allSamplesFinite
    }

    class RawTraceChannel {
        +Int channelIndex
        +Float64 positionX
        +Float64 rmsNative
        +Float64 peakToPeak
        +Boolean isDeadOrConstant
        +Float64 clippingFraction
        +Boolean clippingSuspected
        +Int maxPlateauLengthK
    }

    %% ==========================================
    %% PAQUETE 3: MOTOR CIENTÍFICO (MICROSERVICIO)
    %% ==========================================
    class IQCDiagnosticEngine {
        <<interface>>
        +executeDiagnostic(SeismicSurveyAcquisition survey, QCPolicyConfig policy) QCDossier20
    }

    class MASWDiagnosticEngine {
        +computePhaseShiftSignedQ(SeismicShotRecord shot, Float64 pisoRel) Matrix2D
        +computeMainLobeExclusionZone(Float64 q0, Int N, Float64 dx) Interval
        +extractDynamicProgrammingRidge(Matrix2D Ifq, Float64 lambda, Float64 s0) DispersionCurve
        +evaluateProcessingSensitivity(SeismicShotRecord shot, DispersionCurve baseCurve) List~Float64~
        +evaluateMultiShotConsistency(List~DispersionCurve~ curves) MultiShotComparison
    }

    class TRSDiagnosticEngine {
        +detectCausalOnsetSTALTA_AIC(RawTraceChannel trace, Float64 staWin, Float64 ltaWin) Float64
        +computeConditionalSNR(RawTraceChannel trace, Float64 tOnset, Float64 tPre) Float64
        +assessGlobalSpreadQuality(List~TRSTraceDiagnostic~ traces) TRSSpreadAssessment
        +fitHodographBranches(List~OnsetPick~ picks) HodographModel
        +evaluateFermatReciprocity(List~ShotPair~ conjugatePairs, Float64 tolMs) List~ReciprocityResult~
        +computeIntraSourceRepeatability(List~SeismicShotRecord~ stackedShots) Float64
    }

    class QCPolicyConfig {
        +String policyId
        +String versionTag
        +Map~String, Float64~ thresholds
        +String sha256PolicyDigest
    }

    %% ==========================================
    %% PAQUETE 4: DOSIER 2.0 (EVALUACIÓN DESACOPLADA)
    %% ==========================================
    class QCDossier20 {
        +UUID id
        +UUID acquisitionId
        +String canonicalJsonDigest
        +DateTime generatedAt
        +Int8 reviewVersion
        +String etag
        +Map~ArtifactType, String~ artifactUris
        +applyReviewDecision(ReviewDecision decision, Int8 expectedVersion)
    }

    class DiagnosticQualityDimension {
        <<abstract>>
        +String policyApplied
        +String globalSummaryStatus
        +List~String~ primaryWarnings
    }

    class MASWDiagnosticDimension {
        +List~MASWFrequencyBin~ frequencyBins
        +List~MASWUsabilityBand~ usabilityBands
        +List~MultiShotPairDiscrepancy~ offsetComparisons
        +String uncertaintyStatus
    }

    class MASWFrequencyBin {
        +Float64 frequencyHz
        +Float64 apparentVelocityC0
        +Float64 signedWavenumberQ0
        +Float64 crestCoherenceI
        +Float64 crestBackgroundContrastC
        +Float64 rivalRatioR
        +Float64 maxSensitivityS
        +MASWBandStatus status
        +List~MASWDiagnosticReason~ reasons
    }

    class MASWBandStatus {
        <<enumeration>>
        UTILIZABLE_STAR
        REVISAR
        NO_UTILIZABLE
        NO_EVALUABLE
    }

    class MASWDiagnosticReason {
        <<enumeration>>
        OK
        DIRECTION_UNRESOLVED
        NYQUIST_LIMIT
        LOBE_AT_NYQUIST
        COMPETING_PEAK
        PROCESSING_SENSITIVE
        LOW_CONTRAST
        KERNEL_UNSUPPORTED
    }

    class TRSDiagnosticDimension {
        +Float64 pLowerBoundPct
        +Float64 pUpperBoundPct
        +TRSSpreadStatus globalSpreadStatus
        +Float64 onsetCoveragePct
        +Float64 meanRepeatabilityPearsonR
        +List~TRSTraceDiagnostic~ traceDiagnostics
        +List~ReciprocityResult~ fermatPairs
        +List~HodographModel~ branchModels
    }

    class TRSTraceDiagnostic {
        +Int shotIndex
        +Int channelIndex
        +Float64 snrNetDb
        +Float64 clippingFraction
        +Float64 aicOnsetTimeMs
        +TRSTraceStatus traceStatus
        +List~String~ findings
    }

    class TRSTraceStatus {
        <<enumeration>>
        BUENA
        REGULAR
        MALA
        NO_EVALUABLE
    }

    class TargetSufficiencyDimension {
        +EngineeringTargetType targetType
        +SufficiencyStatus status
        +List~String~ missingExternalEvidence
        +List~ExternalEvidenceAttachment~ verifiedAttachments
        +evaluateSufficiency() SufficiencyStatus
    }

    class SufficiencyStatus {
        <<enumeration>>
        NOT_DEMONSTRATED_PENDIENTE
        DEMONSTRATED_VERIFIED
        INSUFFICIENT_COVERAGE
    }

    %% ==========================================
    %% PAQUETE 5: REVISIÓN Y DIRECTIVAS DE CAMPO
    %% ==========================================
    class ReviewDecision {
        +UUID id
        +UUID dossierId
        +UUID reviewerUserId
        +String clientPlatform
        +DecisionVerdict verdict
        +FieldActionDirective directive
        +String technicalJustification
        +DateTime decidedAt
    }

    class DecisionVerdict {
        <<enumeration>>
        APPROVED
        APPROVED_WITH_OBSERVATIONS
        REJECTED_ACTION_REQUIRED
    }

    class FieldActionDirective {
        +DirectiveType actionType
        +List~Int~ targetShotStations
        +Float64 suggestedNewDx
        +Float64 suggestedNewOffsetX1
        +String instructionsForOperator
        +Boolean isResolvedByField
    }

    class DirectiveType {
        <<enumeration>>
        NONE_RELEASE_CREW
        REPEAT_SHOT_INCREASE_STACKING
        RELOCATE_SPREAD_CHANGE_DX
        ADD_SOURCE_OFFSET
        FIX_TRIGGER_OR_CHANNEL_MAPPING
        REDUCE_GAIN_AVOID_CLIPPING
    }

    %% Relaciones entre Clases
    User "1" --> "*" SeismicSurveyAcquisition : sube en campo
    User "1" --> "*" ReviewDecision : dictamina en gabinete
    SeismicSurveyAcquisition "1" *-- "1" ArrayGeometry : contiene
    SeismicSurveyAcquisition "1" *-- "1..*" SeismicShotRecord : agrupa
    SeismicShotRecord "1" *-- "3..*" RawTraceChannel : compuesto por

    IQCDiagnosticEngine <|.. MASWDiagnosticEngine : implementa
    IQCDiagnosticEngine <|.. TRSDiagnosticEngine : implementa
    IQCDiagnosticEngine ..> QCPolicyConfig : usa reglas
    IQCDiagnosticEngine ..> SeismicSurveyAcquisition : procesa
    IQCDiagnosticEngine ..> QCDossier20 : produce

    QCDossier20 "1" *-- "1" DiagnosticQualityDimension : Dimensión 1 (Interna)
    QCDossier20 "1" *-- "1" TargetSufficiencyDimension : Dimensión 2 (Ingenieril)
    DiagnosticQualityDimension <|-- MASWDiagnosticDimension : especializa
    DiagnosticQualityDimension <|-- TRSDiagnosticDimension : especializa

    MASWDiagnosticDimension "1" *-- "1..*" MASWFrequencyBin : evalúa
    TRSDiagnosticDimension "1" *-- "1..*" TRSTraceDiagnostic : evalúa

    QCDossier20 "1" --> "0..*" ReviewDecision : historial auditable
    ReviewDecision "1" *-- "0..1" FieldActionDirective : ordena a campo
    QCDossier20 ..> NotificationAndSyncHub : dispara evento
4. Flujo de Sincronización Bidireccional (Web ↔ Android) y Máquina de Estados
4.1 Máquina de Estados del Levantamiento y Dosier
El ciclo de vida impide estados inconsistentes (por ejemplo, que un operador modifique un archivo ya aprobado o que dos revisores sobreescriban decisiones simultáneamente):

Fragmento de código
stateDiagram-v2
    [*] --> UPLOADING : Operador inicia carga en Web
    UPLOADING --> QUEUED_FOR_QC : SHA-256 verificado + Geometría completa
    UPLOADING --> INVALID_INPUT : Faltan dt/dx o NaN/Inf detectados (Paso 1)
    INVALID_INPUT --> UPLOADING : Operador corrige metadatos/archivos

    QUEUED_FOR_QC --> PROCESSING_QC : Worker Científico toma tarea
    PROCESSING_QC --> PENDING_REVIEW : Dosier 2.0 generado (Push FCM enviado a Android + WebSocket a Web)

    state PENDING_REVIEW {
        [*] --> UNOPENED
        UNOPENED --> IN_INSPECTION : Revisor abre en Android o Web (Presencia activa)
    }

    PENDING_REVIEW --> APPROVED : Dictamen APROBADO (v=v+1, Sync Web + Android)
    PENDING_REVIEW --> APPROVED_WITH_OBS : Dictamen APROBADO CON OBSERVACIONES (v=v+1)
    PENDING_REVIEW --> ACTION_REQUIRED_IN_FIELD : Dictamen REPROBADO + Directiva (Repetir/Reubicar/Corregir)

    ACTION_REQUIRED_IN_FIELD --> UPLOADING : Operador ejecuta directiva y sube nuevo intento (Vinculado al padre)
    APPROVED --> SUFFICIENCY_VERIFIED : Se anexa evidencia externa (Pozo / Topografía) -> Dimensión 2 DEMOSTRADA
    APPROVED_WITH_OBS --> SUFFICIENCY_VERIFIED : Se anexa evidencia externa
4.2 Secuencia de Sincronización Multiplataforma sin Condiciones de Carrera
Cuando el Especialista de Gabinete revisa el dosier desde la App Android mientras la Plataforma Web también tiene la vista abierta (en gabinete o en la laptop de campo), la sincronización opera bajo este protocolo:

Fragmento de código
sequenceDiagram
    autonumber
    actor OP as 👷 Operador (Web Campo)
    participant API as 🚀 API Gateway / Core (FastAPI)
    participant S3 as 📦 MinIO / S3 + PostgreSQL
    participant WRK as 🧮 GeoQC Engine Worker
    participant HUB as 🔔 Redis Pub/Sub + FCM Hub
    actor REV_MOB as 📱 Revisor (App Android)
    actor REV_WEB as 💻 Revisor ( Consola Web )

    OP->>API: POST /acquisitions (Metadatos: dx, x1, dt) + Subida .sg2
    API->>S3: Persiste .sg2 (SHA-256) y crea registro (status=QUEUED, version=1)
    API->>WRK: Encola Job [Run_GeoQC_Dossier_2_0]
    API-->>OP: 202 Accepted (UI Web muestra barra de progreso en tiempo real)

    WRK->>S3: Lee .sg2, ejecuta MASW/TRS Engine
    WRK->>S3: Guarda dossier.json, .pdf, .html, .csv (status=PENDING_REVIEW, version=2)
    WRK->>HUB: Publica evento DOSSIER_GENERATED (dossier_id, digest, version=2)

    par Notificación Push y Tiempo Real
        HUB->>REV_MOB: Push Notification FCM ("Nuevo Dosier TRS KM 52+500 listo para revisión")
        HUB->>REV_WEB: WebSocket Event [DOSSIER_READY] (Actualiza bandeja Web sin recargar)
        HUB->>OP: WebSocket Event [DOSSIER_READY] (Habilita vista preliminar en campo)
    end

    REV_MOB->>API: GET /dossiers/{id} (Recibe JSON + ETag: "v2")
    REV_WEB->>API: GET /dossiers/{id} (Recibe JSON + ETag: "v2")

    Note over REV_MOB, REV_WEB: El revisor inspecciona en Android y decide REPROBAR por LOBE_AT_NYQUIST

    REV_MOB->>API: POST /dossiers/{id}/reviews (If-Match: "v2", verdict=REJECTED, directive=RELOCATE_SPREAD)
    API->>S3: Verifica version==2 -> Actualiza a version=3, guarda ReviewDecision
    API->>HUB: Publica DOSSIER_REVIEWED (version=3, verdict=REJECTED, platform="ANDROID")
    API-->>REV_MOB: 200 OK (ETag: "v3")

    par Sincronización Instantánea Multiplataforma
        HUB->>REV_WEB: WebSocket [STATE_SYNC v3]: Actualiza UI Web a "REPROBADO" y bloquea formulario
        HUB->>OP: WebSocket + Push [DIRECTIVE_ISSUED]: Alerta roja en campo ("Reubicar tendido: dx=2.0m")
    end

    opt Intento de edición tardía desde una pestaña Web desactualizada
        REV_WEB->>API: POST /dossiers/{id}/reviews (If-Match: "v2", verdict=APPROVED)
        API-->>REV_WEB: 409 Conflict (Estado actual ya es v3 dictaminado en Android)
    end
5. Decisiones Técnicas Clave para Mantenibilidad y Escalabilidad
A. Contrato API e Idempotencia para Conectividad Intermitente en Campo
En exploraciones geofísicas, la conexión móvil suele ser inestable (3G/LTE intermitente o Starlink).

Subida Resumible (TUS Protocol / S3 Multipart): Si el operador en el KM 40+672 sube 38 archivos .sg2 y pierde señal al archivo 25, la carga se reanuda desde el último chunk verificado por SHA-256 sin retransmitir los primeros 24.

Payload Ligero para Android (dossier_summary.json): Aunque el motor genera el dossier.pdf y dossier.html completos, la App Android consume primero el endpoint /dossiers/{id}/lightweight (~15 KB en formato JSON comprimido con Brotli) que contiene los arreglos de las curvas 
c
^
 (f), bandas de usabilidad (UTILIZABLE*, REVISAR, NO_UTILIZABLE), matriz de calidad de trazas y pares de Fermat, renderizándolos de forma nativa en el teléfono en menos de 200 ms. Si el revisor desea descargar el PDF formal, lo solicita bajo demanda.

B. Trazabilidad Criptográfica e Inmutabilidad (Linaje de Versiones)
Cuando un levantamiento es Reprobado y el operador ejecuta una repetición o reubicación en campo, nunca se sobrescribe el QCDossier20 original.

Se crea una nueva instancia SeismicSurveyAcquisition con un puntero parent_acquisition_id hacia el levantamiento reprobado. Esto permite auditar cómo mejoró la repetibilidad (
r de Pearson pasando de 
0.60 a 
0.78) o cómo desapareció la alerta LOBE_AT_NYQUIST al reducir 
dx de 
5.0 m a 
2.0 m.

C. Estructura Modular de Microservicios Sugerida
Para mantener el código limpio y desacoplado:

geoqc-scientific-core (Paquete Python/C++ puro sin dependencias web): Contiene únicamente la matemática del Dosier 2.0 (masw, trs, policies). Se puede ejecutar tanto por CLI en una laptop desconectada como dentro del contenedor Worker.

geoqc-worker-service (Celery / FastStream + Docker): Envuelve geoqc-scientific-core, descarga de S3, ejecuta el cálculo en procesos aislados y sube resultados.

geoqc-api-service (FastAPI + SQLAlchemy Async + Pydantic v2): Maneja autenticación JWT, roles, máquina de estados, concurrencia optimista (ETag), WebSockets y envío a Firebase Cloud Messaging (FCM).

6. Explorador Interactivo de Arquitectura y Flujo de Sincronización
Utiliza los controles del siguiente componente interactivo para recorrer paso a paso cómo fluyen los datos, las validaciones del Dosier 2.0 y la sincronización en tiempo real entre el terreno, el microservicio científico y las plataformas Web/Android: