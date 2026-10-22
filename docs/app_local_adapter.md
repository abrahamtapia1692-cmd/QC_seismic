# Adaptador MASW local — primera implementación

Fecha: 2026-10-14. Alcance: paso 2 de [APP-LOCAL-0.1](../app.md).
Esta entrega describe el adaptador. El avance posterior de backend, persistencia y worker se registra en [app_local_backend.md](app_local_backend.md); las interfaces siguen pendientes.

## Qué se implementó

[geoqc/masw/adapter.py](../geoqc/masw/adapter.py) ofrece una entrada tipada para hasta cuatro Shot MASW validados, protocolo, política, revisión de adquisición, exclusión de sensibilidad y referencia de motor explícitos. Devuelve un dosier científico JSON con manifiesto de entradas y digest, sin renderizado, acceso a datasets, escritura de archivos o dependencias web.

El cálculo puro compartido del dosier histórico se extrajo a [dossier_analysis.py](../geoqc/masw/dossier_analysis.py). El generador [report_masw_quality.py](../tools/report_masw_quality.py) conserva carga Oysand, textos de evidencia pendiente y presentación, con un wrapper compatible. Las pruebas comparan los resultados contra fingerprints capturados antes de extraer; no se limitan a comparar dos wrappers de la misma función.

El informe del núcleo y la usabilidad del dosier se conservan como resultados distintos:

| Resultado | Estimador y alcance |
| --- | --- |
| native_diagnostics | MASW-R1 del núcleo, DP y refinamiento de pico existentes; sin calibraciones suministradas al adaptador |
| apparent_usability | DP sobre velocidades de rejilla, alternativas de procesamiento fijadas y política DRAFT |
| trace_observations | Observaciones por receptor en la ventana solicitada; los canales excluidos y faltantes permanecen visibles |

No se sustituye la curva refinada por la curva de rejilla ni se interpreta sensibilidad como sigma. La comparación Oysand conserva su protocolo propio; el caso E5 usa MASWProtocol. El adaptador no convierte ASCII incompleto en un Shot ni inventa metadatos para unificar los recorridos.

## Uso desde CLI

Desde la raíz del repositorio y con el entorno científico instalado:

~~~powershell
.\.venv\Scripts\python.exe -X utf8 -m geoqc masw-dossier examples/e5/masw_plane.sgy --protocol examples/e5/protocol.json --policy configs/masw_usability_v1.json --revision-id local-e5-revision-1 --sensitivity-receiver r0
~~~

La salida estándar contiene exclusivamente el documento JSON; un error de ingesta conserva su diagnóstico y sale con código 2. La exclusión r0 es un experimento de sensibilidad declarado, no una afirmación de que ese receptor sea un trigger. El nombre se valida contra receiver_ids; una exclusión inexistente se rechaza.

La CLI acepta un tiro por invocación. El adaptador Python admite lotes ordenados de hasta cuatro tiros, con una exclusión explícita por tiro y un protocolo común compatible con todos ellos. No se ha implementado aún la recepción de lotes por HTTP ni una cola de procesamiento.

## Uso desde un ejecutor Python

~~~python
from pathlib import Path

from geoqc.io.readers import read_shot
from geoqc.masw.adapter import (
    MASWAdapterInput,
    ReceiverExclusion,
    build_masw_dossier,
    capture_engine_reference,
)
from geoqc.masw.contracts import MASWProtocol
from geoqc.masw.diagnostic_quality import UsabilityPolicy

shot = read_shot(Path("examples/e5/masw_plane.sgy"))
request = MASWAdapterInput(
    acquisition_revision_id="local-e5-revision-1",
    shots=(shot,),
    protocol=MASWProtocol.model_validate_json(
        Path("examples/e5/protocol.json").read_bytes()
    ),
    usability_policy=UsabilityPolicy.model_validate_json(
        Path("configs/masw_usability_v1.json").read_bytes()
    ),
    sensitivity_exclusions=(
        ReceiverExclusion(shot_id=shot.id, receiver_id="r0"),
    ),
    engine_reference=capture_engine_reference(),
)
result = build_masw_dossier(request)
document = result.to_document()
json_text = result.to_json()
~~~

