# Incorporación de auditoría — SDD v1.4

Fecha: 2026-10-03. Documento de trabajo: [SDD v1.4](../SDD_QC_Geofisico_MASW_TRS_v1_4.md).

**Actualización 2026-10-12:** [MASW-R1](masw_review_2026_10_12.md) revisa el adjunto externo y la implementación existente E5. Incorpora anexo D, ocho obligaciones NOT_RUN y [ADR 0002](adr/0002-masw-r1.md). La evidencia G0–G5 anterior se conserva para su alcance base; no cierra el alcance ampliado. Las notas de avance siguientes son históricas. El desarrollo próximo debe cubrir RM-08/RM-02/RM-03 antes de confiar en salidas MASW para E6; G9 permanece pendiente.

**Implementación posterior:** [primera entrega MASW-R1](masw_r1_implementation.md): contratos 1.4-r1 con migración conservadora, autoridad modal separada de payload, unión con covarianza conjunta y runner con criterios RM. Se conservan pendientes de cohorte modal y de integración E6/E8; pruebas acotadas no cierran esos alcances.

**Estado al incorporar la revisión documental:** correcciones incorporadas a la especificación; implementación, pruebas del producto y validación de campo pendientes en ese momento. No se declara cerrado ningún hallazgo experimental ni gate mediante cambios de texto.

**Avance posterior:** E0 implementado; [G0](../evidence/e0/G0.json) pasó 96 casos que cubren 11 obligaciones, sin skips, con ruff/formato/mypy strict. La tabla siguiente conserva el registro de incorporación documental; la ejecución vigente de las obligaciones E0 se consulta en esa evidencia. Los demás algoritmos, la resolución completa de los hallazgos y la calibración de campo siguen pendientes.

**Avance E1/E3:** [la ejecución conjunta](../evidence/e1_e3/execution.json) vuelve a comprobar G0 y evalúa G1/G3 con cobertura, referencias externas y convergencia. El [alcance habilitado](e1_e3_implementation.md) distingue variantes de formato y dominio sintético. No cierra V-E3-8, criterios de campo cercano ni G9.

La v1.3, fuentes Python y evidencia de auditoría permanecen intactas. El motivo matemático de modificar los requisitos erróneos está en [ADR 0001](adr/0001-revision-teorica-del-plan.md); los contraejemplos completos, en [findings.md](findings.md). El [manifiesto](validation_manifest_v1_4.json) contiene todos los vínculos entre hallazgo y tests.

## Cambios por hallazgo

