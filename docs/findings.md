# Auditoría del SDD GeoQC-Field v1.3

Fecha: **3 de octubre de 2026**, America/Mexico_City. Documento auditado: `SDD_QC_Geofisico_MASW_TRS.md`, SHA-256 `144d000a250e48dc70786a8d991c702c518b675d16ce11b2522e36791f309bf8`.

**Dictamen: requiere revisión antes de implementar los criterios de aceptación.** La arquitectura y la intención de trazabilidad son aprovechables. Sin embargo, el plan contiene errores demostrables, pruebas que exigen información no identificable y supuestos que todavía no permiten sostener una decisión de suficiencia del levantamiento. Una auditoría documental no puede demostrar ausencia absoluta de errores ni sustituye la validación experimental.

Se auditó el documento completo, los cinco archivos de código/configuración entregados y las referencias accesibles indicadas en cada hallazgo. Los experimentos reproducibles están en [audit_plan_numerics.py](audit_plan_numerics.py), y los resultados, versiones y hashes en [audit_plan_v1_3.json](../evidence/audit_plan_v1_3.json). No se modificaron el SDD original, las pruebas originales ni sus tolerancias. Ningún gate queda cerrado mediante esta auditoría.

## Cómo interpretar los hallazgos

**Bloqueante**: cambia la lógica de aceptación, contiene una contradicción matemática o impide ejecutar el protocolo tal como está escrito. **Alta**: debe resolverse antes de validar el módulo afectado. **Media**: necesita especificación para una implementación verificable. Las prioridades son juicios de revisión.

**Error confirmado** significa contradicción documental, derivación o contraejemplo ejecutado. **Laguna** significa información o regla necesaria ausente. **Calibración pendiente** significa que la propuesta es admisible como hipótesis, pero su valor numérico todavía no está validado. Ningún umbral alternativo sugerido aquí se presenta como aprobado.

## Hallazgos bloqueantes

### H01 — NACD está definido con la distancia equivocada

**Error confirmado.** E0.4, E5.4, V-E5-9, Anexos A y C.

El plan usa `NACD = x1 / lambda`. El parámetro publicado es la distancia media fuente–receptores normalizada: `NACD = mean(r_j) / lambda`; en un arreglo regular, unilateral y completo, `mean(r_j) = x1 + (N-1) dx / 2`. Puede existir además un criterio conservador sobre el primer receptor, pero necesita otro nombre y su propia calibración.

Con `N=24, dx=2, x1=6, lambda=48 m`, el cociente del SDD es `0.125`; NACD es `29/48 = 0.60417`. Los valores 4.8 y 9.6 m son aritméticamente correctos para la regla propia del plan, pero no son una consecuencia del NACD citado. No se debe sustituir la fórmula conservando automáticamente los umbrales.