La carga y capture_engine_reference hacen I/O explícito antes del cálculo. La referencia captura hashes del paquete, del estimador MASW y versiones del entorno. El cálculo no vuelve a leer fuentes ni políticas. Un worker futuro podrá invocar la misma función después de autorizar, preparar entradas y verificar su manifiesto.

Para transportar la entrada se usa request.model_dump_json().encode("utf-8") y MASWAdapterInput.model_validate_json(payload_bytes). En Windows no se debe decodificar un payload UTF-8 usando implícitamente la codificación local. La prueba entre procesos verifica que los textos de procedencia y el digest se conserven.

La referencia de motor y acquisition_revision_id proceden de un ejecutor confiable; esta función no autentica usuarios ni consulta la base para verificar esa revisión. El futuro backend no debe aceptar una referencia de motor declarada por el navegador como autoridad científica.

## Salida e inmutabilidad

MASWAdapterResult conserva el contenido como scientific_json inmutable y verifica su scientific_digest al construirse. to_document devuelve una copia independiente; modificar esa copia no altera el resultado. to_json produce el documento de intercambio, con el digest agregado fuera del cuerpo que se firma por hash.

model_dump_json del resultado serializa el envelope interno; no debe confundirse con to_json, que entrega el dosier. Esta distinción evita que diccionarios/arrays mutables cambien silenciosamente un resultado ya identificado.

El manifiesto identifica tiros en orden, hashes de originales/sidecars suministrados por la ingesta, Shot científico, geometría, adquisición, cabeceras, protocolo, política y receptor excluido. No incluye URLs, tiempos de ejecución ni dictámenes humanos. El digest es una comprobación de integridad; no una firma de autoría o certificación.

Los hashes internos usan canonical_hash del proyecto. En el manifiesto, protocolo y política se identifican como modelos tipados mediante canonical_hash(request.protocol) y canonical_hash(request.usability_policy), que incluyen el nombre del modelo. native_diagnostics conserva el hash histórico del protocolo como mapping JSON. Son ámbitos de canonicalización diferentes y no se deben intercambiar para validar calibraciones. El digest del dosier completo sí se verifica directamente sobre el documento JSON sin scientific_digest, como comprueban las pruebas.

Cambiar código introduce hashes de procedencia nuevos aunque las métricas coincidan. El estimador nativo conserva su validación de compatibilidad de calibraciones; las referencias históricas no se reasignan al código nuevo. La entrada pura uncalibrated_masw_diagnostics comparte el cálculo del núcleo y no admite calibraciones ni aprobaciones externas como argumentos.

## Soporte y abstención

- MASW APPARENT, entre 3 y 64 canales, hasta 65 536 muestras/canal, 256 frecuencias y 512 velocidades; estos límites son de admisión, no capacidad medida.
- Ventana física, bins FFT, relojes y geometría compatibles con el transformador existente; no se remuestrea ni infiere t0.
- Pesos unitarios en la política inicial. Otros pesos se rechazan explícitamente; no se evalúan como si fueran uniformes.
- Geometría irregular o soporte espectral incompleto no heredan el kernel uniforme: se conserva NO_EVALUABLE y sus motivos.
- Una máscara que invalida la ventana de un receptor lo excluye del cálculo y conserva su identidad, fracción válida y motivo. No se presenta el cero interno de exclusión como RMS observado.
- Variantes sin soporte se exportan como null, con abstención; JSON no emite NaN/Infinity.
- El orden de soporte publicado sigue el orden físico de canales, incluso al analizar dirección negativa. El signo de q se expresa en el sistema x físico.
- Suficiencia NOT_DEMONSTRATED y eligible_for_acceptance=false. No se añaden bandas validadas ni reglas de liberación de campo.

Todavía no se ha medido rendimiento, consumo máximo, cancelación o aislamiento de un worker real. El adaptador procesa tiros secuencialmente; la admisión HTTP, límites de bytes, recursos del proceso y control de trabajos pertenecen al paso de backend. No hay almacenamiento/publicación transaccional de artefactos en esta entrega.

## Verificación reproducible

Resultado de esta entrega: **43 pruebas de aplicación/dosier y 40 regresiones seleccionadas del núcleo pasaron**, sin fallos, errores ni skips. Ruff pasó para los archivos modificados y mypy para los 63 archivos del paquete. Los reportes y el dosier E5 están enlazados en el índice de evidencia.

