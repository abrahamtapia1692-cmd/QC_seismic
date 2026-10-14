# Calidad por traza y dosier de prueba

**Versión actual: dosier esquema 3.** Ver [revisión contrastada y correcciones](revision_qc_trs_ruido.md).
La evaluación de campo ahora distingue **no evaluable**, revisión y fallas observadas. Chevremont
incluye 335 SNR condicionales finitas; un canal no resuelve potencia neta. La cifra no se presenta como
SNR validada del primer arribo. Los resultados porcentuales históricos indicados más abajo se
conservan en `quality`; la decisión vigente está en `assessment`.

| Conjunto de campo | Buenas demostradas | Revisión | Malas | Solo evidencia pendiente | Evaluación |
|---|---:|---:|---:|---:|---|
| Oysand | 0 | 0 | 0 | 96 | No evaluable |
| Chevremont | 0 | 261 | 2 | 73 | No evaluable |

En Chevremont hay 334 trazas sin falla demostrada con evidencia pendiente, incluidas las 261 en revisión.
Los canales 7 y 29 de 0 m siguen rojos. Se mantienen el total de trazas y los cortes 90/75; el intervalo
de porcentaje posible evita confundir falta de evidencia con mala adquisición. Véanse las gráficas de
ruido y los CSV/JSON actualizados. La [prueba de filtrado](../evidence/trace_quality/filter_validation.png)
es una copia sintética experimental; no modifica los datos de campo.

Abrir [dosier HTML](../evidence/trace_quality/dossier.html) o [PDF](../evidence/trace_quality/dossier.pdf).
El HTML es autónomo: lleva las figuras dentro del archivo y permite filtrar la tabla de canales por calidad.
Los [CSV](../evidence/trace_quality/traces.csv) y [JSON](../evidence/trace_quality/dossier.json) conservan
identificadores, métricas, motivos y trazabilidad. Los canales se numeran desde 1 y conservan su ID original.

## Regla solicitada para registros y conjuntos

`porcentaje_bueno = 100 × número_de_trazas_buenas / número_total_de_trazas`

| Calidad | Porcentaje de trazas buenas |
|---|---|
| Buena | ≥90 % |
| Regular | ≥75 % y <90 % |
| Mala | <75 % |

Se incluyen todas las trazas en el denominador, también las regulares y las incompletas.
La decisión usa conteos enteros, antes de redondear el porcentaje mostrado: 89.9 % es regular.
Un conjunto suma las trazas de sus registros, sin promediar porcentajes. Un conjunto vacío queda
sin calificación (`grade: null`). Cada traza de un disparo cuenta una vez; no se deduplica el receptor
entre disparos ni se interpreta como una observación estadística independiente.

## Criterio inicial por traza

Se reutilizan las métricas del QC común. Los límites por canal son **locales y provisionales**;
no fueron especificados por el usuario ni se presentan como límites físicos universales.

| Evidencia | Buena (verde) | Regular (amarillo) | Mala (rojo) |
|---|---|---|---|
| Integridad | Todas las muestras válidas | Huecos parciales | Sin soporte válido suficiente en análisis |
| Señal | Variable | Anomalía de amplitud respecto a modelo declarado | Canal muerto o constante |
| SNR neta | ≥12 dB | ≥6 y <12 dB | <6 dB o potencia neta no resuelta sobre ruido verificado |
| Clipping | ≤0.1 % | >0.1 y <1 % | ≥1 % |
| Evidencia | Integridad, SNR y clipping evaluables | Falta información para decidir | Una falla demostrada prevalece sobre faltantes |

La categoría es la peor condición encontrada. Alertas de línea de red, banda fuera del margen
de Nyquist o duración insuficiente para el escenario declarado producen regular.
SNR requiere ventanas disjuntas, ruido independiente y estacionariedad verificada. Ruido AC cero
es censura, no SNR infinita ni evidencia de calidad buena. Clipping requiere rails y escala conocidos;
un apilado puede impedir su evaluación. No se infiere un canal malo de una abstención del picker.
La falta de un modelo de amplitud no inventa anomalías entre receptores con distinta atenuación.

