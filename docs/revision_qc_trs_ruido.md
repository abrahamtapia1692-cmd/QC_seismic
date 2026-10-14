# Revisión contrastada del texto adjunto y correcciones del QC

El texto recibido combina propuestas, afirmaciones sobre un PDF de 82 páginas y referencias a un
SDD v1.2. Se contrastó con las muestras originales, el código y el plan vigente **v1.4**. No se
adoptan sus diagnósticos visuales ni sus fórmulas como hechos comprobados.

## Resultado de la revisión

| Afirmación o propuesta del texto | Resultado al contrastarla | Corrección adoptada |
|---|---|---|
| El dosier confunde falta de evidencia con mala adquisición | La regla porcentual era coherente con la petición original, pero su presentación inducía a una conclusión que los datos no demostraban | Separar evaluación, hallazgos y evidencia; resultado `NO_EVALUABLE` si la evidencia pendiente puede cambiar la categoría |
| Sin ADC no se puede medir SNR | Incorrecto para una razón de potencias con escala común y ganancia estable | SNR condicional en unidades nativas; rails siguen siendo necesarios para confirmar clipping |
| Sustituir siempre varianza por MAD | Incorrecto: son estimandos distintos fuera del modelo gaussiano | Conservar potencia total y reportar MAD como escala robusta complementaria |
| Usar el percentil 25 del ruido para corregir no estacionariedad | Selecciona ruido más silencioso y puede inflar SNR | Reportar potencias por bloques; no escoger retrospectivamente el más limpio |
| Usar automáticamente la coda como ruido | La coda puede contener señal, reverberaciones y ondas superficiales | Sin referencia independiente, no usar ese fallback |
| Fase cero garantiza que el primer arribo no cambia | Incorrecto: el operador es bidireccional, puede generar energía antes del inicio y alterar el picker | Copias candidatas, pruebas explícitas y ninguna sustitución de originales |
| Canal 22, Chevremont 60 m, truncado | No se confirma: 4000 muestras finitas, cola variable hasta el final, sin tramo final constante | No etiquetar truncamiento; detectar por separado colas digitales constantes y exigir duración esperada para confirmar pérdida |
| Eje de correlación en 0 m rotulado SNR | No se reproduce: el PDF leído ya decía «Similitud local» en la página 20 | Mantener ejes separados; SNR condicional marcada con asterisco |
| MASW recibe el protocolo TRS | No se reproduce: `local_similarity` solo se invoca para Chevremont | Mantener rutas separadas; no inventar pretrigger o correlación TRS para Oysand |
| Canales 22–24 de Oysand tienen amplitud anómala por la figura | No se deduce de una figura normalizada independientemente por canal | No diagnosticar ganancia/acople desde esa imagen; conservar amplitudes nativas y referencias declaradas |
| 83.3 y 94.4 Hz son picos espectrales | El dato reportado es frecuencia mediana de potencia, no necesariamente el pico | Conservar la definición, añadir centroide y ancho espectral como medidas distintas |
| Correlación baja demuestra canal muerto; máximo negativo demuestra polaridad invertida | No: ruido, cambios de forma, modos o ciclos equivalentes pueden producirlo | Canal muerto se identifica con muestras; correlación queda como anomalía local sin causa atribuida |
| Falta de consenso demuestra geología, geometría equivocada o mala referencia | No permite separar esas causas por sí sola | Acción concreta: comparar ventanas/ramas y réplicas y comprobar geometría, ganancia y acople |

## SNR: definición y alcance corregidos

Para ventanas declaradas de ruido `n` y señal más ruido `x`, se elimina la media de cada ventana:

`Pn = mean((n - mean(n))²)`; `Px = mean((x - mean(x))²)`

`SNRneta = 10 log10((Px - Pn) / Pn)` cuando `Pn > 0` y `Px > Pn`.

La interpretación requiere que la potencia de ruido sea transferible entre ventanas y que el término
cruzado señal–ruido tenga esperanza cero. La resta, el truncamiento a cero, el cociente y el logaritmo
no son conjuntamente un estimador insesgado universal. Con ruido cero o potencia neta no resuelta,
se informa censura; no se genera SNR infinita ni un valor numérico ficticio.

`sigma_MAD = median(abs(n - median(n))) / 0.67448975` es una escala consistente con sigma gaussiana,
resistente a observaciones extremas. **No mide automáticamente toda la potencia de un ruido impulsivo**.
Si esos impulsos pertenecen al ruido real de adquisición, excluirlos mejora el número de SNR sin mejorar
el dato. Se reportan ambas escalas. [Definición y escalado de MAD, SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.median_abs_deviation.html).