Un estudio de campo posterior también usa la distancia media y encuentra criterios distintos según fuente; esto contradice presentar `0.5/0.25` como límites universales de sesgo. Deben documentarse población, fuente y rango geológico de calibración. [Estudio experimental de campo cercano, GJI, 2022](https://academic.oup.com/gji/article/229/3/1531/6505134).

**Corrección:** distinguir `near_offset_ratio` y `nacd_center`; recalcular ejemplos y perfiles después de elegir y validar cuál gobierna el QC. Para canales enmascarados, usar los receptores activos y registrar la selección. No inferir inmediatamente que la geometría original sí cubre 30 m.

### H02 — La frecuencia natural del geófono no impone una profundidad máxima física

**Error de interpretación confirmado; calibración pendiente.** Changelog v1.3, E0.4, E2.7, E5.4, OQ-11.

La función de transferencia y los números `|H|` son correctos. También lo son los cálculos nominales `15.075 m` para 4.5 Hz y `33.919 m` para 2 Hz, si se asumen `c=169.595 m/s` y `k_g=1`. Pero `f_n` no es un corte duro, como reconoce el propio SDD. Esos resultados son estimaciones condicionadas; no prueban que la profundidad alcanzable real sea 15 m.

Una respuesta común a todos los canales altera amplitud y fase común, pero no necesariamente la pendiente de fase espacial. Importan el SNR, las diferencias de respuesta entre sensores, la fuente y la cadena completa. La corrección instrumental no recupera información perdida en ruido.

Las guías InterPACIFIC permiten evaluar frecuencias inferiores a la natural mediante calibración e inspección espectral; consideran geófonos de 4.5 Hz habitualmente adecuados para objetivos someros de unos 30 m. Esto tampoco garantiza 30 m en cada sitio. [Foti et al., §2.1.1](https://iris.polito.it/bitstream/11583/2680600/1/10.1007_s10518-017-0206-7.pdf).

**Corrección:** llamar al término `nominal_low_frequency_depth`, informar supuestos y sustituirlo en el QC por una banda observada validada. Añadir respuesta compleja, tolerancias entre sensores, sensibilidad, ADC, ruido propio, calibración y tratamiento de respuesta desconocida. Una cota inferior estimada que no alcanza el objetivo significa «no demostrado», no «imposible».

### H03 — Se confunden planificación, banda observada y profundidad resoluble

**Laguna y contradicción de severidad.** E0.4, E5.4, E5.7, V-E0-8b.

La geometría puede permitir longitudes de onda que nunca aparecen con SNR suficiente. `max_s min(...)` es solo un límite geométrico de planificación; omite continuidad, energía, instrumentación, canales activos y modos realmente observados. Reutilizarlo para dar PASS a la profundidad de campo puede producir falsa suficiencia.

`lambda_max/kappa_z` es una regla de alcance nominal; no demuestra por sí sola resolución de Vs(z), unicidad ni exactitud de Vs30. El test de sensibilidad al 90 % tampoco demuestra identificabilidad: concentración de sensibilidad y resolución del problema inverso son propiedades diferentes. Para kernels deben definirse norma, parámetros, signo y normalización; sumar derivadas por capas sin definir parametrización hace depender el resultado de la discretización.

Además, E0 registra `PROJECT_INFEASIBLE` como FAIL, V-E0-8b introduce WARN para una cota inferior y E5.7 vuelve a FAIL si el objetivo supera la estimación. No hay una regla común que resuelva esos casos.

**Corrección:** separar `planning_envelope`, `observed_valid_band`, `nominal_depth` y `target_resolution_evidence`. La misma utilidad matemática puede apoyar las rutas, con entradas y estados distintos. Un prior Vs_min y un solo nu no son una cota rigurosa para perfiles arbitrarios; requieren hipótesis explícitas sobre el medio completo. El prior nunca basta para dar PASS observado.

### H04 — El coeficiente 0.886 corresponde a potencia, y la conversión a velocidad se linealiza fuera de su rango

**Error confirmado por cálculo.** V-E5-3, E5.2.

El SDD define una imagen de **amplitud** `I=|sum fasores/N|`. Para el kernel de Dirichlet de 24 receptores:

| Definición | FWHM × N × dx, en número de onda en ciclos/m |
|---|---:|
| Amplitud I, al 50 % | 1.207476 |
| Potencia I², al 50 % | 0.886557 |

Por tanto, `0.886` no es el FWHM de I. Además, `c=f/q` es no lineal. Si la semianchura en q es `d` y el pico está en `q0`, el ancho exacto es `Delta c/c0 = 2 a/(1-a²)`, `a=d/q0`, siempre que ambas fronteras permanezcan positivas.

Para `lambda=L_eff`, incluso usando potencia, el ancho exacto es `1.10336 c`, frente a `0.886 c`: error de aproximadamente 24.5 %, superior al ±15 % exigido. Con amplitud, el ancho exacto es `1.90004 c`. El test no es correcto tal como está escrito.

**Corrección:** declarar amplitud o potencia, medir primero el ancho en q, transformar exactamente las fronteras y limitar la aproximación lineal a picos estrechos. El relleno de ceros interpola la rejilla, no aumenta la resolución física.

### H05 — El ancho del pico no es la desviación estándar del estimador

**Error confirmado.** E5.5, V-E5-11, Anexo C.

`FWHM/(2 sqrt(2 ln 2))` convierte el ancho de una función gaussiana en su escala gaussiana. La imagen de coherencia no es una densidad de probabilidad ni una verosimilitud gaussiana. El ancho por apertura puede permanecer grande cuando el centro de un pico aislado se estima con gran precisión a SNR elevado.

Con el propio coeficiente del SDD, `lambda=75 m`, `L_eff=96 m` impone `sigma_c/c >= 0.293945` por construcción. Esto no concuerda con usar ese COV como indicador de precisión al 5–10 %. El Anexo C tampoco distingue inequívocamente COV de incertidumbre y COV entre disparos; ambos deben tener IDs y umbrales separados.

**Corrección:** reportar resolución del espectro e incertidumbre de estimación por separado. Calibrar esta última con réplicas y experimentos independientes, incluyendo sesgo. El jackknife espacial cambia el arreglo y sus dependencias; no debe asumirse equivalente a réplicas independientes. Exigir cobertura de intervalos por banda, SNR y familia geológica, no solo cobertura agregada.

### H06 — La cola asintótica Rayleigh no es siempre conservadora

**Error confirmado mediante cuadratura y Monte Carlo.** E5.4b, inciso (b) de V-E5-17; no confundirlo con V-E5-17b, el test separado de ruido real.

Para N=12 y `a=sqrt(-ln(0.3)/12)=0.3167508`:

| Método | P(|S| > a) |
|---|---:|
| Aproximación exp(-N a²) | 0.300000 |
| Integral de Kluyver | 0.306362 |
| Monte Carlo, 2 000 000 realizaciones | 0.306121 ± 0.000326 (1 error estándar) |

La cola exacta excede la asintótica en un punto del rango `p∈[0.001,0.3]` exigido por el SDD. Verificar colas pequeñas no prueba dominancia global. La desigualdad propuesta `P_emp <= P_Ray (1+3 sigma)` también confunde el error absoluto de una proporción con un margen relativo.

Sí se reprodujeron los cuantiles de cola 0.0005: `0.744483`, `0.545573`, `0.392000` para N=12,24,48. La integral y estos valores son útiles bajo la hipótesis nula declarada. [Representación de Kluyver en el trabajo de Borwein y colaboradores](https://www.carmamaths.org/resources/jon/walkstalk-jmm.pdf).

**Corrección:** retirar la afirmación universal de conservadurismo. Comparar valores exactos y empíricos con `|p_emp-p_ref|` e intervalos binomiales adecuados; no convertir una desigualdad falsa en gate.

### H07 — Corregir el número de velocidades no corrige la dependencia entre canales

**Laguna estadística.** E5.4b, V-E5-17b de ruido real.

Hay dos cantidades diferentes: el número de receptores independientes y el número de hipótesis de velocidad examinadas. La correlación espacial reduce la información de los receptores y puede generar picos coherentes. Aumentar `N_eff` de velocidades no reproduce esa distribución nula.

Bonferroni se aplica al número de hipótesis efectivamente evaluadas; no requiere independencia. Sustituirlo por «bins independientes» estimados mediante un FWHM variable en c no conserva automáticamente su garantía. Conviene trabajar en q o lentitud y especificar toda la búsqueda. El control por frecuencia tampoco equivale a control por registro: se buscan múltiples frecuencias, offsets, modos y trayectorias.

**Corrección:** separar `n_active_receivers`, dependencia de canales y multiplicidad. Validar la distribución del máximo de la búsqueda completa con surrogates/ruido de campo que preserven estructura espacial y temporal. Un tren coherente de tráfico puede pasar el test de coherencia; falta un control de propagación/ventana/causalidad para distinguirlo del evento activo.

### H08 — El sintético de campo lejano no valida sesgos de campo cercano

**Laguna de validación.** E3.3, V-E5-10, E11.

La suma modal asintótica `exp(-ikr)/sqrt(kr)` valida el transformador en campo lejano. No contiene por sí sola el campo completo de la fuente ni la interferencia de ondas de cuerpo responsable de parte del sesgo cercano. «Corrección de campo cercano» y «términos evanescentes de orden bajo» no identifican un modelo físico ni un error de truncación.

disba documenta dispersión, elipticidad, autofunciones y kernels; una curva de dispersión no constituye un Green completo de fuente puntual. [API y algoritmos oficiales de disba](https://github.com/keurfonluu/disba).

**Corrección:** definir un generador independiente con fuente, componente, superficie libre, propagación, convergencia y límite de campo lejano verificables. Puede ser un Green estratificado validado o modelado de onda completa. El mínimo necesario para validar el gate cercano debe existir antes de certificar ese criterio; no puede quedar íntegramente postergado a E11. Hasta entonces, el sesgo indicado es desconocido y el criterio es provisional.

### H09 — V-E4-10 exige detectar capas que pueden ser invisibles a primeros arribos

**Error confirmado por no identificabilidad.** E4.3, V-E4-10, Anexo A.3.

Se construyó un modelo de tres velocidades `300/600/1500 m/s`, espesores `5/0.5 m`, cuya rama intermedia nunca es primera llegada. Un modelo de dos capas `300/1500 m/s`, con espesor `5.233854 m`, produce exactamente los mismos tiempos en el experimento de 0–200 m; la equivalencia procede de igualar el intercepto de la rama profunda y no solo del muestreo numérico. Un detector basado únicamente en esos tiempos no puede distinguir los modelos.

Una capa de baja velocidad tampoco tiene que producir aumento de pendiente o salto. En capas planas con ramas observables crecientes en velocidad, el primer tiempo es la envolvente inferior de ramas: es continuo y sus pendientes pueden disminuir. Ausencia de indicios no demuestra ausencia de capas ocultas. [Limitaciones documentadas por USGS](https://pubs.usgs.gov/of/2013/1102/of2013-1102_text.pdf).

**Corrección:** emitir «riesgo de no identificabilidad» cuando corresponde al alcance del método, sin prometer detección universal ni FPR≤5 % para fenómenos indistinguibles. Añadir pares de modelos equivalentes como validación negativa y evidencia complementaria cuando se requiera resolverlos.

### H10 — La verdad del primer arribo está indefinida para una Ricker centrada

**Laguna física y numérica.** E3.2, E4.1, V-E4-1..3.

Una Ricker centrada en `t_verdadero` tiene soporte bilateral infinito; su centro no es el inicio de un pulso causal. STA/LTA y AIC pueden detectar su lóbulo previo. Exigir precisión submilisegundo respecto al centro mientras se llama al resultado «primer arribo» no define correctamente la verdad de referencia.

El filtro fase-cero es bidireccional; su ausencia de desfase en estado estacionario no garantiza ausencia de energía previa a un onset. Deben evaluarse precursor, bordes y sesgo de picking. [Documentación de filtfilt](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.filtfilt.html).

**Corrección:** especificar un onset causal conocido, respuesta de fuente/instrumento, delay y verdad antes/después del procesamiento. Calibrar sesgo e incertidumbre para ese estimando. Definir AIC con tamaños de segmentos exactos y manejo de varianza cero, tamaños mínimos y extremos. El caso sin ruido no debe producir división por cero en incertidumbre o reciprocidad.

### H11 — Las reglas permiten PASS con comprobaciones críticas ausentes y no definen toda la tabla de verdad

**Error de especificación confirmado.** E6.1, E6.0, OQ-09.

Una única advertencia importante sigue siendo PASS si `k_warn=3`; una métrica crítica NA no bloquea PASS si menos del 30 % del total es NA. Falta qué ocurre con FAIL no crítico. Si se ignora, pasar de tres WARN a dos WARN y un FAIL no crítico mejoraría WARN a PASS, violando V-E6-2.

NA reúne cosas distintas: no aplicable, dato ausente, método no válido, cálculo fallido e insuficiencia de evidencia. El porcentaje puede cambiar al añadir métricas informativas, sin que se adquiera evidencia nueva.

**Corrección:** registrar por requisito `mandatory`, `critical`, aplicabilidad, motivo de ausencia y condición de aprobación. Un requisito obligatorio ausente bloquea suficiencia/PASS aunque haya muchas otras métricas. Definir la regla para todos los FAIL y WARN. Separar estado de calidad, completitud de evidencia y autorización de uso. Conservar reportes amarillos sin bitácora como borradores; la ausencia de salvedad debe bloquear aceptación, no ocultar el diagnóstico.

### H12 — El orden estricto de etapas contradice sus dependencias

**Error confirmado.** §0.1, E2, E3, E5.9, E9.

E2 exige cientos/miles de sintéticos e inyectores que se desarrollan en E3. El gate G2 no puede cerrarse antes de disponer de esa base, bajo el orden obligatorio E0→E10. E0.4 además necesita física de referencia presentada como E3.3.

La regla de campo cercano depende de calibración en E5.9/E9, pero E5.9 es opcional y los gates tempranos no distinguen implementación de validación final. No hay estado coherente para «funciona, umbral aún no validado».

**Corrección:** ordenar por dependencias: base/referencias analíticas → ingestión y sintéticos mínimos → QC común → módulos específicos → decisión/UI/reportes → V&V → release. Usar gates de implementación y gates de validación distintos. No exigir calibración final antes de construir las herramientas que la hacen posible.

### H13 — Los gates omiten pruebas que el documento declara necesarias

**Error confirmado.** G4, G5, G6, G8.

| Gate | IDs que quedan fuera de su definición actual |
|---|---|
| G4 | V-E4-18..21: hits, ángulos y correlación con error |
| G5 | V-E5-17, 17b, 18, 19, 20: nula, ruido real, bandas y calibración por N |
| G6 | V-E6-4..5: bloqueo diagnóstico y salvedades |
| G8 | V-E8-3: bloqueo de certificado |

**Corrección:** generar gates de un manifiesto explícito de requisitos y pruebas; distinguir REQUIRED/ADVISORY/NOT_APPLICABLE, con justificación. Actualizar la regla §0.5 para aceptar ADVISORY solo donde esté declarado. El gate no puede omitir silenciosamente la defensa principal contra un PASS incorrecto.

## Hallazgos de prioridad alta

### H14 — FS estimado mediante el máximo observado crea clipping falso

**Error confirmado.** E2.3.

Una sinusoide limpia sin recorte produce `phi=0.13` al tomar FS de su propio máximo y aplicar `|u|>=0.98 FS`: rebasa ampliamente FAIL=0.001. Estar cerca del máximo observado no significa tocar el límite del ADC. Un plateau tampoco es prueba suficiente aislada en datos cuantizados.

**Corrección:** usar rails y conversión de ganancia conocidos para confirmar saturación. Si se desconocen, reportar sospecha basada en evidencia combinada; no reutilizar ese máximo como full scale confirmado. Definir ventana y denominador de phi consistentemente —el SDD usa `n_s` pero umbrales «en ventana de señal»— y probar ambas polaridades, cuantización, senoidales y clipping previo al apilado.

### H15 — La correlación cruda no distingue polaridad de fase de propagación; acople y ganancia están confundidos

**Error confirmado y laguna de diagnóstico.** E2.2, E2.5, V-E2-6.

Dos canales limpios separados dx, con `lambda=3dx`, tienen correlación de fase `cos(2pi/3)=-0.5`. La regla `rho<-0.3` acusa inversión legítimamente ausente. Debe definirse si se compara a lag cero, se alinea un delay físico o se estima coherencia de fase en una banda. Buscar el mayor lag sin restricción también puede esconder una inversión en señales periódicas.

Reducir amplitud ×0.2 puede significar acople, ganancia, directividad, interferencia modal o atenuación lateral. El residual no identifica una causa única. Además, log RMS y MAD necesitan manejo de ceros/MAD=0; el gradiente de amplitud con offset afecta el estadístico de «ganancia».

**Corrección:** alinear con propagación físicamente admisible y contrastar varias bandas/réplicas; reportar anomalía de amplitud y causas compatibles. No convertir el residual en certeza de mal acople. Separar confianza del tiempo de arribo y QC de polaridad: invertir el signo no hace necesariamente erróneo un pick.

### H16 — La prueba de reciprocidad exige un efecto mayor que su propia tolerancia

**Error confirmado.** V-E4-6, E4.2, V-E4-7.

En un medio homogéneo de 1500 m/s, 0.5 m producen 0.333 ms; el piso de 1 ms deja pasar el par. No puede exigirse que todo error de 0.5 m falle. El término `max(...,2 sigma)` puede dejar pasar errores grandes si la incertidumbre es grande; ese caso significa poca capacidad diagnóstica, no evidencia fuerte de reciprocidad.

También faltan covarianzas de errores compartidos, mínimos de pares y reglas de atribución. Geometría, t0 y picking pueden generar patrones similares; una pareja no identifica al culpable. En ruido nulo `sigma_Delta=0` vuelve indefinido z. Un factor 2 fijo contradice `z_crit` configurable.

**Corrección:** medir potencia de detección en función de efecto/ruido, exigir pares identificados y geometrías realmente recíprocas, incorporar incertidumbre común y emitir causas candidatas cuando no haya identificabilidad. Separar tolerancia operativa y prueba estadística.

### H17 — Monotonicidad y velocidades aparentes necesitan condiciones de aplicación

**Laguna teórica.** E3.2, E4.3, E4.4.

La monotonía de tiempo con |offset| es un control válido bajo hipótesis específicas, no una ley para todo medio 2D con relieve/lateralidad. Fuentes internas requieren separar lados y ramas; valores de velocidades aparentes pueden diferir por buzamiento sin fallas. La ecuación de refractor inclinado necesita dominio angular, rama físicamente accesible y convención de buzamiento; no se deben aceptar velocidades negativas cuando `theta_c-phi` cambia de signo.

El gradiente lineal requiere `v(z)>0` y rayos dentro del dominio; para g=0 hay que usar el límite y para gradientes de otro signo no reutilizar `1/g` indiscriminadamente. La fuente y los receptores a distinta elevación exigen definir la distancia r de la solución.

**Corrección:** declarar dominios por fórmula, probar límites y derivar alertas de «modelo de referencia inaplicable», sin llamar error de datos a la violación de una hipótesis geológica.

### H18 — Geometría, máscaras y dirección no están suficientemente especificadas

**Error confirmado y lagunas.** §2.3, E1.2, V-E5-6, E5.4.

Permutar conjuntamente trazas y posiciones conserva I. Invertir canales y además negar x refleja la dirección de propagación: necesita cambiar la dirección de búsqueda. El ejemplo ejecutado cambia I de `1` a `0.041667` con c positivo fijo. V-E5-6c mezcla permutación y reflexión.

Tras excluir un geófono, el arreglo puede ser irregular: `N_activo dx` no describe su apertura ni el kernel, y `2dx` uniforme no cubre huecos. Falta separar shot unilateral, bilateral e interno, así como soportes de cobertura por sitio. `Geometry` no contiene y, orientación ni CRS, aunque promete verificar desplazamiento lateral. Elevación z no es por sí misma una falla «fuera de línea».

**Corrección:** representar coordenadas reales, componente/orientación, incertidumbre, máscaras y procedencia. En MASW, separar direcciones o usar distancia radial con hipótesis verificadas; evaluar el kernel del arreglo real y las ambigüedades por huecos. En TRS conservar topografía. La prueba de alias `lambda=1.5dx` incluye un alias de q negativo; una búsqueda exclusivamente en c positivo no lo ve necesariamente.

### H19 — La imagen normalizada no mide energía modal ni garantiza identidad del modo

**Error de interpretación y laguna.** E5.3, V-E5-8.

`I_peak(m1)/I_peak(m0)` es una razón de coherencias de fase, no una razón de energías físicas después de normalizar cada traza por |U|. Amplitudes distintas, fuentes y mezclas pueden producir picos parecidos. Seleccionar la trayectoria más lenta con energía «significativa» no basta para asegurar que el fundamental está observado: puede estar ausente, solapado o confundido con aliases/ruido.

**Corrección:** separar espectro de amplitud/potencia e imagen de coherencia; preservar los datos sin normalizar. Añadir `mode_identity=confirmed/apparent/unknown`, resolución entre crestas y condiciones explícitas para atribución modal. Probar fundamental débil/ausente y modos no resolubles; recuperar correctamente una trayectoria aparente no permite dar por confirmada la fundamental.

### H20 — Hits y ángulos no demuestran unicidad ni garantizan DOI

**Error de alcance y laguna numérica.** E4.4b, V-E4-20..21, E4.5.

En un semiespacio homogéneo con todos los sensores en superficie, los primeros rayos son superficiales: añadir disparos intermedios y off-end no crea por sí solo cobertura a profundidad. La secuencia rojo/ámbar/verde debe definir modelo y profundidad; no puede ser universal. Celdas atravesadas pueden seguir mal resueltas por dependencias entre columnas del Jacobiano y regularización.

`H_c*(h_celda/dx)` no se deriva como normalización invariante a malla. Repetir idénticos rayos eleva hits sin nueva dirección/información; apilados no son observaciones independientes. La cobertura puede ser desconectada, por lo que un DOI único necesita definición. Siddon requiere convenciones de rayos sobre bordes/vértices y conteo de segmentos curvos.

**Corrección:** probar refinamiento de malla, deduplicación y rayos de frontera; añadir tests de resolución/ensembles con geometría real. En celdas vacías, ángulos y tensor son desconocidos, no valores fiables. Definir un ROI y una máscara de resolución. «Shots laterales» requiere ampliar el modelo 2D o declarar que se recomienda otro levantamiento.

### H21 — Chi² bajo y 3–5 iteraciones no prueban recuperación correcta

**Laguna de inferencia.** E4.5, V-E4-14..15, E5.9.

El chi² definido es un misfit normalizado por N; no es automáticamente un chi² reducido con grados de libertad residuales. Ajuste, regularización, errores correlacionados y discrepancia del forward cambian su distribución. Un buen ajuste puede corresponder a un modelo erróneo; un mal ajuste puede deberse a iteraciones insuficientes. Los errores sigma inflados reducen artificialmente el misfit.

La inversión opcional de E5.9 deja sin prueba obligatoria la relación entre el QC y la exactitud de Vs30, aunque el objetivo ingenieril se usa para aceptación. Correlación Spearman agregada puede reflejar el diseño del corpus y no demostrar tasas de error por clase.

**Corrección:** diferenciar no convergencia, error de datos y discrepancia de modelo. Separar controles rápidos de campo de pruebas offline obligatorias de utilidad ingenieril para cualquier perfil que prometa suficiencia Vs30. Validar modelos alternativos, parámetros nuisance, sesgo y cobertura; no aprobar por misfit solo. La doc. oficial muestra que `rayCoverage()` usa el Jacobiano y el manager emplea Dijkstra; no asumir que implementa el FMM declarado. [Código oficial de TravelTimeManager](https://www.pygimli.org/_modules/pygimli/physics/traveltime/TravelTimeManager/).

### H22 — El tamaño de validación real no sostiene el límite de falsos PASS

**Error de alcance estadístico confirmado.** E9.1..3, OQ-07.

Incluso con diez sitios inaceptables independientes y cero falsos PASS, el límite superior binomial unilateral al 95 % es `1-0.05^(1/10)=25.89 %`, no 5 %. Para sostener ≤5 % con cero errores hacen falta al menos **59 casos inaceptables independientes** bajo ese modelo. Si los diez sitios incluyen buenos y malos, el denominador relevante es menor. Muchos disparos del mismo sitio no aportan esa independencia.

**Corrección:** especificar denominadores, intervalos, unidad de muestreo y agrupación por sitio. Separar calibración y prueba por sitio/familia de modelos, no solo por semillas. Registrar acuerdo entre expertos y adjudicación, usar evaluación ciega y reconocer incertidumbre de la verdad de campo. Una inversión final es referencia complementaria, no automáticamente verdad independiente.

### H23 — El tiempo de registro y la banda no están coherentemente presupuestados

**Contradicción condicional y laguna.** E2.1, E5.1, Anexo C, E9.4.

En el perfil Vs30, offset máximo=134 m y `c_min=80 m/s` requieren `134/80+0.3=1.975 s` después del trigger, aun sin margen. Si los 2 s del benchmark incluyen 0.1 s de pretrigger, quedan 1.9 s: insuficientes. Si 2 s son posttrigger, el caso cambia; el SDD no lo precisa. Los tiempos de paquetes dispersivos deben usar velocidad de grupo adecuada, no confundirla con velocidad de fase.

Con dt=0.5 ms, Nyquist es 1000 Hz y la propia regla `0.8 f_N` deja 800 Hz: no cubre una banda TRS objetivo de 1–2 kHz. Eso no implica que toda refracción requiera 2 kHz, pero exige perfiles de muestreo congruentes.

**Corrección:** definir pre/posttrigger, longitud temporal efectiva de FFT/Welch, padding y grupo mínimo. Duración total no equivale a duración útil después de muting. Un pretrigger de 100 ms no define automáticamente una PSD fiable a 2–5 Hz ni precisión espectral universal de 0.1 Hz para el test de red. Fijar tolerancias por duración, estimador y SNR.

### H24 — SNR y recomendaciones de stacks usan convenciones incompletas

**Error de unidades potencial y lagunas.** E2.4, E6.2.

El SNR temporal estima señal neta/ruido; `PSD_s/PSD_n` estima señal+ruido/ruido si la ventana de señal contiene ambos. No se deben comparar los mismos umbrales como si fueran la misma magnitud. Hay que declarar escala lineal/dB, tratamiento de DC, ruido no estacionario, ruido cero y resultado censurado cuando la sustracción no es positiva.

La fórmula de stacks necesita SNR lineal. En dB: `N_req=ceil(N_actual*10^((SNR_obj_dB-SNR_act_dB)/10))`; de 6 a 12 dB, partiendo de 4 stacks, da 16. Ruido correlacionado, clipping o cambios de fuente invalidan ese aumento ideal. El denominador y las ventanas deben mantener comparables las potencias.

**Corrección:** fijar un estimando para cada SNR y una regla explícita para datos ausentes/censurados. Añadir intervalos y condiciones de validez a la acción de stacks. No diagnosticar falta de beneficio de stack únicamente como problema de trigger.

## Hallazgos de especificación y trazabilidad

### H25 — El contrato de datos no contiene los campos que requieren las reglas

**Alta; laguna.** §2.3, §0.7, E6.0, E8, AP-3.

Shot omite t0/delay por canal, máscara, IDs físicos, componente, unidades de amplitud, respuesta y vínculo entre réplica/stack y disparo. Geometry omite y e incertidumbre. Metric omite `valid_band`, `reason`, incertidumbre, aplicabilidad, obligatoriedad y `certifiable`; QCReport omite `diagnostic_mode`, `certifiable`, hashes de datos y versión de esquema. No hay contratos de picks, curvas, bandas por disparo ni cobertura.

Pydantic frozen tampoco hace inmutable el contenido de un ndarray o dict por sí solo. Deben definirse copia/readonly, serialización de numpy, NaN/Inf y digest canónico. Los errores de ingesta deben poder reportarse aunque no exista un Shot válido.

**Corrección:** diseñar estos contratos antes de implementar el motor. Diferenciar tiempo relativo y absoluto, amplitudes counts/V/unidad física, stack sum/mean y procedencia de cada cabecera. Exigir campos según técnica, sin pedir sigma_c en un reporte solo TRS.

### H26 — Configuración, parámetros y perfiles están incompletos

**Alta; error documental y laguna.** §0.12, §2.4, Anexo C.

Los comentarios `# direction` no son campos YAML; la plantilla omite la dirección requerida. Tampoco aparecen muchos umbrales usados por tests: hits/ángulos, porcentajes de celdas, min/max frecuencias, ventanas, margen, acople, sigma, angularidad, definición de crítico/obligatorio y reglas por técnica. Los perfiles nombrados en §2.4 no coinciden con los del Anexo C.

El perfil por defecto tiene 48 canales y `peak_levels.n_reference=24`, de modo que su propio test V-E5-20 impide verde de coherencia. Declarar «perfil factible» no demuestra que pueda terminar en PASS con toda su configuración.

**Corrección:** un esquema único con unidades, dirección, inclusión de fronteras, alcance y versión de calibración; referencia explícita del perfil. Clasificar constantes físicas y parámetros de algoritmo aparte de umbrales operativos: AP-6 no debe prohibir números matemáticos como 2pi. Los tests de frontera deben coincidir con `>`/`>=` de la especificación.

### H27 — Varias pruebas exigen resultados sin definir condiciones que los hacen posibles

**Alta; lagunas.** V-E2-7, V-E2-10, V-E4-8..9, V-E4-13, V-E5-1, V-E5-16.

«SNR≥15 dB» no basta para garantizar error de lag ≤0.05 dt con interpolación parabólica: influyen ancho de banda, duración y ruido. Cambiar dt×2 puede seguir produciendo velocidades plausibles; sin reloj/metadato independiente no es universalmente detectable. Tres capas no implican tres ramas visibles si faltan offsets suficientes. Muting dependiente de canal puede alterar fase aunque un filtro sea fase-cero. Un ancho de coherencia grande no distingue automáticamente dos modos.

FMM requiere fuentes fuera de nodos, interfaces, dominio, norma de error y distancia mínima definida; no se garantiza un máximo relativo universal con «20 celdas por longitud característica». Una malla 10× más fina no sustituye convergencia ni evita todos los sesgos compartidos. disba y un solver propio pueden compartir aproximaciones; la independencia debe justificarse.

**Corrección:** poner dominios, diseño experimental, criterios de abstención e intervalos estadísticos en cada prueba. Definir el sentido del score antes de exigir Spearman negativo en V-E5-16. Incorporar fallas combinadas, near-threshold, modelos fuera de familia y controles imposibles de inferir.

### H28 — BIC, asignación de técnica y aceptación por sitio necesitan reglas adicionales

**Alta; laguna y error condicionado.** E4.3, E6, §1.1.

`p=3K-1` cuenta pendientes, interceptos independientes y quiebres para segmentos discontinuos; con continuidad impuesta cambia el conteo —en una parametrización usual, p=2K—. RSS sin ponderar no corresponde a un likelihood con sigmas heterogéneas conocidas. RSS=0, mínimos de puntos por rama y quiebres en extremos requieren tratamiento explícito.

El plan tampoco define completamente la sustitución de un disparo malo por su repetición válida, la suficiencia de offsets/direcciones, las técnicas obligatorias por objetivo ni el área del sitio representada por un tendido. Si se toma siempre el peor disparo histórico, una repetición correcta nunca libera el sitio; si se ignora un disparo requerido ausente, puede ocurrir lo contrario.

**Corrección:** BIC de un modelo estadístico explícito; conservar registros fallidos y definir selección/supersesión trazable. Aceptar por requisitos de cobertura del objetivo, no por cantidad de registros verdes. Distinguir adquisición aceptable de representatividad ingenieril del sitio.

### H29 — Hash de reporte no es garantía de autorización ni de certificación científica

**Media; error de alcance.** E8.3, AP-1, AP-8.

Un digest sin referencia externa detecta modificación respecto a un digest confiable, pero quien cambia JSON también puede recalcularlo. Una bandera verdadera acompañada de su nuevo hash no demuestra que se hayan cumplido requisitos. Hash de configuración distinto tampoco demuestra que el cambio sea indebido: falta asociarlo a una versión de calibración y decisión registrada.

**Corrección:** el PDF debe recomputar elegibilidad desde requisitos/evidencia validados, no confiar en flags de UI o JSON. Definir qué integridad ofrece el sistema y una referencia confiable si se exige detectar edición deliberada. Excluir timestamps/metadatos volátiles del digest científico reproducible. La firma digital, si se necesita autenticidad, resuelve otro problema. El sello debe decir qué se validó y bajo qué alcance; no presentar QC de adquisición como certificación del subsuelo.

### H30 — El estado «34 tests entregados y verificados» no es reproducible en el directorio actual

**Media; error de estado confirmado.** Changelog, E0.1, pyproject.toml.

Los archivos están en la raíz y faltan `geoqc/core`, `geoqc/synth` y `tests/unit`. pytest está configurado para `tests`, inexistente. La ejecución explícita del archivo falla en colección con `ModuleNotFoundError: geoqc`.

Se copiaron los archivos sin editar a una estructura temporal que refleja los imports: **33 pruebas pasaron y 1 se omitió**, por falta de hypothesis. Eso apoya el módulo de referencia, pero no equivale a 34 pruebas ejecutadas ni a G0/G3 cerrados. `write_evidence` además puede escribir PASSED desde un único test y en directorio temporal; no constituye un agregador de evidencia de todas las validaciones.

**Corrección:** reportar el estado real y empaquetar cuando empiece la implementación. Declarar dependencias de desarrollo, fijar entorno reproducible, registrar skips y hacer que un gate requerido no se apruebe con una prueba omitida. Uniformar `@covers` frente a `pytest.mark.req`, definir los requisitos individuales y eliminar referencias inexistentes `V-T-*`/`V-M-*`.

## Aspectos comprobados que se pueden conservar

- La cúbica de Rayleigh, su transformación desde la ecuación secular y la solución cerrada para nu=0.25 son correctas para el semiespacio isotrópico planteado. La comprobación del residual es algebraicamente equivalente: útil para verificación de implementación, no una segunda teoría independiente.
- Los ratios recalculados son `0.87403205` (nu=0), `0.91940169` (0.25), `0.92741271` (0.30), `0.94219543` (0.40), `0.94895970` (0.45) y `0.95531250` (0.50). Usar `0.95531` redondeado como prohibición exacta rechazaría el propio límite correcto. nu=0.5 debe describirse como límite incompresible; no parametrizar Vp finito por esa igualdad.
- Las fórmulas de refracción horizontal de dos capas, el cruce y la recuperación de h son correctas bajo sus hipótesis. La onda de cabeza requiere distancia físicamente admisible; las pruebas de primeras llegadas deben tomar la rama dominante.
- La convención Fourier negativa es consistente con un retardo `exp(-i2pi f r/c)` y steering positivo en un arreglo unilateral con dirección definida. Deben evitarse energía cero y bins fuera del dominio.
- Las longitudes 46/48/52 m del ejemplo regular, la respuesta de geófono y los cuantiles de Kluyver se reprodujeron. No extienden su validez automáticamente a geometrías irregulares o ruido correlacionado.
- La mejora ideal `10 log10 N` del SNR al promediar ruido independiente es correcta. Separar UI y núcleo, usar SI, conservar procedencia, calibrar umbrales y evaluar datos reales son decisiones adecuadas.
- Vs30 debe explicitarse como `30 / integral_0^30 dz/Vs(z)` o `30/sum(h_j/Vs_j)` con espesores recortados a 30 m. Cobertura de 30 m no demuestra por sí sola el valor de esa media armónica ni autoriza extrapolación silenciosa.

## Plan de cierre antes de implementar criterios de aceptación

1. Revisar los fundamentos H01–H11 y definir qué significa PASS: calidad de adquisición, evidencia suficiente para el objetivo o autorización humana de abandonar sitio.
2. Rehacer orden de dependencias y gates H12–H13; escribir manifiesto de requisitos, métricas obligatorias y validaciones. No ajustar tests solo para satisfacer el plan existente.
3. Resolver contratos y configuración H25–H26, y las condiciones experimentales H14–H24/H27–H28. Publicar una revisión propuesta con supuestos pendientes explícitos.
4. Ejecutar referencias físicas y contrapruebas de no identificabilidad antes de usar resultados para calibrar. La fase sintética de campo cercano debe validar el campo cercano realmente modelado.
5. Calibrar con datos de campo identificados y dejar un conjunto independiente. La evidencia de utilidad Vs30 debe ser obligatoria para el perfil que la invoque.
6. Cerrar V&V con intervalos y límites de aplicabilidad; recién entonces evaluar el alcance de aceptación operativa de una release.

La revisión de texto puede corregir los errores confirmados. Los umbrales de campo cercano, precisión ingenieril, falsos PASS y rendimiento seguirán **pendientes de medición** hasta contar con experimentos y datos suficientes.

## Referencias verificadas y límites de acceso

Las citas en los hallazgos apoyan afirmaciones concretas; el resto de contraejemplos son derivaciones o ejecuciones propias registradas en el JSON. Se consultaron también [SEG-Y rev1, especificación oficial](https://seg.org/wp-content/uploads/2025/11/seg_y_rev1.pdf): intervalos de muestreo en microsegundos y escalares de coordenadas exigen conversiones/quantización explícitas; «dt exacto» y «geometría exacta» solo son exigibles para valores representables. No toda variante little-endian reconocida es corrupción, y SEG-Y no tiene una firma única suficiente para todo archivo. El round-trip debe verificar opciones realmente soportadas.

Para miniSEED hay que declarar revisión y metadatos auxiliares: no asumir extracción universal de geometría de fuente, ganancia, stacking o respuesta desde las muestras. [Documentación FDSN miniSEED](https://docs.fdsn.org/projects/miniseed3/en/latest/) y [StationXML](https://docs.fdsn.org/projects/stationxml/en/latest/overview.html).

Se verificaron las fichas públicas de [ASTM D5777-18, refracción](https://store.astm.org/d5777-18.html) y la identificación de [D7400/D7400M, downhole, en el catálogo oficial](https://store.astm.org/products-services/standards-and-publications/standards/geotechnical-engineering-standards.html). No se revisó el texto completo de normas de pago ni se afirma conformidad normativa. La normativa local y edición aplicable al proyecto permanecen abiertas. La referencia Yoon–Rix se contrastó con el estudio primario posterior citado en H01; no se atribuye a una lectura íntegra del artículo original de 2009.