Los umbrales se pueden ajustar mediante `quality_policy` dentro del protocolo de QC:

```json
{
  "quality_policy": {
    "id": "TRACE_QUALITY_V1_DRAFT",
    "snr_good_min_db": 12.0,
    "snr_bad_below_db": 6.0,
    "clip_good_max_fraction": 0.001,
    "clip_bad_min_fraction": 0.01
  }
}
```

El campo es opcional, por lo que los protocolos anteriores siguen funcionando. `geoqc qc` incorpora
`traces[].quality`, `quality_policy` y `data_quality`. El `report.quality_status` anterior conserva
su significado de peor métrica del perfil. La calificación solicitada por porcentaje está en
**`data_quality.grade`**. Ninguna categoría nueva habilita `eligible_for_acceptance`.

## Ejecución y resultados del cálculo porcentual inicial

```powershell
.\.venv\Scripts\python.exe tools/report_trace_quality.py
.\.venv\Scripts\python.exe -m pytest tools/tests/test_trace_quality.py tools/tests/test_field_report.py -q
```

Se puede usar `--output ruta` para elegir otro directorio. El generador vuelve a leer los originales,
comprueba sus hashes contra el manifiesto y conserva las muestras. Para campo solo calcula integridad
del registro completo; no construye un Shot válido a partir de metadatos desconocidos ni reutiliza
calificaciones históricas del picker. Las figuras normalizan cada canal únicamente para visualizarlo.
Se generan PDF, HTML, CSV, JSON y PNG, además de NPZ de los tres controles sintéticos.

| Prueba | Buenas | Regulares | Malas | Calidad del registro |
|---|---:|---:|---:|---|
| Control 90 % | 18 | 1 | 1 | Buena |
| Control 75 % | 15 | 1 | 4 | Regular |
| Control 70 % | 14 | 1 | 5 | Mala |
| Ejemplo E2 existente | 4 | 1 | 1 | Mala (66.67 %) |
| Oysand, cuatro registros | 0 | 96 | 0 | Mala por 0 % de buenas demostradas |
| Chevremont, siete registros | 0 | 334 | 2 | Mala por 0 % de buenas demostradas |

Los controles usan ruido iid con semilla 20261010, canales de bajo SNR, clipping y canales muertos;
se comparan las categorías obtenidas de las muestras con etiquetas conocidas. Estas etiquetas no
entran al clasificador. Se validan también límites decimales, faltantes, conteos, colores y datos
de campo. Esto valida implementación y presentación, no transferencia de umbrales a campo.

En el conteo de compatibilidad, **430 trazas de campo quedan regulares y dos malas por anomalía local de forma**.
La evaluación vigente separa ahora faltantes y revisión, como se indica al inicio de este documento.
La integridad de las muestras pasa, pero
faltan rails/escala ADC y ventanas de ruido/señal con estacionariedad verificada. Por la regla solicitada,
el cálculo numérico inicial daba malo con 0 % de trazas demostradas buenas. La evaluación vigente es
NO_EVALUABLE por el intervalo de evidencia pendiente. Esto no demuestra averías ni que las
432 trazas sean malas. El dosier muestra ambos niveles y sus motivos. Para resolver las categorías pendientes
hacen falta los metadatos y el protocolo de adquisición, sin elegir ventanas para forzar un resultado verde.

El PDF incluye resumen, gráficas y motivos por canal. El JSON registra hashes de originales, configuración
y código, protocolos usados y resultados de los controles; el dosier registra su hora de generación en UTC.

## Consistencia local de formas de onda

