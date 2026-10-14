# Implementación inicial MASW-R1: contratos, evidencia modal y covarianza

Fecha: 2026-10-12. Alcance: primera entrega RM-08/RM-02/RM-03; diagnóstico.

`masw_diagnostics` emite schema `1.4-r1`, revisión MASW-R1 y hash fijado del
suplemento. Sigue leyendo `MASWProtocol` 1.4: `mode_identity` de entrada es una
declaración, conservada como `declared_mode_identity`, no una confirmación efectiva.
No se cambian los umbrales ni la física del transformador.

## Evidencia modal

La API admite `modal_evidence` y `modal_approvals` como dependencias separadas.
`ModalEvidence` contiene hashes del Shot científico, protocolo y estimador,
dominio, dirección, frecuencias, hash de receptores activos por punto, etiqueta
M0/M1/…, autoridad, método, alternativas, limitaciones y origen humano/calibrado.
`ModalApproval` procede del registro de confianza de la aplicación y fija hash
de contenido, autoridad y estado activo. No se carga automáticamente desde el
reporte, protocolo ni archivo señalado por el usuario. Un hash editable junto
al contenido no autentica una autoridad.

Se verifica contenido, revisión, alcance, vigencia mediante aprobación activa y
soporte por punto. Ref inexistente, revocada, alterada o incompatible => UNKNOWN
si se solicitaba CONFIRMED. Se preservan motivos, etiqueta por punto, origen de
confirmación y hash de evidencia verificada. La confirmación humana se distingue
de un método calibrado; ni una ni otro habilitan aceptación de campo en esta entrega.

La CLI no expone un flag para autootorgarse confianza y conserva diagnóstico
exportable. Antes de integrar un registro externo deberán fijarse su autoridad,
procedimiento de actualización/revocación y calibración compatible (OQ-16).
No hay clasificador modal nuevo ni tasas de falsa confirmación medidas: RM-02
continúa INCOMPLETE hasta la cohorte independiente `population`.

## Unión con covarianza

`CurveR1` separa etiqueta modal por punto del estado de confianza, identidad de
observación y soporte. `migrate_curve(DispersionCurve)` conserva información
histórica; no infiere un modo físico ni soporte suficiente desde CONFIRMED/band_refs.
El resultado migrado queda UNKNOWN cuando antes se declaraba CONFIRMED. Identidades
legacy se derivan del contenido: coincidencia de curvas copiadas se conserva,
pero procedencias distintas no se deduplican por parecido numérico.

`merge_curves` admite curvas legacy/R1 y una `JointCovariance` explícita con orden
de point_ids, unidad (m/s)² y procedencia. No resuelve referencias textuales en disco.
Las referencias originales y las curvas completas permanecen en la salida.
Valida dimensiones, finitud, simetría, PSD, identidades y sigmas; matriz singular
es admisible. No añade jitter ni reemplaza covarianza desconocida por independencia.

Compara diferencias usando todos los términos cruzados. `compatibility_sigma`
debe proporcionarse para comparación puntual no determinista: ya no hay default3.
Sin criterio/covarianza/modo/soporte, `compatible_overlap=null` y estado UNKNOWN.
Modo o soporte distintos producen incompatibilidad explícita. Una etiqueta modal
es una hipótesis declarada para comparar; esta función no autentica su origen.

Con varios puntos devuelve C_delta=A C Aᵀ, rango, discrepancia en espacio nulo y
Mahalanobis al cuadrado cuando es definido. No asigna p-value ni aceptación conjunta
sin calibración de la selección/multiplicidad. Duplicados de la misma identidad
se conservan como contribuciones, pero no se cuentan dos veces ni estrechan sigmas.
La unión no promedia ni interpola observaciones.

## Evaluación y evidencia

El [protocolo](requirements_masw_r1.md) se registró antes de ejecutar las pruebas;
los [criterios](masw_r1_criteria.json) descomponen cada RM. Dos regresiones iniciales
fallaron con el código anterior, registradas en
[red_initial.json](../evidence/masw_r1/red_initial.json); la segunda etapa de contratos
pendientes está en [red_contracts.json](../evidence/masw_r1/red_contracts.json).
Son registros del ciclo TDD, no aprobación de obligaciones científicas.

`tools/check_masw.py` ahora distingue `base_gates` del cierre ampliado `gates`.
Cada criterio RM exige casos realmente ejecutados y fases setup/call/teardown
exitosas; omisión, skip, error, duplicados o hashes/revisión distintos no aprueban.
Los metadatos se vinculan al snapshot del runner, suplemento y protocolo/criterios.
Solo se consume el resultado del proceso de prueba lanzado por el runner; este
evaluador no autentica archivos de terceros. Todos los RM son obligatorios para
G5 ampliado, que bloquea sus descendientes mientras alguno esté pendiente.

Las ejecuciones nuevas se escriben en subdirectorios únicos de
`evidence/masw_r1/runs`; `evidence/e5` conserva la evidencia anterior.
El manifiesto complementario preserva sus estados iniciales de diseño; el estado
actual procede de la ejecución. Un criterio implementado no sustituye los faltantes:
RM-08 todavía requiere `decision_integration` al desarrollar E6/E8. Ningún resultado
de esta entrega equivale a validación G9.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_masw_r1.py -q
.\.venv\Scripts\python.exe tools/check_masw.py
```

El runner devuelve código1 si G5 ampliado está INCOMPLETE aunque pasen los tests
ejecutados; consultar resultados RM y gates base para distinguirlo de un fallo.
No se degrada la política para convertir ese código en aprobación.