En Chevremont se declara una ventana fija `[-0.75,-0.05)` s en el reloj DELAY y señal `[0,0.18)` s.
No se eligen por mínimo ruido ni por maximizar SNR. Se reportan cuatro potencias de subventana y su
razón máximo/mínimo. Superar 4 activa revisión; pasar no demuestra estacionariedad durante la llegada.
Son límites diagnósticos locales, sin tasa de falsas alarmas calibrada.

Resultados actuales: **335/336 valores finitos de SNR condicional**, uno con potencia neta no resuelta;
237 canales compatibles con el control interno de bloques y 99 variables/no resueltos. Ninguno de esos
conteos certifica la transferencia a la ventana de señal. Tampoco se denomina a esta medida SNR del
primer arribo: para ello falta una ventana asociada a un onset adjudicado, evitando selección circular.
Oysand conserva SNR no evaluable por falta de una referencia de ruido independiente.

## Ruido LF y líneas próximas a 50/60 Hz

El nuevo módulo `geoqc/qc/noise.py` calcula potencia LF sobre PSD Hann y divide por la potencia total
de la ventana de señal, con denominadores y unidades explícitos. Se solicitan 1–15 Hz y un mínimo de
tres ciclos. Con 0.7 s de pretrigger solo se soporta aproximadamente **4.29–15 Hz**: se marca banda
parcial y nunca se informa la cifra como si cubriera 1 Hz. `R > 0.5` genera revisión; no identifica viento,
tráfico o acople ni prueba por sí solo una falla instrumental.

La coherencia cuadrática se estima con Welch, `|Pxy|²/(Pxx Pyy)`, cuando hay soporte. Un único segmento
produce una estimación degenerada; se exigen al menos cuatro segmentos y tres ciclos por segmento.
Para empezar en 1 Hz esto requiere **7.5 s** con solape de 50 %, más que los 0.7 s disponibles.
Se informa ese requisito de adquisición, en vez de rellenar o confundir ruido común con buena señal.
[Definición de coherencia y segmentación, SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.coherence.html).

Se buscan candidatos alrededor de 50 y 60 Hz y sus primeros cinco armónicos bajo Nyquist. La
prominencia se compara con bandas vecinas y se interpola el máximo en log-potencia. Se conserva
`bin_width_hz`, que aquí es aproximadamente 1.43 Hz, y la incertidumbre frecuencial queda desconocida.
Interpolar no demuestra precisión de ±0.02 Hz. No se atribuye red eléctrica por encontrar un pico:
la persistencia, ancho y estabilidad deben comprobarse con un registro de ruido más largo. Las
búsquedas múltiples tampoco tienen aún significación estadística calibrada.

## Supresión: candidato verificable, sin garantía falsa

`filter_candidate` crea una copia con high-pass Butterworth en secciones de segundo orden y/o notch
en frecuencias declaradas. Registra coeficientes, orden, Q, implementación, hashes y cadena de proceso.
Su estado siempre es `CANDIDATE_ONLY`; el original no se sustituye. Un callback puede ejecutar el picker
antes/después: un desplazamiento mayor que `0.25 dt` falla la estabilidad, y la ausencia de cualquiera
de los picks deja la comprobación sin verificar. Un acuerdo entre picks tampoco demuestra exactitud.

`filtfilt` aplica el filtro en ambos sentidos, duplica su orden y tiene efectos de borde; la fase cero
no equivale a conservar un comienzo causal. [Documentación del operador, SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.filtfilt.html).

El [experimento reproducible](../tools/validate_noise_review.py) usa ruido de 3 y 59.95 Hz y un pulso
causal conocido a 0.2 s. El picker TRS existente devuelve **0.201 s en RAW y abstención en el candidato**:
la supresión de esas bandas no basta para aprobarlo. Ver [figura](../evidence/trace_quality/filter_validation.png),
[auditoría](../evidence/trace_quality/filter_validation.json) y [arrays](../evidence/trace_quality/filter_candidate.npz).
No se filtraron automáticamente los registros de campo ni se aplicó este high-pass a MASW.