Se incorporó correlación cruzada normalizada entre receptores próximos, con media y norma recalculadas
en cada solape. El desfase está limitado por `min(max_lag_s, distancia/min_apparent_velocity_ms)`;
se conserva al menos 75 % de las muestras de la ventana. No se filtra, rellena, comprime ni remuestrea
silenciosamente. Es una medida de similitud como la descrita en la
[documentación de ObsPy](https://docs.obspy.org/packages/autogen/obspy.signal.cross_correlation.correlate_template.html).
Los límites numéricos aquí adoptados son propios, provisionales y no provienen de esa referencia.

Para Chevremont se usan las ventanas del protocolo de picking anterior, sin ajustarlas a los canales
señalados: llegada `[0,0.18)` s y línea base `[-0.25,-0.05)` s. El reloj DELAY sigue sin verificación externa.
Los [parámetros reproducibles](../examples/field/similarity_protocol.json) declaran radio 2.1 m, hasta cuatro
vecinos, velocidad aparente mínima de escenario 100 m/s y tope de desfase de 20 ms. Se usan distancias de
la geometría local y se comprueba CHANNEL_NUMBER. La comparabilidad instrumental es provisional.

La decisión requiere al menos tres vecinos válidos y evalúa:

1. Mediana de la magnitud de correlación con los vecinos. Menos de 0.5 es una diferencia fuerte;
   entre 0.5 y 0.8 requiere revisión; a partir de 0.8 la forma es compatible.
2. Consenso de una mayoría de al menos tres vecinos **sin incluir al canal examinado**. Todos los
   pares de esa mayoría deben superar o igualar 0.8. Esto evita que un único vecino anómalo
   degrade a los receptores sanos. Si no hay consenso, se conserva regular por referencia heterogénea.
3. Para rojo: correlación mediana <0.5 y al menos 75 % de correlaciones individuales <0.5,
   además del consenso anterior. No se impone por ser simplemente el peor canal del registro.

Se conserva el signo de cada correlación y su desfase, pero no se interpreta un máximo negativo
como prueba de inversión de polaridad: una onda oscilatoria puede tener ciclos equivalentes.
La métrica tampoco es un picker ni una medición validada del tiempo de viaje.
La frecuencia mediana de potencia y la RMS de línea base dividida por RMS de llegada son auxiliares.
Una razón de línea base relativa >5 veces la mediana de los vecinos genera revisión, no una SNR física.

En el registro **Chevremont 0 m**, el método detecta automáticamente:

| Canal | Correlación local | Consenso entre vecinos | Frecuencia mediana | Línea base relativa a vecinos |
|---|---:|---:|---:|---:|
| 7 | 0.201 | 0.948 | 83.3 Hz | 8.3× |
| 29 | 0.272 | 0.942 | 94.4 Hz | 2.1× |

Ambos quedan rojos, con sus métricas y motivos en HTML/PDF/CSV/JSON. La
[ampliación automática](../evidence/trace_quality/anomalies_05.png) compara formas alineadas,
espectros y línea base con los vecinos. Los ajustes de desfase y signo se usan solo para visualizar
la comparación; los originales se conservan. La vista de todas las trazas muestra su forma original.
En los otros seis disparos no se activa este criterio de anomalía fuerte. Esto no identifica una
avería persistente del sensor: la causa puede ser acoplamiento, ruido, adquisición o un fenómeno local.

La correlación complementa los controles anteriores; no elimina los faltantes de SNR/clipping ni
certifica la física del subsuelo. La coherencia también puede aparecer en ruido común. Cambios laterales,
dispersión o interferencias pueden producir diferencias legítimas. Por eso el protocolo TRS no se aplica
automáticamente a Oysand MASW. Los cortes de 90 % y 75 % del conjunto se mantienen.

En `geoqc qc`, se activa opcionalmente con `similarity` dentro de `QCProtocol`, usando los mismos campos
del JSON indicado. Devuelve `traces[].similarity`, y las alertas se incorporan a `traces[].quality`.
Las pruebas en `tools/tests/test_trace_similarity.py` cubren retardos, amplitud/DC, anomalías aisladas,
vecinos contaminados, vecindarios heterogéneos, orden de canales, huecos, relojes y la integración con QC.
