# Requisitos para E0, especificación 1.4

Estos IDs se definen aquí. Se distinguen de los IDs `V-*`, que identifican obligaciones de validación. El antiguo `REQ-SYN-2` de la prueba v1.3 no acredita estos requisitos.

| Requisito | Contrato y datos necesarios | Validación |
|---|---|---|
| REQ-E0-PACKAGE | Paquete instalable, importación fuera del proyecto, sin UI obligatoria; CLI de diagnóstico. Python y dependencias declaradas. | V-E0-1 |
| REQ-E0-REPRO | PCG64 con semilla entera explícita; hashes de entradas y versiones. El orden de claves no modifica el hash; forma/tipo de arrays sí. | V-E0-2 |
| REQ-E0-CONFIG | Rechazar claves desconocidas/duplicadas, parámetros de umbral ausentes, direcciones incoherentes y fronteras indefinidas. Los perfiles DRAFT no permiten aceptación. | V-E0-3 |
| REQ-E0-OFFSET | Separar distancia media y mínima al receptor; conservar contrapruebas 4.8/9.6 m como aritmética histórica, sin criterio operativo. | V-E0-4 |
| REQ-E0-PHYSICS | Compartir λ=c/f entre escenarios y resúmenes de puntos observados. Prior no convierte una máscara inválida en evidencia. Entradas SI positivas finitas. | V-E0-5 |
| REQ-E0-PLANNING | Perfiles Vs30/15 m con banda declarada, hipótesis explícitas, profundidad nominal y efectos conjuntos de N/dx/offset. Resultado conservador NOT_DEMONSTRATED. | V-E0-6 |
| REQ-E0-GEOMETRY | Coordenadas 3D, incertidumbre, CRS y procedencia; L_ap=(N−1)dx y L_eff=Ndx solo para arreglo regular completo horizontal alineado con x. Huecos/topografía/y impiden ese kernel. | V-E0-7 |
| REQ-E0-RESPONSE | Respuesta compleja normalizada de geófono con convención Fourier del SDD. f_n y k_g f_n no se presentan como cortes físicos. Máscara y motivo conservan banda sub-f_n desconocida. | V-E0-8 |
| REQ-E0-DATA | Nueve contratos versionados, arrays copiados e inmutables, tiempos por canal, unidades, máscaras, incertidumbre y procedencia; JSON finito con null para muestras corruptas. | V-E0-9 |
| REQ-E0-EVIDENCE | Registro completo de 100 IDs, grafo válido; faltantes/skips/fallos no cierran gates. G0 requiere pruebas más ruff/formato/mypy strict. Evidencia de implementación separada de auditoría/calibración. | V-E0-10 |
| REQ-E0-RAYLEIGH | Raíz física de semiespacio isótropo en −1<ν≤0.5, incluyendo límite incompresible. Forma cerrada ν=0.25, solver polinómico alternativo, residual equivalente y pruebas de propiedades. | V-E3-4 |

Los contratos de ArrivalPick, DispersionCurve y Coverage son estructuras de intercambio iniciales. E0 no implementa picking, análisis modal, propagación de covarianza ni cobertura de rayos. Las referencias opcionales desconocidas permanecen null; no se fabrican calibraciones. QCReport en E0 admite diagnóstico y decisión humana PENDING; el motor de requisitos y decisiones se implementa en E6.

La descomposición funcional posterior se fija por dominio y datos requeridos. Esta tabla corresponde a la planificación al terminar E0; E1/E3 se concretaron después en [requirements_e1_e3.md](requirements_e1_e3.md) y su ejecución vigente está en [execution.json](../evidence/e1_e3/execution.json). Los detalles de los estimadores restantes se especifican antes de implementar cada etapa:

| Dominio | Contratos y datos necesarios | Obligaciones pendientes |
|---|---|---|
| IO | Formato, trazas, headers originales, escalares/unidades, geometría y trigger. Fallo tipado sin Shot inválido. | V-E1-1..6 |
| QC | Ventanas, canales activos, ruido, sincronía, réplicas independientes, instrumento/ADC/ganancia y respuestas. | V-E2-1..10 |
| SYN | Verdad analítica o independiente, dominio/model mismatch, semillas, topografía y fallos combinados. | V-E3-1..3,5..8 |
| TRS | Onset/incertidumbre, geometría, errores compartidos, reciprocidad, ROI y modelo de rayos identificable. | V-E4-1..21 |
| MASW | Ventanas, f/c/mode_identity, kernel real, banda por disparo/dirección, incertidumbre/modalidad y objetivo. | V-E5-1..22, V-E5-17b |
| DEC | Requisitos aplicables, obligatorios/críticos, calibraciones vigentes, agregación, conflictos y supersesión. | V-E6-1..6 |
| UI | Estado diagnóstico, máscaras, resultados y motivos sin atribución causal injustificada. | V-E7-1..3 |
| RPT | Hashes/versions, confianza, salvedades y decisión humana con alcance. Exportar no equivale a aceptar. | V-E8-1..4 |
| CAL/NFR | Corpus independiente, holdout por sitio, intervalos/potencia, dominio de calibración y rendimiento/offline. | V-E9-1..7, V-E10-1..2 |

La lista exacta de obligaciones y dependencias sigue en [el manifiesto](validation_manifest_v1_4.json). La tabla posterior agrupa áreas; no afirma que ya estén implementadas o probadas.
