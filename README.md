# GeoQC-Field

Proyecto de control de calidad y suficiencia de adquisición sísmica MASW/TRS.

**Para entender, modificar y ampliar el sistema:**
[Manual de arquitectura y mantenimiento](docs/manual_mantenimiento.md): mapa del código,
recorrido de datos, operación local, criterios, pruebas, recuperación y evolución.

**Aplicación local — plan inicial:** [APP-LOCAL-0.1](app.md) ·
[decisiones de alcance](docs/adr/0004-local-masw-scope.md) ·
[auditoría de arquitectura](docs/auditoria_arquitectura_app_2026_10_14.md).
Primer hito previsto: MASW, SEG-Y con sidecar, dosier y revisión humana diagnóstica.
La especificación está definida y el [adaptador científico MASW](docs/app_local_adapter.md) está implementado;
el backend y los workers locales tienen pruebas PostgreSQL. El [cliente Web local](docs/app_local_web.md)
permite cargar registros, consultar dosieres y registrar revisiones con control de conflictos;
el cierre del hito integrado sigue pendiente.

**Dosier MASW Oysand:** [HTML](evidence/masw_quality/dossier.html) · [PDF](evidence/masw_quality/dossier.pdf) ·
[método y resultados](docs/masw_quality_dossier.md). Cuatro registros, 96 trazas,
bandas diagnósticas y comparación entre offsets; evidencia pendiente explícita.

**Nuevo dosier por traza:** [HTML](evidence/trace_quality/dossier.html) · [PDF](evidence/trace_quality/dossier.pdf) ·
[criterios, resultados y reproducción](docs/trace_quality_dossier.md). Verde/buena, amarillo/regular y rojo/mala;
calificación del tendido por porcentaje de buenas: ≥90 %, ≥75 % y <90 %, o <75 %.
La [revisión de SNR, ruido LF/red y decisión con evidencia](docs/revision_qc_trs_ruido.md) incorpora
SNR condicional de campo, estado no evaluable y pruebas de filtrado que conservan los originales.

**Plan vigente de trabajo:** [SDD v1.4 + MASW-R1](SDD_QC_Geofisico_MASW_TRS_v1_4.md). La ejecución histórica registra **G0–G5 PASSED** para sus protocolos sintéticos: contratos, ingesta SEG-Y/SEG-2 con sidecars, referencias, QC común, TRS y MASW; incluye cobertura de ingesta ≥90 %, cero skips obligatorios y controles de tipos/estilo. La [revisión del 12 de octubre de 2026](docs/masw_review_2026_10_12.md) incorpora ocho obligaciones adicionales, inicialmente NOT_RUN. La [primera implementación MASW-R1](docs/masw_r1_implementation.md) agrega evidencia modal verificable, unión con covarianza y evaluación del suplemento. El runner distingue gates base/ampliados y conserva cada ejecución en `evidence/masw_r1/runs`. El cierre ampliado de G5, la calibración de campo y los gates posteriores siguen pendientes.

