# Calificación TRS con parámetros estimados y cobertura explícita

Fecha: 2026-10-20. Política optativa `TRS_SAMPLE_SCREENING_V1_DRAFT`.

Esta política cierra el recorrido de calificación diagnóstica por muestras para
el ejemplo KM: devuelve categorías, motivos, soporte y estimaciones por traza y
su agregación por tendido. Conserva simultáneamente la evaluación estricta.
Su implementación probada no equivale a calibración de aceptación de campo.

## Qué aportan las referencias

Se revisaron las notas de [cabeceras](../examples/km_app/header_research.md),
[apilamiento](../examples/km_app/stack_analysis.md) y
[correcciones de ruido](revision_qc_trs_ruido.md), junto con estas fuentes primarias:

| Fuente consultada | Aporte y límite |
|---|---|
| [Manual del fabricante DAQLink 4](https://geodevice.uz/upload/iblock/86a/DAQLink-4-Manual.pdf), §§4.2.1, 4.3.6, 5.4.7–5.4.14 | La ganancia y calibración afectan el rango; la exportación puede incorporar opciones de procesamiento. Incluye estadísticas de ruido y monitor entre disparos. Conocer el modelo no identifica la configuración usada. |
| [SEG-2](https://seg.org/wp-content/uploads/2025/11/seg_2.pdf), apéndice C | Define metadatos de escala y apilamiento. STACK positivo forma parte de la conversión estándar; STACK=0 del KM no permite reconstruir esa escala. |
| [ObsPy: correlación normalizada por solape](https://docs.obspy.org/packages/autogen/obspy.signal.cross_correlation.correlate_template.html) | Referencia para medir similitud con normalización local; no proporciona nuestros umbrales ni demuestra acople, polaridad o identidad de fase. |
| [SciPy: periodograma](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html) | PSD con frecuencia, ventana y escala declaradas. Una línea espectral no identifica su causa. |
| [EarthScope/MUSTANG](https://service.iris.edu/mustang/) y [guía de métricas](https://ds.iris.edu/ds/nodes/dmc/tutorials/getting-started-with-mustang/) | Distingue estadísticas de señal, continuidad, anomalías y metadatos. Sus métricas de registros largos no se transfieren como umbrales a estos tiros cortos. |

Los cortes de cobertura, contraste, persistencia y mesetas que siguen son
decisiones locales de esta política DRAFT. No se atribuyen al fabricante, SEG,
ObsPy o EarthScope. Se fijan explícitamente; no se optimizan para volver verde el KM.

## Separación de resultados

1. `quality`, `data_assessment` y `trace_qc_assessment`: evaluación estricta
   anterior, con sus faltantes de independencia, rails y comparabilidad.
2. `operational_quality` por traza y `operational_assessment` por registro/conjunto:
   calificación **condicional del registro bajo el escenario declarado**.
3. Suficiencia `NOT_DEMONSTRATED` y elegibilidad `false`, también cuando la
   categoría diagnóstica resulte buena.

Una buena diagnóstica significa que las comprobaciones requeridas no muestran
alertas bajo ese escenario. No significa SNR del primer arribo validada,
ausencia demostrada de clipping físico, sensor certificado ni subsuelo resuelto.

## Mediciones y estimaciones

### Integridad y morfología

Se usan máscaras y estadísticas nativas. Canal muerto/constante y fallas
demostradas del QC estricto prevalecen. Los huecos generan revisión; no se
rellenan. Una ventana incompleta no cuenta como una comprobación apoyada.

La morfología busca corridas de al menos tres muestras exactamente iguales en
los extremos **observados** de la ventana de análisis. Devuelve duración de la
corrida más larga y fracción de muestras en mesetas candidatas. Un máximo
aislado no dispara la alerta. Una meseta genera revisión por posible saturación,
cuantización o procesamiento; no se convierte en rail ADC ni en clipping confirmado.
No detectar una meseta tampoco prueba que no hubo saturación.

### Contraste señal/referencia sin escala absoluta

Se requieren ventanas disjuntas explícitas. No se busca retrospectivamente la
ventana más silenciosa ni se selecciona solo el bloque favorable. Se conservan
las ventanas del KM: señal `[0,0.5)` s y referencia posterior `[1.5,2)` s.

Se divide toda la referencia en cuatro bloques con al menos 16 muestras cada
uno. Se elimina la media de cada bloque y de la señal. Con `Ps` como potencia
AC de señal y `Pn,k` como potencia de cada bloque, se informa:

`C_inferior = 10 log10(Ps / max(Pn,k) - 1)`

`C_superior = 10 log10(Ps / min(Pn,k) - 1)`

Un cociente neto no positivo se conserva como censurado/null, nunca como cero dB
o infinito. Un bloque de potencia cero impide usar este contraste para declarar
buena. Una normalización común a ambas ventanas evita desbordamientos y conserva
invariancia a una ganancia fija común. No corrige AGC o ganancias variables.

El intervalo mide **sensibilidad a la variación de la referencia**, no confianza
estadística, ni el error por coda o ruido no transferible. La razón máximo/mínimo
de potencias debe ser ≤4 para declarar estable la referencia dentro de sí misma.
Todo el intervalo debe alcanzar 12 dB para el dominio favorable. Contraste bajo,
intermedio, no resuelto o referencia variable produce revisión. El corte 6 dB
distingue el motivo de contraste bajo; con ruido no verificado no se convierte
por sí solo en una falla física demostrada.

La independencia señal/ruido no se infiere al pasar ese control. El campo
`noise_independence_verified` permanece false.

### Similitud relativa estimada

Se calcula la correlación normalizada nativa con el vecindario, reloj, ventana
y desfase del protocolo. La copia computacional que permite medirla no modifica
`comparable_channels` del protocolo original ni el diagnóstico estricto.

Para usarla como criterio debe existir una mayoría coherente de al menos tres
vecinos, excluyendo el canal examinado, según el algoritmo de consenso existente.
Sin consenso o con pocos vecinos, se conserva la medida disponible pero no se
declara falla de adquisición. Este dominio queda sin cobertura. Una diferencia
de forma frente a vecinos coherentes genera revisión en el escenario estimado;
no certifica avería o mal acople. Un máximo en el límite de desfase requiere revisión.

### Persistencia de líneas candidatas

Cada candidato del diagnóstico nativo se contrasta en todos los bloques fijos
de la referencia usando PSD Hann. Se exigen tres ciclos y soporte espectral de
fondo por bloque. Para generar la alerta operativa debe superar 10 dB de
prominencia en al menos 75 % de los bloques, con soporte en todos ellos.
Un candidato aislado no degrada automáticamente la calificación diagnóstica.
Las salidas informan prominencia por bloque, fracción y causa desconocida.
No se activa notch ni se cambia una muestra original.

## Cobertura y categoría

Los cuatro dominios son integridad, morfología, contraste y similitud. La
cobertura es la fracción de dominios con soporte; no es probabilidad de acierto.
Por defecto se exige ≥75 %, y obligatoriamente soporte de integridad, morfología
y contraste, para declarar **buena diagnóstica**. Se puede exigir 100 % en el JSON.

Orden de decisión:

1. Una falla demostrada del QC estricto da MALA.
2. Una alerta observada/estimada apoyada da REGULAR y conserva sus motivos.
3. Sin alertas, con cobertura y dominios obligatorios suficientes: BUENA condicional.
4. Sin alertas pero sin ese soporte: NO_EVALUABLE.

Los metadatos instrumentales ausentes permanecen visibles en `missing_metadata`;
su ausencia por sí sola no bloquea este resultado condicional. No se inventa
ganancia, escala, rails, cantidad de stacks o latencia del trigger.

El tendido conserva la regla solicitada: ≥90 % de buenas → BUENA; ≥75 % y <90 %
→ REGULAR; <75 % → MALA. Todas las trazas permanecen en el denominador. Las no
evaluables producen un intervalo de porcentaje posible y abstención cuando sus
extremos cambian de categoría. El conjunto suma trazas de todos sus registros.
Una MALA por poca proporción de buenas **no afirma que todos los sensores fallaron**;
puede estar motivada por muchas trazas en revisión. Se muestran los conteos.

## Activación, reproducción y límites

En la Web cargar `examples/km_app/demo_trs_f1/trace_qc_operational.json` en el
campo QC. La política es explícita y optativa; `trace_qc.json` conserva la anterior.
La Web, el HTML autónomo y el PDF muestran ambas evaluaciones y las estimaciones.
Una actualización requiere otro run; no se reescriben dosieres ni revisiones humanas.

```powershell
.\.venv\Scripts\python.exe -m pytest tools/tests/test_operational_quality.py tools/tests/test_app_trace_qc.py -q
```

Los controles incluyen canal muerto, mesetas, huecos, ruido variable, referencia
ausente/cero, bordes sin vecinos, ganancia común, límites porcentuales y 100
trazas de ruido con semillas diferentes de las usadas para construir las señales.
También se comprueba persistencia en todos los bloques frente a una línea de
un solo bloque. Son verificaciones de implementación y escenarios, no una tasa
de error calibrada para campo ni una validación geológica independiente.

### Resultado ejecutado sobre KM F1

Dosier publicado `6f2fd889-6ce5-4394-8e78-7eab9fcf7f1a`: 2 buenas diagnósticas
(ch07/ch11), 22 en revisión, 0 malas por falla demostrada y 0 no evaluables en
la capa operativa; cobertura 75 %. El tendido da MALA por 8.33 % de buenas, de
acuerdo con la regla porcentual. La capa estricta conserva NO_EVALUABLE y sus
faltantes. No se declara avería de los 22 canales en revisión.

La [sensibilidad archivada](../evidence/app_local/km_trs_operational_sensitivity/sensitivity.csv)
varía contraste bueno a 10/15 dB, cobertura al 100 %, bloques a 3/8 y razón de
potencias a 2/8. Todas las variantes conservan MALA para el tendido; los conteos
de buenas cambian entre 0 y 6. Este resultado evalúa sensibilidad a esas
decisiones, no robustez frente a todos los modelos físicos posibles.

Se ejecutaron 91 regresiones satisfactorias de QC, ruido, similitud, aplicación,
worker, exportaciones y ejemplos, más la verificación final de presentación.
Ruff pasó y mypy verificó 87 archivos. No se acreditan gates de campo adicionales.

Reproducción sin base de datos ni credenciales, eligiendo una salida nueva:

```powershell
.\.venv\Scripts\python.exe -m tools.report_trs_operational --waveform examples/km_app/demo_trs_f1/km40_f1_trs_exploratory.sgy --protocol examples/km_app/demo_trs_f1/protocol.json --trace-qc examples/km_app/demo_trs_f1/trace_qc_operational.json --output .local/km_operational_reproduction --sensitivity
```

Esta utilidad conserva parámetros y hashes por variante. No cambia el perfil
base a partir del resultado de la sensibilidad ni publica resultados en SQL.

Repetibilidad necesita grupos reales de impactos; reciprocidad necesita pares
físicos de fuente/receptor. Un transitorio de ruido coherente puede imitar señal,
y una referencia posterior puede contener coda estable: estos límites no se
eliminan con un indicador de cobertura. Para decisiones de aceptación se necesita
validación independiente, además de las comprobaciones de esta política.