Las pruebas de aplicación viven en tools/tests para mantenerlas separadas del manifiesto VID científico existente; no se modificaron requisitos ni marcadores de gates para hacerlas pasar.

~~~powershell
.\.venv\Scripts\python.exe -m pytest tools/tests/test_masw_adapter.py tools/tests/test_masw_extraction_regression.py tools/tests/test_masw_dossier.py tools/tests/test_masw_usability.py -q
.\.venv\Scripts\python.exe -m ruff check geoqc/masw/adapter.py geoqc/masw/dossier_analysis.py geoqc/masw/report.py geoqc/cli.py tools/report_masw_quality.py tools/tests/test_masw_adapter.py tools/tests/test_masw_extraction_regression.py
.\.venv\Scripts\python.exe -m mypy geoqc
~~~

La regresión del núcleo seleccionada también cubre ingesta CLI, límites de calibración, evidencia modal MASW-R1, transformadas, curvas y pipeline waveform/holdout. Al exportar sus propiedades a JUnit se necesita junit_family=xunit1; se mantiene la regla del repositorio de tratar warnings como errores.

Para esa regresión se limitaron OPENBLAS_NUM_THREADS y OMP_NUM_THREADS a 1 en el proceso de pruebas. No se cambió el entorno global ni se prometió que otros entornos produzcan digests binarios idénticos. La caracterización Oysand usa fingerprints exactos del entorno de captura; una actualización de librerías requiere investigar diferencias, no regenerar automáticamente el baseline.

~~~powershell
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
.\.venv\Scripts\python.exe -m pytest tests/unit/test_e1_cli.py tests/unit/test_e5_boundaries.py tests/unit/test_masw_r1.py tests/synthetic/test_e5_pipeline.py tests/synthetic/test_e5_transform.py tests/synthetic/test_e5_curves.py -q -o junit_family=xunit1 --junitxml=evidence/app_local/adapter/core_regression_tests_final.xml
~~~

Las asignaciones anteriores afectan solo la sesión de PowerShell desde la que se ejecutan. Para archivar reportes JUnit existentes y un dosier E5 en un directorio nuevo por ejecución:

~~~powershell
.\.venv\Scripts\python.exe tools/summarize_app_adapter.py
~~~

El colector no ejecuta las pruebas ni certifica que sus XML correspondan a las fuentes actuales: conserva los reportes, sus hashes y una captura de procedencia al archivarlos. Devuelve error si los reportes incluyen fallos, errores, skips o cero casos. El comando de pruebas de aplicación puede añadir -o junit_family=xunit1 --junitxml=evidence/app_local/adapter/application_tests_final.xml para producir su reporte de entrada.

El [baseline previo](../tests/fixtures/app_adapter/oysand_before_extraction.json) conserva los hashes originales. Los resultados de ejecución y alcance se registran en [evidence/app_local/adapter](../evidence/app_local/adapter/README.md). No se regeneraron dosieres históricos ni se cerraron G5 ampliado, G6 o G9.

## Próximo paso

Estado frente a los criterios del plan, dentro del alcance de esta entrega:

| Criterio | Evidencia y límite |
| --- | --- |
| APP-01 | Caracterización Oysand contra hashes previos de resúmenes, arrays y comparaciones |
| APP-02 | Ingesta E5 SEG-Y/sidecar y CLI ejecutable desde otra carpeta |
| APP-03 | Plano sintético de 8 canales, otra geometría/dt/t0 y dirección negativa |
| APP-04 | Igualdad de llamada Python, CLI y entrada UTF-8 serializada; servicio worker pendiente |
| APP-05 | Rechazo de sidecar ausente, relojes incompatibles y pesos fuera de alcance; máscaras/ceros/irregularidad con motivos |
| APP-06 | JSON estricto, digest verificable y manifiesto de entradas/configuración/motor; publicación de artefactos pendiente |
| APP-07 a APP-16 | Requieren backend/Web/integración; no se consideran aprobados por estas pruebas |

Implementar el backend local: adquisición/revisión de metadatos, sesiones de carga, trabajos persistentes, manifiestos publicados, membresías y ReviewCase con OCC/idempotencia. Reutilizar este adaptador dentro de un proceso worker; su existencia todavía no demuestra recuperación frente a caídas ni revisión concurrente.