- [Backend MASW local: ejecución, pruebas PostgreSQL y pendientes](docs/app_local_backend.md).
- [Exportaciones CSV/HTML/PDF: formatos, worker y recuperación](docs/app_local_exports.md).
- [Detalle MASW: cursores, frecuencias, unidades y lectura condicional](docs/app_local_detail.md).
- [Cliente Web local: ejecución, revisión concurrente y pruebas en Chromium](docs/app_local_web.md).
- [TRS local: selección de técnica, ejemplo KM y primeros arribos](docs/app_local_trs.md).
- [Auditoría histórica v1.3, H01–H30](docs/findings.md).
- [Registro de cambios y pendientes v1.4](docs/revision_v1_4.md).
- [Manifiesto de 100 pruebas y dependencias](docs/validation_manifest_v1_4.json).
- [Decisiones del proyecto aún abiertas](docs/open_questions.md).
- [Evidencia numérica de la auditoría v1.3](evidence/audit_plan_v1_3.json).
- [Evidencia ejecutada de G0](evidence/e0/G0.json).
- [Instalación, CLI y alcance de E0](docs/e0_implementation.md).
- [Requisitos y contratos de E0](docs/requirements_v1_4.md).
- [Ejecución histórica G0/G1/G3](evidence/e1_e3/execution.json).
- [Formatos, contratos y límites de E1/E3](docs/e1_e3_implementation.md).
- [Comparación independiente de dispersión](evidence/e1_e3/dispersion_comparison.svg).
- [Ejemplo sintético de ingesta](examples/e1/README.md).
- [Ejecución histórica G0/G1/G2/G3](evidence/e2/execution.json).
- [QC común: uso, contratos y límites](docs/e2_implementation.md).
- [Protocolo de validación E2](docs/requirements_e2.md).
- [Ejemplo ejecutable de QC común](examples/e2/README.md).
- [Ejecución histórica G0–G4](evidence/e4/execution.json).
- [TRS: uso, contratos y límites](docs/e4_implementation.md).
- [Protocolo de validación E4](docs/requirements_e4.md).
- [Ejemplo TRS causal con calibración sintética](examples/e4/README.md).
- [Figura de intervalos, arribos y comparación independiente](evidence/e4/validation.svg).
- [Ejecución G0–G5 del alcance base, anterior a MASW-R1](evidence/e5/execution.json).
- [Obligaciones adicionales MASW-R1 y trazabilidad](docs/validation_masw_r1.json).
- [MASW: uso, calibraciones y límites](docs/e5_implementation.md).
- [Protocolo de validación E5](docs/requirements_e5.md).
- [Ejemplo MASW SEG-Y ejecutable](examples/e5/README.md).
- [Motor diagnóstico E6: requisitos, bloqueos y supersesión](docs/e6_implementation.md).
- [Ejemplo de decisión desde QC común](examples/e6/README.md).
- [Primeras pruebas con datos públicos de campo: Oysand y Chevremont](examples/field/README.md).
- [Coherencia, precisión holdout y sesgo cercano](evidence/e5/validation.svg).

La [v1.3 original](SDD_QC_Geofisico_MASW_TRS.md) permanece intacta para reproducir la auditoría. La propuesta anterior es un documento de transición; la v1.4 contiene las reglas consolidadas.

Para verificar integridad de documentos, IDs, dependencias y contrapruebas de la revisión:

```powershell
python docs/validate_plan_v1_4.py
```

Esto verifica la especificación y escribe `evidence/plan_revision_v1_4.json`; no ejecuta los algoritmos del producto ni aprueba G0–G10. El manifiesto conserva el diseño inicial; los estados de ejecución se registran en la evidencia separada.

Para repetir las verificaciones de implementación de E0, con el entorno instalado:

```powershell
.\.venv\Scripts\python.exe tools/check_e0.py
.\.venv\Scripts\python.exe -m geoqc validate-config --config configs/vs30_sitio.yaml
```

Para verificar conjuntamente la implementación actual:

```powershell
.\.venv\Scripts\python.exe tools/check_masw.py
.\.venv\Scripts\python.exe -m geoqc inspect examples/e1/synthetic_ieee.sgy
.\.venv\Scripts\python.exe -m geoqc qc examples/e2/common_qc.sgy --config configs/vs30_sitio.yaml --protocol examples/e2/protocol.json
.\.venv\Scripts\python.exe -m geoqc trs examples/e4/causal_trs.sgy --protocol examples/e4/protocol.json --calibration examples/e4/calibration.json
.\.venv\Scripts\python.exe -m geoqc masw examples/e5/masw_plane.sgy --protocol examples/e5/protocol.json
```

Los perfiles son DRAFT y la CLI es diagnóstica. E5 revalida G0–G4 y evalúa las 23 obligaciones MASW más V-E3-8, con holdout de precisión, 6 millones de realizaciones de la nula y 300 escenarios. El Green independiente cubre interferencia P/S/R en semiespacio homogéneo con fuente finita; campo cercano estratificado y ruido real de arreglo siguen UNCALIBRATED. Las bandas observadas no equivalen a bandas validadas ni suficiencia Vs30. La inversión TRS es paramétrica horizontal y la resolución está condicionada al modelo. **E6 tiene una primera implementación diagnóstica** con CLI, requisitos, bloqueos, supersesión y anotación humana; **G6 sigue INCOMPLETE**. Falta completar registro operativo e integración E6/E8 de MASW-R1, además de G5 ampliado; la validación de campo corresponde a G9.