| Hallazgo | Incorporación a v1.4 | Evidencia de implementación/calibración pendiente |
|---|---|---|
| H01 | NACD del centro separado del ratio al receptor próximo; retirados presets operativos no transferibles | V-E0-4, V-E5-9/10 |
| H02 | Respuesta compleja/relativa y banda observada; frecuencia natural no es límite físico | V-E0-8, V-E2-9 |
| H03 | Planificación, banda observada, alcance nominal y resolución del objetivo separados | V-E0-5, V-E5-14/15/22 |
| H04 | FWHM de amplitud/potencia separado y conversión exacta q→c | V-E5-3 |
| H05 | Resolución distinta de incertidumbre estadística; dos COV diferentes | V-E5-11/12 |
| H06 | Rayleigh asintótica sin dominancia global; contraprueba obligatoria | V-E5-17 |
| H07 | Dependencia de receptores distinta de multiplicidad; nula del máximo y ruido coherente | V-E5-17b/18/21 |
| H08 | Generador cercano convergido antes de validar criterio cercano | V-E3-8, V-E5-10 |
| H09 | No identificabilidad de capas ocultas como resultado válido; test imposible reemplazado | V-E4-10 |
| H10 | Onset causal, AIC con tamaños explícitos y sesgo de filtro documentado | V-E3-1, V-E4-1/2/3 |
| H11 | Calidad/completitud/elegibilidad separadas; desconocidos obligatorios bloquean aceptación | V-E6-1/2/4/5 |
| H12 | Dependencias G0→G1/G3→G2; referencia física adelantada y calibración G9 distinta | V-E0-10 |
| H13 | Gates enumeran todos los IDs, incluyendo los antes omitidos | V-E0-10 |
| H14 | Rails conocidos para clipping confirmado; máximo observado no es FS | V-E2-3 |
| H15 | Polaridad con alineación física; anomalía de amplitud sin causa exclusiva | V-E2-2/6 |
| H16 | Covarianza y potencia de reciprocidad; efecto0.333ms compatible con tol1ms | V-E4-5/6/7 |
| H17 | Dominio de fórmulas y modelos explícito; no convertir inaplicabilidad geológica en fallo de datos | V-E3-2, V-E4-8/9 |
| H18 | Geometría3D/máscaras/soporte/dirección; permutación distinta de reflexión | V-E0-7, V-E1-4/5, V-E5-4/6 |
| H19 | Coherencia distinta de energía; identidad modal confirmada/aparente/desconocida | V-E5-7/8 |
| H20 | Hits/ángulos como cobertura; resolución/ROI/malla y vacío desconocido | V-E4-18/19/20/21 |
| H21 | Misfit, convergencia y recuperación separados; utilidad Vs30 obligatoria para el perfil | V-E4-14/15, V-E5-16 |
| H22 | CI/potencia/agrupación por sitio; diez sitios solo piloto | V-E9-1/3 |
| H23 | Pre/posttrigger y velocidad de grupo; coherencia banda/muestreo/duración | V-E2-1/5, V-E9-4 |
| H24 | SNR neta/total y dB/lineal separados; stack condicionado por modelo | V-E2-4/8, V-E6-3 |
| H25 | Contratos de tiempo, máscaras, respuesta, incertidumbre, reportes y fallo de ingesta | V-E0-9, V-E8-2 |
| H26 | Registro obligatorio completo, direcciones/unidades/fronteras; perfil DRAFT sin aceptación | V-E0-3/6, V-E5-20, V-E9-7 |
| H27 | Dominios y protocolo por experimento; abstención cuando información no permite inferir | V-E2-7/10, V-E4-13, V-E5-1/16 |
| H28 | BIC por likelihood/parametrización y supersesión explícita por requisito | V-E4-9, V-E6-6 |
| H29 | Digest científico distinto de autenticidad; elegibilidad recomputada desde evidencia confiable | V-E8-1/3/4 |
| H30 | Estado real del código entregado y skips; manifiesto no autoaprueba suites | V-E0-1/10 |

## ID y migración de pruebas

Se conservan los92 IDs de v1.3 y se agregan8: V-E0-9/10, V-E3-8, V-E5-21/22, V-E6-6, V-E8-4 y V-E9-7. Cada test lleva `specification_version=1.4`; coincidencia de nombre no equivale a mismo estimando ni a evidencia válida.

Todos los100 IDs tienen registro único y al menos un gate. V-E3-4 se comparte como referencia entre G0/G3; V-E3-8 pertenece a G5 porque el generador ampliado es previo a validación cercana, no al QC común básico. Un skip obligatorio produce INCOMPLETE, nunca PASSED.

La v1.4 fija las fórmulas verificadas y las reglas de abstención/aceptación. Las metas empíricas razonables de v1.3 se conservan como objetivos iniciales de experimentos con alcance y CI; no se aprobaron nuevos límites relajados. Requisitos físicamente imposibles se sustituyeron por contrapruebas de no identificabilidad conforme al ADR.

## Verificación de incorporación documental

`python docs/validate_plan_v1_4.py` comprueba IDs de plan/manifiesto, grafo sin ciclos, cobertura de hallazgos, enlaces locales y hashes históricos, y recalcula el kernel de Dirichlet y el tamaño binomial. Preserva contrapruebas de capa oculta y cola Rayleigh de la evidencia histórica. Produce `evidence/plan_revision_v1_4.json` con `DOCUMENT_CONSISTENCY_VERIFIED` cuando pasa.

Este resultado es de coherencia documental y controles analíticos seleccionados. No sustituye ninguno de los100 tests del producto, no aprueba parámetros de campo y no demuestra ausencia absoluta de errores.

## Siguiente alcance de implementación — registro histórico anterior a E2/E4/E5

E0/E1/E3 básicos tienen ejecución trazable; reproducción actual en [e1_e3_implementation.md](e1_e3_implementation.md). Continuar con QC común E2/G2 según el grafo. Completar el registro operativo de métricas y requisitos antes de algoritmos de decisión. Los datos reales y las decisiones OQ se resuelven antes de habilitar perfiles operativos, no antes de poder desarrollar herramientas diagnósticas.
