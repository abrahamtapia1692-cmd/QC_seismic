# E2 — implementación de QC común

Requisitos/protocolo numérico: [requirements_e2.md](requirements_e2.md).
Revalidación conjunta: `python tools/check_common.py`; artefactos en `evidence/e2`.
Esta ejecución conserva el historial E0/E1/E3 y registra nuevamente G0/G1/G3 junto
con G2. Ningún estado de diseño del manifiesto se reescribe como PASSED.

## Uso

```powershell
.\.venv\Scripts\python.exe tools/check_common.py
.\.venv\Scripts\python.exe tools/create_qc_demo.py
.\.venv\Scripts\python.exe -m geoqc qc examples/e2/common_qc.sgy --config configs/vs30_sitio.yaml --protocol examples/e2/protocol.json
```

`geoqc.qc.common_qc(shot, protocol, config)` devuelve un reporte con hashes de código,
configuración/protocolo y entradas, métricas de clip/SNR por receptor, estadísticas,
presupuesto temporal y espectros. `QCProtocol` es JSON SI validado y exige ventana
de análisis; ruido/señal, modelo/gain, rails y banda son explícitos y opcionales.
Ventanas ausentes/fuera del registro o datos enmascarados producen estado y motivo.
Los huecos nunca se comprimen para FFT/correlación.

## Semántica

- RMS AC, RMS total, DC, ceros, constantes y MAD se informan por ventana. Muerto
  significa exactamente cero observado. Un canal completamente excluido es MISSING.
- El residual de log RMS se calcula solo con amplitudes positivas y modelo externo
  de amplitud/gain. MAD cero usa límites de ratio declarados; no divide por cero.
  Una amplitud anómala no confirma acople ni separa gain y propagación.
- `adc_rails` expresa rails RAW; `rail_scale_to_data` declara conversión a waveform.
  La escala puede ser común o una tupla explícita por receptor con gain diferente.
  Saturación se mide sobre muestras válidas. Valores fuera de rails son INVALID.
  Stacks agregados abstienen: ausencia de saturación visible no certifica réplicas.
  Sin rails/escala la sospecha morfológica queda MISSING, nunca PASS.
- SNR neto resta potencia de ruido a potencia total tras quitar media por ventana;
  ambos estimandos y potencias se conservan. Ruido independiente y estacionariedad
  deben estar declarados con referencia externa. Cero/censura se expresa sin Inf/NaN.
  Welch usa parámetros compatibles; máscara PSD neta positiva conserva soporte.
  La cota DOF=2K no se interpreta como intervalo calibrado. No se presume que 100 ms
  puedan caracterizar ruido de 2 Hz.
- Interferencia de red requiere frecuencia del sitio y duración suficiente. Usa
  periodograma Hann sin padding, pico/mediana lateral. Resolución/medio bin explícitos;
  no se interpreta la interpolación espectral como precisión experimental.
- `compare_repeats` es API para fuente/componente comparable y banda declarada,
  potencia en banda ≥95%, duración ≥5 ciclos, lag dentro de búsqueda física. Máximos
  periódicos equivalentes, bordes y baja correlación abstienen. La interpolación
  parabólica solo tiene precisión validada en el experimento registrado sin ruido.
  `flagged=True` indica signo invertido respecto a referencia alineada; no causa.
  `repeatability` informa dispersión muestral de lags en ms; necesita al menos tres
  réplicas identificables y conserva la referencia compartida. No descarta réplicas
  ambiguas para emitir jitter válido.
- `stack_noise_independence` informa correlación muestral de réplicas de ruido.
  `required_stacks` exige ruido independiente, comparabilidad y stack MEAN. SUM puede
  convertirse externamente a promedio con unidades/escala conocidas; no se adivina.
- `instrument_response` conserva complejo nominal. Referencia declarada de calibración
  no se autentica ni cambia el modelo nominal a instrumento real. Datos bajo fn son
  posibles; no se emite límite físico de profundidad.

CLI `qc` devuelve código 0 si calculó el diagnóstico, aunque haya problemas detectados;
2 si ingesta/configuración/protocolo no son válidos. Es un diagnóstico para revisión:
`evidence_status=INCOMPLETE`, `eligible_for_acceptance=false`, `operator_decision=PENDING`.
Umbrales configurados se aplican como candidatos con dirección/unidad/fronteras
inclusivas; sin umbral la métrica numérica no adquiere clasificación automática.

G2 cubre exclusivamente los experimentos sintéticos registrados. Permanecen pendientes
datos/cadena instrumental reales, identidad de causas ambiguas, incertidumbre de lag
con ruido, calibración por sitio G9 y aceptación. El siguiente trabajo del grafo es
E4/G4 (TRS) o E5/G5 (MASW); E5 además requiere V-E3-8 de campo cercano independiente.
