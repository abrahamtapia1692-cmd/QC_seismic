# Requisitos definidos para E1 y E3

Estos requisitos concretan los dominios IO/SYN del SDD v1.4. Los identificadores de prueba V conservan el significado del plan. Ningún requisito aquí habilita aceptación de campo.

| Requisito | Contrato/datos y resultado exigido | Validación |
|---|---|---|
| REQ-IO-SEGY | Rev0 IBM32 y rev1 IBM32/IEEE32; endian declarado por contexto binario inequívoco. Coordenadas/tiempo con escalares y cuantización; amplitudes contra valores conocidos y lector ObsPy externo. | V-E1-1 |
| REQ-IO-FAILURE | Archivos vacíos, truncados, variantes no habilitadas y metadatos inconsistentes producen IngestError/IngestFailure accionable; no corrección silenciosa. SEG-2 rev1 códigos 1/2/4/5 y sidecar. | V-E1-2 |
| REQ-IO-CONTRACT | Matriz rectangular y máscara conservan canales físicos, t0/dt por canal y muestras corruptas/canales cortos. Property testing de 1–96 canales, 16–32768 muestras y dt representable; no precisión ficticia float64→float32. | V-E1-3 |
| REQ-IO-GEOMETRY | CSV SI unido por receptor físico, posiciones 3D, soporte explícito y espaciamiento nominal. Irregularidad, topografía, y y huecos no prueban error causal. | V-E1-4 |
| REQ-IO-DIRECTION | Fuente interna: mantener índices, lados, distancias, azimut y coincidencias; receptor sobre eje y tiene categoría transversal explícita. | V-E1-5 |
| REQ-IO-REFERENCE | Referencia fiable declarada, CRS/correspondencia iguales e incertidumbre por receptor. Comparación geométrica conserva MISSING/autoridad desconocida/solapamiento; 0.1 m sigue siendo candidato diagnóstico. | V-E1-6 |
| REQ-SYN-SIGNAL | Ricker bilateral para espectro/Parseval; pulso causal con onset analítico y muestreado separados, respuesta instrumental causal registrada. Ruido blanco/coloreado/coherente/tráfico/hum/bursts con semilla y SNR de ventana explícita. | V-E3-1 |
| REQ-SYN-TRS | Dos capas horizontales con rama de cabeza accesible; buzamiento solo dentro de su dominio. Gradiente g≥0 y límite estable g=0; contraste FMM independiente con refinamiento y expansión de dominio. | V-E3-2 |
| REQ-SYN-RECIPROCITY | Simetría analítica fuente/receptor en medios estáticos isótropos modelados; no exigir identidad de discretizaciones diferentes. | V-E3-3 |
| REQ-SYN-RAYLEIGH | Referencia común de E0; se vuelve a ejecutar en el entorno de esta etapa. | V-E3-4 |
| REQ-SYN-DISPERSION | Dunkin/disba/CPS vs FEM vertical propio, tres perfiles incluido Vs invertido, banda 4–40 Hz, fundamental. Comparar todos los puntos sin ocultar cutoffs, ≤0.5 %, con malla y dominio convergidos. Síntesis modal asintótica: IFFT real y ventanas extendidas; rechazar presupuesto/convergencia insuficientes. | V-E3-5 |
| REQ-SYN-LIMITS | Alta/baja f solo en modelos con las asíntotas apropiadas; aproximación ≤1 % y secuencia de frecuencias hacia el límite. | V-E3-6 |
| REQ-SYN-FAULTS | Doce inyectores y combinaciones con parámetros/unidades/semilla/procedencia; severidad contrastada por medidas distintas. Acople es cambio aparente de amplitud y dt no garantiza detectabilidad. | V-E3-7 |

G1 exige cobertura de líneas de `geoqc.io` ≥90 %, además de V-E1-1..6 y G0 vigente. G3 exige V-E3-1..7 y G0; V-E3-8 pertenece a G5 y **permanece pendiente**. La validación aquí es del dominio sintético declarado, no del campo cercano, de perfiles reales ni de una inversión final. Los estados se derivan en [execution.json](../evidence/e1_e3/execution.json).
