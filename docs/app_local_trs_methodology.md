# Cobertura metodológica del dosier TRS local

Comparación con `evidence/trace_quality`, `docs/trace_quality_dossier.md` y
`docs/revision_qc_trs_ruido.md`. Esta auditoría describe la implementación actual;
no incorpora al dosier resultados que no se hayan calculado para su adquisición.

## Integración incorporada tras la auditoría

Las ejecuciones TRS nuevas incorporan `geoqc/qc/adapter.py`: QC común, integridad
digital, política/calificación por traza y agregación con evidencia pendiente.
El JSON opcional `trace_qc` declara QCProtocol, NoiseProtocol y perfil de proyecto.
Sin ese JSON se ejecuta el respaldo de integridad de registro completo, sin
inferir ventanas de ruido o comparabilidad. Se integran diagnósticos nativos de
ruido y coherencia LF cuando se declaran sus ventanas, y similitud mediante
QCProtocol. Las guardas del motor determinan si cada resultado es evaluable.

La Web presenta formas de onda y PSD reducidas solo para visualización, tabla
de QC por canal, razones, intervalos de agregación y examen de ruido antes del
picker. El ejemplo KM declara referencia posterior exploratoria; no declara
independencia, transferencia estacionaria o comparabilidad instrumental verificadas.

Repetibilidad/reciprocidad siguen pendientes de integración del flujo con grupos
de impactos y pares físicos explícitos. El filtrado candidato sigue siendo un
experimento separado, no un paso obligatorio de la adquisición RAW.
Los dosieres históricos conservan sus resultados y muestran que no incluyen QC.
Véase la [guía actual](app_local_trs.md).

## Brecha identificada antes de esta integración

`tools/report_trace_quality.py` compone un dosier de calidad por canal sobre
conjuntos de campo y controles sintéticos. Reutiliza QC común, diagnósticos de
ruido, similitud y evaluación por traza. Sus imágenes y resultados pertenecen
a los datos y protocolos documentados en ese informe, no al KM cargado en la Web.

La Web ejecutaba `geoqc_app/calculate.py` → `geoqc/trs/adapter.py` →
`geoqc/trs/report.py`. Ese recorrido producía picks, ramas y estados condicionados
de parámetros/inversión, con hashes y faltantes. El adaptador no invocaba
`common_qc`, `noise_diagnostics` ni `local_similarity`. El informe TRS nativo
devuelve `quality_status: null`; no constituye una evaluación de calidad por traza.

| Etapa | Motor / dosier de desarrollo | Web TRS antes de la integración |
|---|---|---|
| Ingesta y procedencia | Muestras, metadatos, geometría y hashes | Integrado |
| Integridad por canal | Soporte válido, estadísticas, canal muerto/constante, cola digital | No integrado como informe QC; el preflight de formato no lo sustituye |
| SNR y clipping | Ventanas, independencia/estacionariedad, rails, escala y apilamiento explícitos | No integrado |
| Ruido y espectros | PSD, potencias por bloques, LF parcial, candidatos de líneas y coherencia con soporte | No integrado |
| Similitud local | Ventana, vecindario, desfases y consenso declarados | No integrado |
| Calidad por traza y registro | Hallazgos, revisión y evidencia pendiente; intervalo de porcentaje bueno | No integrado |
| Picking TRS | Onset, abstenciones, incertidumbre y calibración | Integrado; KM sin calibración temporal |
| Ramas y parámetros | Ajustes y modelos condicionados a su evidencia | Integrado con abstenciones; KM sin modelo verificado |
| Repetibilidad y reciprocidad | Funciones con observaciones/protocolos específicos | Sin integración del flujo multiimpacto/multifuente |
| Filtrado candidato | Copia experimental y verificación de efecto en el picker | Sin integración; no es un filtro obligatorio del recorrido RAW |
| Suficiencia, procedencia y revisión | Evidencia científica separada de la decisión humana | Integrado; suficiencia no demostrada |

## Consecuencias para el ejemplo KM

Los cinco tiempos sin calibrar, diecisiete abstenciones ambiguas y dos ausencias
del F1 describen el **picker**, no canales buenos, regulares o malos. Una
abstención del picker no prueba mala adquisición. La vista gráfica de esos
resultados tampoco añade las etapas QC pendientes.

La ventana tardía de 1.5–2 s se declaró como referencia exploratoria del picker;
eso no verifica que esté libre de señal ni que el ruido sea transferible a la
ventana de llegada. No debe convertirse automáticamente en ruido independiente
o estacionario verificado para aprobar SNR. La escala/rails ADC y la convención
de STACK siguen requiriendo su evidencia para clipping.

No corresponde transferir al KM las ventanas, radio de vecindario o resultados
de Chevremont, ni los resultados del experimento sintético de filtrado.

## Contrato metodológico de la integración

El dosier completo debe conservar, por registro, el protocolo QC explícito y sus
resultados nativos; mostrar las trazas con normalización solo de visualización;
y presentar métricas, estados y motivos antes del picking. La evaluación vigente
es `data_assessment`, con intervalo por evidencia pendiente, conservando aparte
el conteo histórico `data_quality`. Las trazas no evaluables permanecen en el
denominador y no se presentan como fallas demostradas.

Ruido, similitud, repetibilidad y reciprocidad necesitan sus propios protocolos
y relaciones entre registros. Las etapas sin soporte deben indicar su estado y
el motivo; no simularse mediante imágenes o valores de otro conjunto. Las
pruebas sintéticas sustentan la implementación, pero no son mediciones del KM.

El dosier ya publicado y su digest se conservan. Integrar estos cálculos requiere
una nueva ejecución con los mismos originales y una nueva especificación
metodológica, conservando el vínculo a la revisión de adquisición. No requiere
alterar los originales ni sobrescribir la revisión humana anterior.
