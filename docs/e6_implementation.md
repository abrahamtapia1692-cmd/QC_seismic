# E6 — primera implementación diagnóstica

Fecha: 2026-10-13. Continúa el siguiente paso registrado en el README.

`geoqc.decision` agrega requisitos explícitos por registro, técnica, componente,
unidad y soporte. Deriva calidad, completitud, bloqueos y motivos. Las métricas
opcionales no cubren requisitos faltantes ni diluyen FAIL/WARN. NA requiere
fundamento en el perfil. Se conservan todos los registros, incluidos los no usados.

`DecisionInput` requiere un perfil de requisitos ya descompuesto; no se genera un
registro operativo completo a partir de las métricas disponibles. El ejemplo E2
solo declara controles comunes y conserva los requisitos de técnica/sitio pendientes.

La selección incluye dependencias transitivas: un resultado PASS derivado de una
entrada con FAIL crítico sigue bloqueado. La salida enumera los derivados afectados.
Una supersesión requiere original y sustituto, geometría/componente/configuración/
soporte iguales, responsable, motivo y todos los controles bloqueantes resueltos PASS.
No reescribe dependencias de productos calculados sobre el original; deben recalcularse.
No se admite equivalencia aproximada de geometría/configuración sin contrato nuevo.

El adaptador `record_from_common_qc(shot, report)` conserva métricas, soporte de
traza y faltantes upstream. Desambigua IDs repetidos mediante hash de soporte.
Verifica hashes originales compartidos; no autentica reportes editados ni vuelve
a calcular las métricas físicas. Su uso previsto es dentro de la aplicación tras
`common_qc`. La CLI acepta un contrato diagnóstico explícito, sin flags de confianza.

El esquema rechaza elegibilidad inyectada. Referencias de calibración no verificadas
dejan requisitos empíricos UNCALIBRATED. MASW legacy o revisión/hash incompatibles
requieren migración; faltantes de los cálculos previos mantienen INCOMPLETE. Incluso
controles binarios completos quedan YELLOW: este release no habilita GREEN ni aceptación.
OUT_OF_SCOPE se muestra explícitamente y conserva cualquier bloqueo crítico en motivos.

`annotate` recalcula el resultado antes de asociar una decisión humana al digest,
alcance y fecha con zona horaria. ACCEPTED requiere responsable y salvedades; solo
es anotación humana, no validación científica ni autorización de release. No altera
WARN/FAIL. No se ha implementado todavía almacenamiento persistente de bitácora.

Acciones disponibles: predicción de stacks reutilizando la fórmula/supuestos E2,
y revisión cualitativa de muestreo espacial. No hay nuevos umbrales empíricos ni
dimensionamiento automático de aperturas/offsets. El digest incluye entrada completa,
historial, selección, resultados y código; no incluye la anotación temporal humana.
La canonización de orden de presentación de E8 queda pendiente.

## Reproducción

```powershell
.\.venv\Scripts\python.exe tools/create_decision_demo.py
.\.venv\Scripts\python.exe -m geoqc decision --input examples/e6/input.json
.\.venv\Scripts\python.exe tools/check_decision.py
```

El [protocolo](requirements_e6.md) se escribió antes del código. El primer fallo
por módulo ausente está en [red_initial.txt](../evidence/e6/red_initial.txt).
Cada verificación nueva guarda pruebas reales, fases, hashes, versiones, controles
de estilo/tipos y cobertura en `evidence/e6/runs/<ejecución>/execution.json`.
El runner exige cobertura de decisión ≥85 % y cero casos omitidos de los seis IDs.

Pasar los casos implementados no acredita todo V-E6-1..6 ni cierra G6. El runner
general conserva G6 y descendientes INCOMPLETE mientras falten registro operativo,
integración E6/E8 y G5 ampliado MASW-R1. RM-08 `decision_integration` no se marca
cumplido por esta entrega: aún falta integrar curvas/modos y el modelo de confianza
de E8. También siguen pendientes calibración/alcance G9 y acciones completas del perfil.