Tampoco hay una prohibición física universal de filtros causales: su retardo y distorsión deben
formar parte de la calibración del estimador. Elegir causal o bidireccional no sustituye esa validación.
Para Wiener, con `x=s+n` y señal/ruido no correlacionados, el filtro no causal de mínimo error
cuadrático es `H=Sss/(Sss+Snn)` bajo el modelo de segundo orden; minimizar ese error no garantiza
minimizar el error del pick. [Derivación, MIT, capítulo 11](https://ocw.mit.edu/courses/6-011-introduction-to-communication-control-and-signal-processing-spring-2010/f135b328c7448bf21c4939ea9ff8f8fb_MIT6_011S10_chap11.pdf).
Una cancelación adaptativa con canal de referencia requiere una observación simultánea correlacionada
con el ruido y suficientemente separada de la señal deseada. El pretrigger ayuda a estimar estadísticas;
no proporciona automáticamente la realización del ruido que ocurrió durante la llegada.

## Correlación: corrección de la fórmula del texto

Si `xi = si + ni`, el ruido de ambos canales es independiente entre sí y de la señal, las razones de
potencia son `gamma_i = Var(si)/Var(ni)` y las señales alineadas tienen correlación `rho_s`, entonces:

`rho_observada = rho_s sqrt(gamma_i gamma_j / ((1 + gamma_i)(1 + gamma_j)))`.

Es una relación poblacional bajo esos supuestos, derivada de la covarianza. Para SNR iguales y señal
perfectamente correlacionada se reduce a `gamma/(1+gamma)`. La expresión del texto
`gamma_i gamma_j/(1+gamma_i+gamma_j)` puede superar uno y no es un coeficiente de correlación válido.
Multiplicar por `(1 - 3/sqrt(n_eff))` no convierte esa relación en un umbral universal: faltan un modelo
de incertidumbre, dependencia temporal, selección del máximo entre lags y corrección por comparaciones.
Por ello no se impone un umbral «adaptativo» no calibrado usando SNR condicional.

Se mantiene el detector local existente, explícitamente provisional, con mayoría de vecinos coherentes,
desfases acotados por geometría y sin atribuir causas. Se añadieron centroide, ancho RMS del espectro,
RMS de llegada y razón de amplitud local como auxiliares; esta última no prueba mal acople sin controlar
propagación, sensibilidad y ganancia. Los canales **7 y 29 del disparo 0 m** mantienen sus anomalías.

## Decisión y evidencia, sin cambiar el denominador solicitado

Se conservan los cortes 90 % / 75 % y todas las trazas. Se calcula un intervalo conservador:

- Límite inferior: buenas demostradas / total.
- Límite superior: (buenas demostradas + trazas pendientes sin falla demostrada) / total.
- Si los extremos caen en categorías distintas, la evaluación es `NO_EVALUABLE`.
- Las fallas demostradas permanecen malas aunque también falte información.

Chevremont 0 m ahora se presenta como **no evaluable, con 2 malas detectadas y 46 pendientes**,
no como «46 buenas» ni como rechazo demostrado de todo el disparo. Con 30 % de fallas demostradas,
el resultado sí sería mala aunque todo el resto estuviera pendiente, porque el máximo bueno sería 70 %.
Los controles conocidos siguen dando buena a 90 %, regular a 75 % y mala a 70 %.

Por compatibilidad, `data_quality` conserva el cálculo numérico previo; la evaluación con evidencia
está en **`data_assessment`** en QC común y **`assessment`** en los registros del dosier. La tabla/figura
usa `assessment_grade` por canal: verde buena, amarillo revisión, rojo mala y gris no evaluable.
Las notas comunes de ADC/trigger/ventanas se agrupan por registro. Los motivos propios llevan acciones.

## Reproducción y alcance pendiente

```powershell
.\.venv\Scripts\python.exe tools/report_trace_quality.py
.\.venv\Scripts\python.exe tools/validate_noise_review.py
.\.venv\Scripts\python.exe -m pytest tools/tests/test_noise_review.py tools/tests/test_trace_quality.py tools/tests/test_trace_similarity.py tools/tests/test_field_report.py -q
```

Las pruebas distinguen potencia y MAD bajo impulsos, comprueban ganancia/SNR, ruido variable, huecos,
ruido cero, líneas desviadas y armónicos, duración/coherencia, pre-ringing, rechazo de picks inestables,
no mutación de originales, límites porcentuales y el supuesto truncamiento del canal 22.

Quedan pendientes la calibración de tasas de error en campo, ventanas adjudicadas del primer arribo,
diagnóstico causal de acople/geometría, incertidumbre de líneas y una validación que permita promover
un filtrado a procesamiento operativo. No se sustituyen esos pendientes por promesas de invariancia
ni se cambia el SDD histórico o sus obligaciones para declarar un gate aprobado.
