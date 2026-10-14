# SDD — GeoQC-Field: calidad y suficiencia de adquisición MASW/TRS

**Versión:** 1.4 · **Fecha:** 2026-10-03 · **Idioma:** ES.
**Revisión documental:** MASW-R1 · 2026-10-12; base 1.4 conservada.
**Estado:** implementación diagnóstica con evidencia histórica G0–G5 en dominios declarados; refuerzos MASW-R1 y calibración de campo pendientes.
**Documento vigente de trabajo:** este archivo. La [v1.3](SDD_QC_Geofisico_MASW_TRS.md) se conserva como referencia histórica, sin modificaciones.

Esta revisión incorpora la [auditoría H01–H30](docs/findings.md). Corrige definiciones, pruebas y dependencias; no acredita validación de campo ni cierra gates. Los valores empíricos iniciales son hipótesis de calibración, no garantías físicas ni normativas. El [manifiesto](docs/validation_manifest_v1_4.json) enumera todos los tests y dependencias; el [registro de revisión](docs/revision_v1_4.md) distingue corrección documental de validación pendiente.

La [revisión MASW-R1 y su anexo D normativo](docs/masw_review_2026_10_12.md) complementan E3/E5 y los contratos de E0/E6/E8. Sus ocho obligaciones RM constan en un [manifiesto complementario](docs/validation_masw_r1.json) con estados iniciales NOT_RUN. La [primera implementación](docs/masw_r1_implementation.md) agrega contratos, evidencia modal, covarianza y evaluación por criterios; los resultados se registran aparte. La evidencia anterior no aprueba los refuerzos; el cierre ampliado de G5 está pendiente. Los 100 IDs base conservan su significado. El [ADR 0002](docs/adr/0002-masw-r1.md) exige vincular revisión/hash y completar migración/integración antes de cerrar el alcance ampliado. Puede continuar el desarrollo diagnóstico con aceptación operativa deshabilitada.

## 0. Protocolo de ejecución y evidencia

1. Ejecutar según el grafo de dependencias de §0.1, no por orden numérico E0→E10. E3 aporta sintéticos antes de cerrar E2. La referencia Rayleigh V-E3-4 se verifica en E0.
2. TDD para implementación: escribir pruebas significativas, observar el fallo esperado y luego implementar. Las pruebas físicas deben tener una verdad independiente del algoritmo evaluado.
3. No relajar tolerancias para aprobar. Cambios de teoría, estimando o criterio de aceptación se documentan en ADR con derivación, evidencia y versión de esquema/calibración. La corrección documental autorizada en esta revisión no autoriza umbrales operativos aún no calibrados.
4. Aleatoriedad: `numpy.random.Generator(PCG64(seed))`. Registrar semilla, plataforma, versiones, threads y entradas. Determinismo numérico en CPU/entorno fijado: exacto cuando corresponda, o tolerancia explícita por magnitud; no prometer igualdad de PDF con timestamps distintos.
5. Cada test produce evidencia derivada del resultado real: `id, specification_version, status, input_hashes, config_hash, code_hash, metrics, tolerances, seed, versions, timestamp, artifact_refs`. No aceptar JSON PASSED autoafirmado como cierre de una suite. Evidencia de auditoría v1.3 es histórica, no evidencia de implementación v1.4.
6. Gates: estado `NOT_RUN/RUNNING/PASSED/FAILED/INCOMPLETE`. Todos los tests obligatorios deben ejecutarse y pasar en un entorno identificado. Un skip obligatorio deja INCOMPLETE. Este documento no declara ninguno PASSED.
7. Resultado sin validez, motivo e incertidumbre explícitos no se presenta como estimación fiable. Un dato no aplicable, ausente, inválido o un cálculo fallido se distinguen.
8. Núcleo headless sin dependencias de UI; SI internamente. Unidades de amplitud conservadas —counts, V o magnitud física— con conversión documentada.
9. Evitar inverse crime: generador/forward/malla/parametrización independientes y convergencia comprobada. Diferente semilla o una malla más fina, por sí solas, no bastan.
10. Cada métrica numérica de decisión exige casos PASS/WARN/FAIL, fronteras, entradas desconocidas y casos de modelo inaplicable. Umbrales viven en configuración con unidad, dirección, inclusión de frontera y versión de calibración. Constantes matemáticas no son umbrales operativos.
11. Una métrica obligatoria con umbral empírico no validado puede visualizarse en diagnóstico, pero no habilita aceptación automática.
12. Mantener [decisiones abiertas](docs/open_questions.md), sin convertir valores iniciales en decisiones del proyecto. Cambios de esquema/configuración se versionan y migran.

### 0.1 Dependencias y alcance de gates

| Gate | Dependencias | Pruebas obligatorias |
|---|---|---|
| G0 — contratos, herramientas y referencias | ninguna | V-E0-1..10, V-E3-4 |
| G1 — ingesta | G0 | V-E1-1..6 |
| G3 — sintéticos básicos | G0 | V-E3-1..7 |
| G2 — QC común | G1, G3 | V-E2-1..10 |
| G4 — TRS en dominio sintético | G2 | V-E4-1..21 |
| G5 — MASW en dominio sintético | G2 | V-E5-1..22, V-E5-17b, V-E3-8 |
| G6 — decisión | G4, G5 | V-E6-1..6 |
| G7 — UI | G6 | V-E7-1..3 |
| G8 — reportes | G7 | V-E8-1..4 |
| G9 — calibración y validación independiente | G8 | V-E9-1..7 |
| G10 — empaquetado y operación | G9 | V-E10-1..2 |

G4/G5 verifican comportamiento en el dominio sintético declarado. G9 valida perfiles, umbrales, instrumentación y utilidad ingenieril con holdout y datos reales. G10 habilita un release solo en ese alcance. E3.5 y V-E3-8 se ejecutan antes de cerrar G5; no son requisito del generador básico G3. V-E3-4 se reutiliza en G3 con trazabilidad y evidencia vigente, sin duplicar la física.

## 1. Objetivo, límites y estados

Evaluar offline registros MASW y/o tomografía de refracción P para informar calidad de adquisición, suficiencia **demostrada** de evidencia respecto al objetivo y acciones correctivas. Meta inicial: ≤60 s por disparo en hardware fijado; es un requisito de rendimiento a medir, no un estado alcanzado.

Alcance inicial: fuentes activas, Rayleigh registrado en componente vertical, refracción P, tendido con coordenadas conocidas y aproximación 2D cuando sea válida. Datos SEG-2, SEG-Y rev0/1 y miniSEED opcional con metadatos auxiliares. Horizontal no significa automáticamente P: componente y onda objetivo deben declararse; SH/Love requieren un perfil y validación propios. MASW pasivo/ReMi, 3D e inversión final de producción quedan fuera de v1.0.

No confundir calidad de adquisición con exactitud de Vs30 ni con unicidad del subsuelo. Un control automático apoya al responsable de campo; no acredita una certificación normativa.

| Campo | Valores y significado |
|---|---|
| `quality_status` | PASS/WARN/FAIL de comprobaciones aplicables con resultado válido; null si no hubo ninguna |
| `evidence_status` | COMPLETE/INCOMPLETE/OUT_OF_SCOPE respecto a requisitos obligatorios |
| `eligible_for_acceptance` | booleano recomputado desde requisitos, evidencia vigente y calibración |
| `operator_decision` | PENDING/ACCEPTED/REPEAT/EXTEND, con responsable, alcance y salvedades |

Veredicto de suficiencia: GREEN únicamente si la evidencia obligatoria está completa, calibrada en alcance, sin FAIL/WARN obligatorio pendiente y `eligible_for_acceptance=true`. YELLOW indica salvedad o insuficiencia que requiere resolver/aceptar explícitamente; RED corresponde a fallo crítico no resuelto. OUT_OF_SCOPE se muestra como tal, no como GREEN. Los motivos completos acompañan el color.

Un reporte diagnóstico/borrador siempre puede exportarse. Su exportación no es aceptación del levantamiento. Un amarillo con salvedad no desaparece al aceptar manualmente: se registra quién aceptó qué.

## 2. Convenciones físicas y contratos

### 2.1 Geometría, tiempo y Fourier

Coordenadas reales `xr,yr,zr,xs,ys,zs`, sistema/origen local y transformación desde CRS documentados. z es elevación —positiva hacia arriba—; profundidad positiva hacia abajo desde la superficie local. Distancia horizontal/radial y longitud de rayo son campos distintos. Offset firmado `xr-xs` conserva dirección; fuentes internas se separan por lados antes del análisis unilateral MASW/TRS.

`time_i = t0_i + i*dt`; `t0_i` es inicio de registro respecto al trigger físico corregido. Signo, unidad y procedencia de delay se resuelven por formato/equipo. SEG-Y codifica dt en microsegundos: conservar cuantización, escalares de coordenadas y unidades; exactitud solo para valores representables. [SEG-Y rev1 oficial](https://seg.org/wp-content/uploads/2025/11/seg_y_rev1.pdf).

Fourier `U(f)=integral u(t) exp(-i2πft) dt`; `q=f/c` en ciclos/m; `k=2πq` en rad/m. Retardo de propagación produce `exp(-ikr)`.

En arreglo regular, unilateral, completo: `L_ap=(N-1)dx`, `L_eff=N dx`, `L_total=x1+L_ap`, `r_mean=x1+L_ap/2`. L_eff describe el kernel rectangular regular; no se extrapola a canales faltantes, ventanas diferentes o geometría irregular. El kernel general usa posiciones y pesos activos reales.

### 2.2 Contratos requeridos antes de implementar el algoritmo

Modelos versionados Pydantic, con copia/readonly de arrays y estructuras anidadas donde se prometa inmutabilidad:

| Modelo | Campos mínimos además de ID/version |
|---|---|
| Acquisition | técnica, onda, componente, orientación, fuente, trigger, receptor físico, respuesta/calibración, ADC/rails, gain, unidades, stack sum/mean, IDs de réplicas |
| Geometry | coordenadas 3D, incertidumbre/covarianza, CRS/origen, permutación y procedencia |
| Shot | matriz, dt y t0 por canal cuando difieran, máscaras/motivos, geometría, adquisición, hashes originales, headers conservados |
| Metric | value/null, unidad, ámbito/soporte, applicability, validity/reason, incertidumbre, direction, threshold refs, mandatory, critical, calibration ref, quality_status/null, acciones |
| ArrivalPick | onset estimado, incertidumbre/intervalo, sesgo calibrado, estado de confianza, ventana, preprocessing ref, correlaciones compartidas |
| DispersionCurve | f,c, sigma/intervalos y covarianza o modelo de covarianza, bandas por disparo/dirección, resolución, mode_identity, incertidumbre de modo, máscara, procedencia por punto |
| Coverage | ROI, mesh, topografía, modelo de rayos, hits independientes, DWS, ángulos, máscara de resolución, limitaciones |
| QCReport | quality/evidence states, requisitos satisfechos/faltantes, diagnostic_mode, elegibilidad derivada, alcance, config/data/code/calibration hashes, evidencia, decisión humana separada |
| IngestFailure | archivo/hash cuando disponible, error tipado, causa y acción; no obliga a construir un Shot inválido |

`applicability=APPLICABLE/NOT_APPLICABLE/UNKNOWN`; `validity=VALID/MISSING/INVALID/MODEL_INAPPLICABLE/COMPUTATION_ERROR/UNCALIBRATED`. NOT_APPLICABLE requiere fundamento en el perfil y no se usa para ocultar ausencia de medición. NaN/Inf no se serializan como estimación; valores censurados llevan intervalo/cota y motivo. Datos corruptos pueden conservarse en bruto, enmascarados para análisis.

### 2.3 Arquitectura y herramientas

```text
geoqc/core: models, config, physics, planning, evidence, units, errors
geoqc/io: readers, geometry, writers
geoqc/qc_common: integrity, channels, noise, timing, repeatability, instruments
geoqc/synth: wavelets, faults, modal, eikonal_models, nearfield_reference
geoqc/trs: picking, reciprocity, timedist, coverage, tomo
geoqc/masw: preprocess, dispersion, picking, resolution, nearfield,
            repeatability, uncertainty, target_evidence
geoqc/decision: requirements, rules, actions, aggregator
geoqc/report: json_log, pdf
geoqc/ui: capa de presentación
tests/{unit,property,synthetic,regression,performance}
configs/  evidence/  docs/adr/
```

Python≥3.11, numpy/scipy, Pydantic v2, YAML, pytest/hypothesis/ruff/mypy; lectores y UI mediante dependencias opcionales probadas: ObsPy, segyio, disba, pyGIMLi, PySide6/pyqtgraph y PDF. Verificar API, unidades y soporte de instalación; lock por plataforma. CLI antes de UI. SEG-D fuera de alcance. Referencia disba usa períodos y unidades propias: convertir explícitamente desde SI y comprobarlo en el adaptador. [Documentación oficial de disba](https://github.com/keurfonluu/disba).

Antecedente de la entrega auditada v1.3: sus imports originales no funcionaban como paquete. En reconstrucción temporal hubo 33 PASS y un skip por hypothesis; no declarar «34 tests PASSED» ni usarlo como cierre G0/G3. El paquete actual y su evidencia posterior se describen en el README; este antecedente no describe su estado presente.

## E0 — Herramientas, contratos y planificación

### E0.1 Referencia Rayleigh

Semiespacio lineal elástico isotrópico: `ξ=(c_R/Vs)²`, `κ²=(1-2ν)/(2(1-ν))`:

```text
P(ξ) = ξ³ - 8ξ² + 8(3-2κ²)ξ - 16(1-κ²)
P(0)<0; P(1)=1; resolver raíz física en (0,1).
ν=0.25: ξ=2-2/√3.
```

ν=0.5 representa límite incompresible; no asignarle Vp finito. La cota del rango ν∈[0,0.5] es `c_R/Vs=0.9553125010256315`, no un redondeo como barrera exacta. Valores a 8 decimales: 0.87403205 (ν=0), 0.91940169 (0.25), 0.92741271 (0.30), 0.94219543 (0.40), 0.94895970 (0.45). Viktorov es aproximación, no verdad de referencia. Si se ofrece rango auxético, validarlo también.

### E0.2 Planificación condicionada

`planning(cfg)->PlanningReport` informa escenarios, priors, banda prevista, incompatibilidades e hipótesis; no declara suficiencia observada. Dejar NACD del centro y ratio al receptor próximo como métricas distintas:

```text
lambda(f)=c(f)/f
nacd_center(f)=mean(r_j activos)/lambda(f)
near_offset_ratio(f)=min(r_j activos)/lambda(f)
nominal_depth=lambda_max_scenario/kappa_z
```

No trasladar automáticamente umbrales 0.5/0.25 de v1.3 a la definición corregida. NACD y límites de sesgo dependen de fuente/modelo y requieren validación específica. [Rahimi, Wood e Himel, GJI 2022](https://academic.oup.com/gji/article/229/3/1531/6505134).

Geófono: respuesta de velocidad normalizada de segundo orden, con convención Fourier anterior, `H(f)=-f²/(f_n²-f²+i2h f_n f)`; módulo `f²/sqrt((f_n²-f²)²+(2h f_n f)²)`. Polos, polaridad y sensibilidad reales deben verificarse contra calibración. `k_g f_n` es política nominal, no corte físico; la banda de campo se valida por SNR y respuesta relativa. Cadena incluye fuente, electrónica y ADC. No inferir imposibilidad desde una cota inferior de velocidad que no alcanza z_obj.

Estados: FEASIBLE_UNDER_ASSUMPTIONS, NOT_DEMONSTRATED, INCOMPATIBLE_WITH_ASSUMPTIONS. Recomendaciones de apertura/offset/frecuencia citan la hipótesis y contemplan banda somera/aliasing, no solo objetivo profundo. Priors Vs_min/ν no constituyen una cota universal de dispersión estratificada.

### E0.3 Pruebas

- **V-E0-1:** paquete importable, suite descubierta, ruff y mypy strict en core; no skips obligatorios por dependencias omitidas.
- **V-E0-2:** semilla/entorno iguales producen arrays idénticos; hash científico canónico estable.
- **V-E0-3:** esquema rechaza umbral incoherente con direction, frontera indefinida y parámetro operativo desconocido/ausente.
- **V-E0-4:** reproducir aritmética histórica 4.8/9.6 m solo como regla near_offset_ratio v1.3; demostrar que no implica imposibilidad física ni sirve como NACD corregido.
- **V-E0-5:** una implementación comparte utilidades entre planificación y QC, preservando distinción entre entradas previstas y observadas; prior favorable no genera PASS observado.
- **V-E0-6:** perfiles Vs30/cimentación generan escenarios coherentes o NOT_DEMONSTRATED; tests de ambas bandas, fronteras y efecto conjunto de N/dx/offset, sin exigir monotonicidad universal de calidad.
- **V-E0-7:** notación/apertura/geometría consistente; con huecos no reutilizar automáticamente N_activo dx ni Nyquist uniforme.
- **V-E0-8:** respuesta geófono y estimaciones nominales 15.07513/33.91904 m reproducidas bajo supuestos; ninguna se etiqueta límite físico. Banda sub-f_n validada/desconocida se distingue.
- **V-E0-9:** contratos mantienen máscaras, tiempo, unidades, incertidumbre y procedencia; serialización sin NaN y contenido inmutable cuando se promete.
- **V-E0-10:** manifiesto contiene cada ID exactamente una vez en registro, toda prueba pertenece a un gate y dependencias no tienen ciclos; ningún REQUIRED+SKIPPED permite PASSED.
- **V-E3-4:** referencia Rayleigh contra forma cerrada, solver alternativo, residual algebraico, límites, monotonicidad en dominio y validación de entradas. Residual equivalente no se presenta como segunda teoría independiente.

## E1 — Ingesta y geometría

Lectores conservan headers y resuelven firma/contexto plausible; SEG-Y carece de una firma única universal. Variantes endianness reconocidas se leen explícitamente; bytes mal interpretados generan error, no corrección silenciosa. Coord scalar, unidades, delay, ganancia y stack se convierten con procedencia y tolerancia de representación.

miniSEED requiere versión y sidecar/manifiesto de fuente/geometría/trigger; StationXML puede aportar instrumento/receptor, pero no sustituye automáticamente metadatos de un disparo activo. No fabricar source/stack desde waveform. [FDSN miniSEED](https://docs.fdsn.org/projects/miniseed3/en/latest/) y [StationXML](https://docs.fdsn.org/projects/stationxml/en/latest/overview.html).

Geometría: posiciones/permutaciones/máscaras, irregularidad y error de coordenadas son cosas distintas. Topografía z conocida se usa en TRS; desviación y requiere evaluación 2D. Diferencia de cabecera y CSV se interpreta con incertidumbre y precedencia explícitas, sin asumir autoridad de ninguno sin fundamento.

- **V-E1-1:** round-trip SEG-Y IBM/IEEE realmente soportado: amplitudes rtol=1e-6 con atol de quantización declarado; dt/coordenadas exactos solo representables, resto dentro de quantización registrada.
- **V-E1-2:** truncados/vacíos/dt inválido/header inconsistente generan IngestError accionable; endian reconocido y corrupción se distinguen.
- **V-E1-3:** property n_ch∈[1,96], n_s∈[16,32768], dt representable en formato; forma/máscaras y metadatos se conservan. No prometer dt exacto para float continuo arbitrario.
- **V-E1-4:** coordenadas conocidas desplazadas producen irregularidad calculada, no certeza de error; umbrales iniciales 20/50 % son diagnósticos hasta calibración. Probar topografía, y, huecos y receptor fuera de soporte.
- **V-E1-5:** fuente interna y bilateral separadas; distancias y orientación exactas para ejemplos representables.
- **V-E1-6:** discrepancias 0.5/0.05 m respecto a referencia fiable se comparan con tol inicial 0.1 m e incertidumbre; metadato ausente queda MISSING.

Gate G1 incluye cobertura de líneas io≥90 %, manejo de formatos y sidecars del alcance habilitado.

## E3 — Referencias sintéticas previas al QC

### E3.1 Señales y ruido

Ricker bilateral sirve para espectro y transformadores, no define un onset causal. Picker se valida con pulso causal especificado `w(t)=0` para t<0, onset conocido, respuesta fuente/instrumento y delay registrado. Truncación/forma se guardan; verdad de onset antes y después del procesamiento distinguida.

Ruido blanco, coloreado, coherente entre canales, tráfico, hum y bursts; covarianza y SNR por ventanas declarados. Comprobar Parseval con normalización FFT y unidades claras. Ruido independiente/stack y señal DC son casos separados.

### E3.2 TRS

Dos capas horizontales V1<V2, h>0, fuente/receptores superficiales:

```text
t_direct=r/V1
t_head=r/V2+ti; ti=2h sqrt(V2²-V1²)/(V1 V2)
x_critical=2h tan(asin(V1/V2))
x_cross=2h sqrt((V2+V1)/(V2-V1))
h=ti V1 V2/(2 sqrt(V2²-V1²))
```

Onda de cabeza solo en rama accesible r≥x_critical; primera llegada es mínimo entre ramas físicas. Buzamiento: velocidades aparentes `V1/sin(theta_c±phi)` requieren convención explícita y dominio 0<theta_c±phi<π/2 para las ramas usadas. Fuera de dominio no interpretar velocidad negativa como refractor válido.

Gradiente positivo `v(z)=v0+gz`, g>0, velocidades positivas y rayo dentro del dominio: `t=acosh(1+g² r²/(2vs vr))/g`, r distancia euclídea de extremos. En g→0 usar límite estable; no extrapolar a g<0 sin derivación del rayo accesible. Referencia eikonal independiente con convergencia y fronteras probadas, no solo «malla 10×».

### E3.3 MASW de campo lejano

Curvas estratificadas mediante algoritmo estable —matriz delta/Dunkin u otra formulación justificada—, modo/periodo/unidades documentados. `U(r,f)=S(f) sum_m A_m(f) exp(-ik_m r)/sqrt(k_m r) exp(-alpha_m r)`, r>0; `alpha_m≈πf/(Q_m c_m)` es aproximación débilmente atenuante. Si se modela fuente finita/campo próximo usar E3.5.

IFFT con simetría conjugada, tiempo suficiente y estudio de padding/truncación: comparar ventanas extendidas y rechazar wrap-around; una desigualdad T≥2 tiempo no basta universalmente para señales dispersivas largas.

### E3.4 Pruebas básicas y fallas

- **V-E3-1:** máximo espectral Ricker en fp±1 bin; Parseval rtol=1e-10; SNR generado vs estimador independiente dentro de tolerancia registrada; onset causal conocido separado.
- **V-E3-2:** fórmulas TRS frente a límites y cruce; valores simples rtol=1e-12/atol temporal 1e-12 s, con dominio explícito y límite g=0 estable.
- **V-E3-3:** reciprocidad en medios estáticos isotrópicos modelados: igualdad analítica o error de convergencia del forward; no exigir bit-exact entre discretizaciones distintas.
- **V-E3-4:** referencia común especificada en E0.
- **V-E3-5:** dos forward de dispersión de origen identificado, tres perfiles incluyendo inversión: diferencia≤0.5 % en banda convergida y modo continuo; cortes/solapamientos no se excluyen silenciosamente.
- **V-E3-6:** límites alta/baja f hacia capa superior/semiespacio en modelos donde esas asíntotas aplican; aproximación≤1 % tras estudio de convergencia.
- **V-E3-7:** inyectores deterministas de muertos, clip, ruido, polaridad, time_shift, geometry, dt, hum, burst, acople aparente, jitter y truncación. Severidad comprobada por otra medida; añadir combinaciones. Error dt no implica detectabilidad universal.

### E3.5 Generador independiente de campo cercano — obligatorio antes de G5

Especificar Green físico estratificado o solver de onda completa con fuente finita, superficie libre, componentes, ondas de cuerpo, respuesta y propagación. Modelo de ondas cilíndricas puede validar su componente geométrica si se limita explícitamente el alcance; no sustituye validar la interferencia de cuerpo. disba suministra curvas/autofunciones, no un Green completo por usar su curva.

- **V-E3-8:** demostrar convergencia en malla/integración/dominio y límite lejano contra referencias; cuantificar error del generador por debajo del sesgo cercano que se pretende medir. Sin ese estudio, no habilitar el criterio de campo cercano como validado.

## E2 — QC común

### E2.1 Tiempo, canales e instrumento

Nyquist `f_N=1/(2dt)`; política inicial `f_max≤0.8 f_N`, más verificación de filtro antialias. Definir T_pre, guard, T_post y T_usable tras ventanas. Registro MASW requiere `T_post≥r_max/v_group_min+T_wavelet+margin`; resolución de FFT útil `1/T_usable` no cambia por padding. Si v_group_min no está demostrado, usar escenario conservador marcado. TRS usa velocidades/accesibilidad pertinentes a primeros arribos. Fase y grupo no se intercambian.

Pretrigger 100 ms es punto inicial de adquisición, no PSD garantizada a 2–5 Hz. Determinar duración por frecuencia mínima, grados de libertad/segmentos, no estacionariedad y precisión requerida. Si falta ruido independiente, SNR=MISSING, sin inventarlo.

RMS, ceros, constantes, DC y MAD se calculan en ventanas/unidades comparables. Estadístico robusto log RMS se aplica a valores positivos y tras tendencia esperada de amplitud/gain; MAD=0 tiene rama explícita. Una anomalía no distingue por sí sola acople de ganancia/propagación.

Clipping confirmado: rails conocidos y escala de cada canal/stack; `phi=#muestras cerca de rail / #muestras válidas en misma ventana`. Sin rails, estimar **sospecha** por evidencias combinadas, nunca FS=max observado. Plateaus cuantizados se contrastan con controles limpios.

### E2.2 SNR, polaridad y repetición

Quitar DC de forma documentada y verificar estacionariedad entre ruido/señal. `SNR_net=max(P_signal_total-P_noise,0)/P_noise`; `SNR_total=P_signal_total/P_noise` es otro estimando. PSD neta usa la misma convención, ventanas/Welch compatibles y unidades. dB=10log10(ratio). Ruido cero, sustracción no positiva y ventana ausente generan cota/estado, no infinidades JSON.

Polaridad: comparar réplicas o vecinos alineados por delay físicamente plausible, banda y componente; correlación sin alineación no diagnostica inversión. Máximo de correlación en señales periódicas requiere ambigüedad explícita. Ajuste `log A=a-n log r-alpha r` solo r>0 y con modelo aplicable; residual sugiere anomalía, no causa única.

Jitter estimado entre fuentes realmente repetidas, señal banda/duración identificada; interpolación submuestra se valida, no se garantiza solo por SNR. `N_req=ceil(N_actual*10^((SNR_target_dB-SNR_actual_dB)/10))` solo para ruido independiente, adquisición comparable y stack promedio o conversión equivalente.

### E2.3 Pruebas

- **V-E2-1:** presupuesto pre/post y banda: ejemplo r=51 m, v_group=80, wavelet=0.3, margin=0 da 0.9375 s; perfil Vs30 r=134 requiere 1.975 s post sin margen. 2 s totales con pre=0.1 no alcanzan. dt=0.5 ms no permite banda de 1–2 kHz bajo regla 0.8 Nyquist.
- **V-E2-2:** muertos k=1..4/24 detectados; controles con atenuación, MAD=0/DC/gain comparable. Meta inicial FPR≤2 % en ≥200 realizaciones, con intervalo y denominador declarados.
- **V-E2-3:** clipping conocido y sinusoide limpia: la sinusoide no es clipping aunque 13 % esté cerca de su máximo; plateaus limpios, ADC, gains y stack incluidos. Fronteras de phi de perfil probado.
- **V-E2-4:** calibración SNR 0/5/10/20/30 dB, ≥500 realizaciones independientes; objetivo inicial error medio≤1.5 dB para SNR≥5 y sesgo≤1 dB, por estrato y ventana. SNR_total/net distinguido.
- **V-E2-5:** líneas 50/60 Hz según sitio: detección/frecuencia con duración/SNR especificados; 0.1 Hz solo para protocolo que sostenga tal precisión. No afirmar precisión por bins interpolados.
- **V-E2-6:** señales propagantes limpias lambda=3dx con correlación cruda -0.5 no generan inversión confirmada; fallas de signo detectadas cuando identificables. Atenuación×0.2 se reporta como anomalía sin causa exclusiva.
- **V-E2-7:** delay submuestra en banda/duración fijadas con error de referencia independiente; meta 0.05dt para experimento prerregistrado, fuera de dominio abstención. No atribuir lag de fuente variable exclusivamente a trigger.
- **V-E2-8:** stack N=1/2/4/8/16 con ruido independiente: pendiente SNR vs10log10N entre0.85 y1.15, con intervalos; correlación de ruido rompe la predicción y se marca.
- **V-E2-9:** H(f) nominal y complejo contra referencia; incluir respuestas relativas distintas, calibración ausente y datos útiles bajo f_n. No emitir límite físico de profundidad desde f_n.
- **V-E2-10:** corpus ≥1000, fallas simples/combinadas y ambiguas con etiquetas independientes; metas iniciales recall≥0.95, FPR≤0.05 por falla identificable. Wrong_dt plausible sin referencia queda no identificable, no fallo obligatorio universal.

## E4 — TRS

### E4.1 Primeros arribos

Cascada STA/LTA y refinamiento AIC; Butterworth fase-cero solo si se cuantifica precursor y sesgo respecto al onset. Banda/ventanas por perfil. Para muestras u[0:N], división k con tamaños k y N-k: `AIC(k)=k log(var(u[:k]))+(N-k) log(var(u[k:]))`, usando varianza de máxima verosimilitud (`ddof=0`), salvo convención distinta derivada explícitamente. k excluye segmentos cortos; piso de varianza dependiente de escala/ruido documentado y probado. No tomar curvatura de AIC como sigma sin calibración.

Incertidumbre estimada por protocolo Monte Carlo/réplicas y sesgo; sigma empírica `a T_dom/sqrt(SNR_linear)+b dt` puede ser modelo candidato, coeficientes/calibración no asumidos. Confianza temporal y polaridad de instrumento son estados separados.

- **V-E4-1:** onset causal con dt=0.25 ms/banda alrededor de80 Hz, duración/filtrado/SNR especificados; objetivos iniciales mediana error≤dt/P95≤3dt para SNR≥15. Se evalúan sesgo y dominio, no centro de Ricker como first break.
- **V-E4-2:** burst/muerto/ambiguo no produce confianza injustificada; inversión de signo preserva tiempo cuando el estimador lo permite, con QC de polaridad separado. Meta de errores confiados >3sigma≤2 % con denominador de picks confiados.
- **V-E4-3:** ≥5000 picks holdout, cobertura de intervalos nominales 68/95 % por estrato con intervalos binomiales y sesgo. Bandas amplias 0.58–0.78/0.90–0.99 de v1.3 sirven exploración, no calibración final automáticamente aprobada.
- **V-E4-4:** escala positiva y traslación temporal compatible con ventana/onset, permutación conjunta de canales; precisión según dt/interpolación. Escalar solo señal sin ruido no conserva SNR y no es invariancia.

### E4.2 Reciprocidad

Identificar pares físicos A↔B y clock/source delay. `Delta=t_AB-t_BA`; `varDelta=varAB+varBA-2covAB,BA`. Covarianza incluye términos compartidos; sigma=0 usa comparación determinista, no división.

Dos salidas: diferencia operativa frente a tolerancia del perfil y discrepancia estadística/potencia de detección. No convertir `max(tol,2sigma)` en prueba de alta calidad: sigma grande puede ocultar error. Consistencia con baja potencia queda evidencia INCOMPLETE si la reciprocidad fiable es obligatoria. RMS(z)≈1 solo bajo el modelo de error correcto y tamaño suficiente, no demuestra ausencia de sesgo geométrico común.

- **V-E4-5:** Delta=0 analítico; con errores conocidos independientes/correlacionados verificar distribución z e intervalos, sigma cero controlado.
- **V-E4-6:** error0.5 m a1500 m/s da0.333 ms y pasa tolerancia1 ms: el test debe respetarlo. Medir potencia para efectos por encima/debajo del umbral; atribución única solo con geometría y observaciones identificables.
- **V-E4-7:** delay2 ms en disparo genera patrón correspondiente, con orientación de Delta registrada; trigger y geometría indistinguibles generan causas candidatas, no certeza automática.

### E4.3 Tiempo–distancia

Separar lados/ramas y modelos aplicables. Segmentos continuos o discontinuos son modelos distintos. BIC=`-2 log likelihood_hat+p log n`; p cuenta todos los parámetros libres, incluido ruido si se estima. Para funciones continuas de K segmentos, K pendientes+intercepto+(K-1) quiebres=2K; discontinuas=3K-1, antes de otros parámetros. Sigmas conocidas heterogéneas usan likelihood ponderado; ajuste robusto no hereda BIC gaussiano sin justificación. RSS=0 y mínimos de puntos definidos.

Monotonía e intercepto directo son controles condicionados por geología/relieve/cobertura. Aumento de pendiente o salto no identifica capa oculta. Primeros arribos equivalentes dejan incertidumbre del subsuelo; discrepancia con hipótesis no significa necesariamente mala adquisición.

- **V-E4-8:** dos ramas visibles y suficientes receptores por rama: metas V≤2 %, ti≤1 ms, h≤5 % con sesgo/onset/ruido definidos. Si no hay rama observable, abstenerse de recuperar h.
- **V-E4-9:** K corresponde a ramas visibles, no número universal de capas; selección BIC y grados de libertad probados en modelos1/2/3 observables y ocultos.
- **V-E4-10:** modelos300/600/1500 m/s con h5/0.5 m y equivalente300/1500 con h≈5.2338536 m producen mismos primeros tiempos cuando el espesor equivalente se calcula igualando interceptos —no usando su redondeo mostrado como dato exacto—; el sistema no inventa un detector universal. Documentar riesgo de no identificabilidad y evidencia complementaria requerida por objetivo.
- **V-E4-11:** outliers10 % con amplitud≥20 ms en protocolo de offsets/SNR prerregistrado: objetivos recall≥0.95 y sesgo de pendiente≤1 %, con intervalos y casos inaplicables.

### E4.4 Cobertura, solver y prueba de inversión

`L_ap/z_obj` y `x_max/x_cross` son heurísticas de planificación, no suficiencia. Enumerar disparos físicos requeridos —extremos, internos y externos— y cobertura/pares que aportan. Cinco internos y dos externos son siete, no cinco. Incluir modelo, ROI/topografía, puntos por rama y profundidades realmente sensibles.

Hits de observaciones independientes, DWS=sum longitudes, ángulos móduloπ por celda. Span=`π-max_gap_circular`; tensor normalizado de vectores direccionales y A=lambda_min/lambda_max. Cero rayos: métricas angulares desconocidas; un ángulo: span0 y A0. Repetir rayos no agrega dirección; pesos/correlaciones se registran. Siddon especifica bordes/vértices/segmentos y conservación de longitud. No asumir H*h/dx como normalización invariante.

ROI y máscara de resolución pueden ser discontinuos. No convertir toda cobertura en una isóbata DOI única ni afirmar unicidad por hits/ángulos. Usar resolución/ensembles independientes y regularización. Off-end no crea cobertura profunda en semiespacio homogéneo con sensores superficiales.

Forward FMM propio y forward de referencia pyGIMLi son implementaciones distintas; adapter documenta método/version y rayos. Convergencia: mallas/horizontes, fuentes fuera de nodo, borde, interfaces y normas definidos. Inversión rápida con presupuesto inicial3–5 iteraciones puede devolver NOT_CONVERGED, sin atribuirlo a datos malos.

Misfit `Q=(d-f)^T C_d^-1(d-f)/n` cuando C_d modelado y no singular; si diagonal, media de residuales cuadrados/sigma². Es misfit normalizado, no chi² reducido con grados de libertad garantizados. Reportar RMS, sesgo, residuales, convergencia y modelo de error; regularización/ruido inflado pueden mejorar Q sin recuperar velocidad.

- **V-E4-12:** h15,V1=300,V2=1500: x_cross=36.74235 m; multiplicador1.5 exige55.1135 m bajo esa heurística. 46/72 m no prueban solos insuficiencia/suficiencia real; verificar puntos por rama.
- **V-E4-13:** solver frente a solución analítica y mallas refinadas, norma/domino definidos; meta p_obs≥0.9 en problema suave primer orden, singularidades separadas. Error de tiempo requerido dentro del presupuesto de picking.
- **V-E4-14:** modelo recuperable en ROI conocida, ruido0.5 ms independiente: evaluar Q/convergencia/error de V por capa; metas iniciales Q0.7–1.5 y error≤10 % no sustituyen resolución ni aplican a capas no identificables.
- **V-E4-15:** errores5 %: evaluar detección/potencia y sesgo en protocolo independiente; incremento50 % de misfit es objetivo específico del experimento, no propiedad universal del solver flexible.
- **V-E4-16:** presupuesto25 s para24 canales×12 disparos medido en hardware/prera y primera/caché; excederlo genera aviso de rendimiento separado de calidad.
- **V-E4-17:** ≥300 escenarios recuperables/ambiguos/inaceptables, etiquetas independientes y tasas por estrato; severo obligatorio no resuelto nunca habilita aceptación.
- **V-E4-18:** Siddon vs intersección independiente en rectas, bordes/vértices y curvas discretizadas; hits exactos con mismas convenciones, longitud rtol1e-10 más atol dimensional declarado.
- **V-E4-19:** ángulos0/60/120° dan span120°; ángulo único span0,A0; vacío UNKNOWN. Distribución uniforme exacta o comparación Monte Carlo con intervalo, no garantía por cualquier n≥200.
- **V-E4-20:** arreglos bajo modelo específico para los tres estados y controles de semiespacio sin profundidad; no imponer verde solo por añadir disparos. Validar refinamiento de malla y duplicados.
- **V-E4-21:** asociación cobertura/resolución/error por ROI y familias independientes, intervalos y confusores. Spearman≤-0.5 es hipótesis inicial que no demuestra unicidad; evidencia insuficiente no autoriza recalibrar contra holdout.

## E5 — MASW

### E5.1 Transformador y resolución

Preprocesamiento preserva waveform original. Ventanas/muting por canal pueden alterar fase y resolución; registrar y validar efectos en banda. Aire c≈340 m/s depende de condiciones y puede solaparse con Rayleigh; no eliminar automáticamente toda energía a esa velocidad.

Para dirección d=±1 y coordenada along-line x, `I(f,c,d)=|sum_j w_j exp(+i2π f d x_j/c) U_j/|U_j||/sum_j w_j`, con w≥0, amplitud no cero y canales activos. Caso unilateral radial usa r con su hipótesis. Canales sin energía se excluyen con motivo; conservar kernel real. No llamar a I energía modal. f–k y tau–p son referencias cruzadas con sesgos/ventanas registrados.

Arreglo uniforme y pesos rectangulares: `D(Delta q)=|sin(π N dx Delta q)/(N sin(π dx Delta q))|`, extendido por límite en ceros removibles. FWHM de amplitud y potencia son distintos. Para N=24: `FWHM_q*Ndx=1.2074756732` en I, `0.8865573942` en I². Calcular fronteras en q y convertir exactamente a c; `Delta c/c0=2a/(1-a²)`, a=(FWHM_q/2)/q0<1. Si cruza q=0 no hay FWHM finito en c.

Nyquist uniforme q_N=1/(2dx), lambda_min=2dx; factor inicial2.5 es margen de política a validar. Mask/huecos y arreglos irregulares necesitan kernel/ambigüedades reales. Buscar direcciones firmadas para no perder aliases negativos. Padding no aumenta apertura ni resolución física.

- **V-E5-1:** filtro/ventana comune vs muting distinto por canal: medir fase/resolución y error de pico en protocolo fijado. Meta fase≤1e-3 rad solo en caso controlado al que aplica.
- **V-E5-2:** plano f0=5 Hz,c0=100 m/s,N24,dx2, frecuencia bin exacta y ventana común; I=1±1e-6/pico en c0 dentro rejilla. Signo contrario no alinea este ejemplo, evitando coincidencia alias accidental.
- **V-E5-3:** resolver kernel finito para amplitud/potencia y transformar fronteras en lambda/L_eff=0.25/0.5/1; contraejemplo a aproximación0.886 universal debe conservarse. Tolerancia ligada a rejilla/root, no ±15 % de teoría equivocada.
- **V-E5-4:** lambda1.5dx produce alias q-1/dx negativo en búsqueda firmada; lambda3dx sin alias indistinguible en dominio Nyquist elegido. Huecos/irregularidad evaluados aparte.
- **V-E5-5:** referencias phase-shift/f–k/tau–p dentro2 % mediana en banda convergida de alta SNR; no cubrir desacuerdos con exclusión arbitraria de bins.
- **V-E5-6:** permutación conjunta U/x/pesos conserva I; reflexión x→-x exige d→-d. Escala común positiva/fase común conserva I con soporte fijo. Excluir muertos preserva la curva de canales activos, no garantiza mejora estricta del pico ni misma resolución que arreglo completo.

### E5.2 Curvas, bandas y modos

Extraer crestas y trayectorias con programación dinámica, penalización dimensional y sensibilidad a priors/rejilla. Mode_identity=CONFIRMED/APPARENT/UNKNOWN; modo más lento observado no confirma fundamental si este está ausente o hay alias/ondas de cuerpo. Amplitud/potencia sin normalizar ofrece atributos distintos de coherencia I; ninguna razón I1/I0 es energía física modal.

`B_s` por disparo/dirección/componente combina máscaras de datos, SNR neto, respuesta relativa, aliases, significancia, sesgo cercano y modo. Mantener bandas diagnósticas/validadas distintas, puntos con incertidumbre y soporte. Unión entre disparos solo con compatibilidad en solapes y procedencia punto a punto; no rellena huecos ni altera el soporte de sitio.

NACD_center y near_offset_ratio se evalúan por receptores activos y lambda observada. Umbrales iniciales de v1.3 quedan retirados como regla operativa validada; nuevos límites requieren E3-8/E5-10 y G9. La banda cercana no validada se marca UNCALIBRATED. f_n no corta automáticamente toda frecuencia menor; tampoco garantiza señal de fuente allí.

- **V-E5-7:** tres familias normal/inversión/contraste, fundamentales visibles y no visibles: objetivos3/6 % RMS para SNR20/10 solo en banda observable; casos ambiguos deben abstenerse de identidad fundamental.
- **V-E5-8:** A1/A0=2 no obliga detección universal; probar modos separables y no resolubles/ausentes, curvas aparentes e incertidumbre de identidad sin inferir energía desde I.
- **V-E5-9:** ejemplo N24,dx2,x1=6,lambda48: near_ratio0.125,NACD_center0.6041667; no conservar profundidad4.8 como resultado NACD. Priors/union no permiten inventar banda observada.
- **V-E5-10:** sesgo cercano Delta c/c vs ambos ratios usando V-E3-8, fuente/modelos calibración/holdout independientes; metas de sesgo5/2 % son objetivos de perfil a comprobar, no presets aprobados. Declarar sesgo desconocido cuando el generador no cubre el fenómeno.

### E5.3 Incertidumbre y nula

Resolución del espectro no equivale a sigma del estimador. Estimar incertidumbre de c con modelo/réplicas independientes, reportar sesgo y covarianza entre frecuencias; remuestreo de canales cambia kernel y dependencia. No imponer sigma=FWHM/2.355 como piso estadístico. Separar `precision_cov=sigma_c/c` de `repeatability_cov=std_shots/mean_shots`.

Nula de N fases independientes uniformes y pesos iguales: R=|sum exp(i phi)|, S=R/N. CDF_R(r)=`r integral_0^infty J1(rt) J0(t)^N dt`. Q_N se define para S, no R. Cola asintótica exp(-Na²) es aproximación, **no cota superior global**. Cuantiles de cola0.0005:0.744483/0.545573/0.392000 paraN12/24/48.

Cuadratura requiere error/truncación registrados y dominio N validado; para N bajos, pesos distintos o fases dependientes no reutilizar tabla sin método adecuado. Control de máximo en toda rejilla usa multiplicidad y surrogates validados; Bonferroni sobre hipótesis evaluadas no necesita independencia, pero «bins efectivos» aproximados no heredan garantía. Correlación de receptores no se corrige aumentando solo cantidad de velocidades.

Significancia del pico no identifica origen: tráfico coherente puede superarla. Verificar relación con disparo, ventanas de control, dirección/velocidad y repeatability. Declarar unidad de falso pico —frecuencia/registro— y controlar búsqueda por f,c,d,offset/modo/trayectoria. N_levels y N_active separados; niveles de coherencia solo transferibles con evidencia.

- **V-E5-11:** cobertura y sesgo de intervalos c por SNR/banda/modelo, con CI y holdout; no usar intervalos globales0.55–0.85 como calibración definitiva.
- **V-E5-12:** experimento identificado de dependencia con SNR/apertura/lambda, reportar regresión/CI y excepciones; no exigir monotonicidad universal al cambiar modos/soporte.
- **V-E5-17:** Kluyver vs MC≥2 millones bajo nula: error con CI binomial y multiplicidad. Verificar cuantiles a±0.005 y el contraejemplo N12,a0.3167508,cola0.30636>asintótica0.3. No imponer dominancia falsa ni sumar error absoluto como relativo.
- **V-E5-17b:** ruido real/coloreado/correlacionado y nula del máximo; control de falsos picos al nivel del protocolo y su intervalo. Si falla, método UNCALIBRATED, no ajuste improvisado contra holdout.
- **V-E5-18:** casos y fronteras del umbral de significancia calibrado, cohorte independiente; significancia sin control del ruido coherente no habilita aceptación.
- **V-E5-20:** N_active distinto del alcance de niveles => UNCALIBRATED; configuración exige calibración compatible. Perfiles48ch no heredan levels24ch por defecto.

### E5.4 Repetibilidad, profundidad y utilidad ingenieril

Comparar curvas en soporte común compatible y con incertidumbre; diferencias sistemáticas indican inconsistencia compatible con lateralidad/fuente/modos, no causa exclusiva. COV repetibilidad0.05/0.10 es hipótesis inicial por perfil, no precisión de Vs30.

Segmento contiguo más largo de banda confirmada: `B_oct=log2(f_hi/f_lo)`. Dos octavas no garantizan grados de libertad independientes ni profundidad resuelta. Para objetivo30 m, `nominal_depth=lambda_max_observed/kappa_z` es estimación de alcance; kappa2–3 es hipótesis, no kernel universal. Informar también cobertura somera y banda incompleta.

Sensibilidad: derivar kernels respecto a parámetros físicos/normalizados explícitos; integración en profundidad usa medida/norma declaradas. Sensibilidad acumulada no es resolución; incluir covarianza/prior, modelos alternativos y objetivo. Vs30=`30/integral_0^30 dz/Vs(z)` o30/sum(h_j/Vs_j), con espesores recortados y sin extrapolación silenciosa. Un perfil que prometa suficiencia Vs30 requiere validación de error ingenieril obligatoria, aunque inversión de campo siga siendo opcional.

- **V-E5-13:** repeatability por réplicas y offsets con incertidumbre calibrada; gradiente lateral no se atribuye inequívocamente a partir de un par si fuente/modos confunden.
- **V-E5-14:** kernels normalizados/convergencia de discretización/ROI y ensembles: regla90 %/kappa2–3.5 se evalúa como hipótesis, no prueba de resolución. Casos de igual dispersión y distinto Vs30 se consideran cuando aplican.
- **V-E5-15:** ≥300 escenarios etiquetados por evidencia del objetivo, no solo lambda/kappa; banda ausente, incertidumbre/modalidad no válida o requisito obligatorio faltante nunca habilitan aceptación.
- **V-E5-16:** obligatorio para perfiles Vs30: estimador de referencia/ensembles independientes con precisión objetivo inicial±15 %, sesgo y CI. Asociación con QC por estrato y sentido de score definido; Spearman negativo solo si score crece con calidad, sin sustituir tasas de falsos PASS.
- **V-E5-19:** banda8–32Hz produce exactamente2 octavas según fronteras; segmentos separados no se fusionan como continuos.
- **V-E5-21:** ruido de tráfico coherente significativo sin evidencia del evento activo => no aceptación automática; controles de dirección/ventana/fuente.
- **V-E5-22:** unión de bandas con hueco/modos distintos/soportes distintos preserva motivos y procedencia; ningún prior sustituye dato observado ni produce suficiencia Vs30 por geometría sola.

## E6 — Motor de decisión y acciones

Perfil enumera requisitos del objetivo, datos/técnicas/ROI obligatorios y evidencia/calibración compatible. Registro de métricas completo y versionado: campos mínimos según §2.2, regla de aplicabilidad, restricciones de entrada y rango de calibración. Un parámetro no especificado no obtiene un default silencioso.

Reglas deterministas de agregación:

1. Quality de métricas válidas aplicables: cualquier FAIL=>FAIL, de lo contrario cualquier WARN=>WARN, todas PASS=>PASS; sin resultados válidos=>null. `critical` diferencia bloqueo RED, no desaparece un FAIL no crítico.
2. Requisito obligatorio MISSING/INVALID/UNKNOWN/MODEL_INAPPLICABLE/COMPUTATION_ERROR/UNCALIBRATED => evidencia INCOMPLETE y elegibilidad=false. NOT_APPLICABLE solo desde perfil justificado; denominar aplicables antes del cálculo, sin diluir por métricas opcionales.
3. FAIL crítico obligatorio/implicado en datos usados => RED y diagnóstico aguas abajo. Fallo en registro excluido por supersesión válida no bloquea su sustituto, pero se conserva historial/cause.
4. WARN/FAIL obligatorio válido bloquea elegibilidad hasta resolución válida; no se borra por `k_warn`. Advertencias opcionales permanecen visibles y requieren revisión humana cuando el perfil lo exige. Una aceptación manual nunca reescribe medición/flags como PASS.
5. Elegibilidad es verdadera únicamente con requisitos aplicables obligatorios satisfechos, calibración/hardware/formato dentro del alcance y ausencia de bloqueo en los datos efectivamente usados. Métricas opcionales no cambian un requisito satisfecho por cantidad.
6. Agregar por cobertura del objetivo y registros seleccionados, no peor registro histórico ni promedio de scores. Supersesión requiere misma geometría/componente/config comparable, soporte y causa resuelta; mantener original, sustituto y decisión.
7. Verificar salvedades/responsable/alcance antes de guardar decisión ACCEPTED con advertencias. Sin ello exportar diagnóstico, nunca ocultarlo. La UI no modifica elegibilidad científica.

Acciones con condición y rango: reacoplar/revisar receptor con anomalía, fuente/stack según modelo válido, offset/apertura bajo escenario cuantificado, validar clock/geometría, cambiar estrategia/técnica si objetivo fuera de alcance. No recomendar «aumentar frecuencia» para resolver aliasing a dx fijo; limitar banda/reducir dx o cambiar diseño. Fuente de menor frecuencia tampoco demuestra profundidad sin banda observada.

- **V-E6-1:** tabla exhaustiva de quality/evidence/eligible por requisitos —incluye FAIL no crítico, NA real y MISSING crítico— coincide con especificación.
- **V-E6-2:** empeorar evidencia usada nunca mejora elegibilidad/veredicto; agregar opcionales no diluye faltantes; selección/supersesión explícita es cambio de inputs, no excepción a monotonicidad.
- **V-E6-3:** integridad de acciones, unidades y supuestos; stacks4,SNR6→12dB producen16 bajo independencia; abstención si no aplica.
- **V-E6-4:** fallo crítico en datos seleccionados bloquea decisión pese a downstream PASS; gráficos diagnósticos con validez heredada explícita.
- **V-E6-5:** diagnóstico amarillo siempre exportable; aceptación con advertencias exige bitácora, responsable y alcance y conserva WARN.
- **V-E6-6:** repetición válida sustituye requisito fallido sin borrar original; disparo/métrica obligatoria ausente no se cubre con registros irrelevantes verdes.

## E7 — Interfaz

Seis vistas: sismograma/picks/estado canal; imagen I y espectro de amplitud/bandas; t–x/reciprocidad; cobertura/resolución; requisitos/acciones/estado de evidencia; comparación/selección de réplicas. Mostrar motivos/soporte/incertidumbre, versión de calibración y si resultado es diagnóstico. Evitar sello «CERTIFICADO» por simple color verde.

Trabajadores cancelables; archivo entrante se procesa tras estabilidad de escritura y se invalida caché cuando cambian datos/config/código/calibración. Vista puede mostrar resultado parcial con requisitos pendientes, sin verde definitivo. Plot decimado no altera datos analizados.

- **V-E7-1:** smoke offscreen con datos válidos/corruptos/ausentes; seis paneles y estados explícitos.
- **V-E7-2:** ninguna lógica numérica en UI ni import inverso core→UI; la UI no fuerza aceptación.
- **V-E7-3:** pantalla1366×768 y96×32768 muestras, interacción/zoom objetivo>20fps con decimación; no confundir tiempo de pintura con latencia analítica.

## E8 — Reportes e integridad

JSON-Schema condicionado por técnica, schema_version/spec/calibration; PDF1–2 páginas de síntesis con anexos si necesarios. Datos, procedencia, máscaras, requisitos no satisfechos, barras/bandas, selección/supersesión, alcance y limitaciones. Reporte TRS no exige sigma_c MASW. Reporte de ingesta fallida no necesita geometría falsa.

Digest científico canónico incluye datos efectivamente usados, config, algoritmo, calibración, requisitos, métricas/banderas y selección. Excluir timestamps/orden de presentación del digest científico; digest de archivo final puede diferir. Hash contra referencia confiable detecta cambios; hash editable junto al JSON no autentica autoridad. Si se exige autenticidad, especificar firma/registro confiable aparte.

Generador recomputa elegibilidad desde evidencia y manifiesto de confianza —no flags UI—; payload editado y rehasheado no basta. Cambios legítimos de config necesitan versión/registro de calibración coherentes; un hash nuevo no implica por sí solo infracción.

- **V-E8-1:** mismos datos/config/código/calibración producen digest científico idéntico; metadatos volátiles separados.
- **V-E8-2:** esquema rechaza campos científicos requeridos ausentes y permite diagnósticos TRS/MASW/ingesta conforme al alcance.
- **V-E8-3:** flags desde UI/JSON editado aunque se recalcule hash no habilitan aceptación si falta evidencia/requisitos válidos; modelo de confianza probado.
- **V-E8-4:** cambios autorizados/config/calibración, máscaras y supersesión quedan en provenance/digest; exportación diagnóstica no se confunde con aceptación humana.

## E9 — V&V y calibración de perfiles

Antes de ajustar umbrales, fijar protocolo, poblaciones/estratos, independencia, split por sitio/familia, estimandos, potencia, mínimos por clase e intervalos. Calibración y holdout disjuntos por sitio y origen, no solo semillas. Holdout no se usa para elegir umbrales; si se cambia diseño, crear nuevo holdout.

Corpus inicial≥2000 registros (≥1000 por técnica) no garantiza tamaño por fallo. Metas iniciales recall severo≥0.95/FPR limpios≤0.05/acuerdo≥0.90; evaluar denominadores y CI por estrato, incluida abstención y cobertura de intervalos. Etiquetas proceden del objetivo/verdad independiente, no del mismo umbral del detector. Calibrar sensibilidad/model mismatch y fallas combinadas.

Datos reales: al menos10 sitios para piloto, no prueba de tasa5 %. La tasa de falsos PASS se calcula entre casos realmente inaceptables; agrupar por sitio, especialistas ciegos, adjudicación y error de referencia. Downhole/perforación/inversión independiente aportan evidencia con sus propios límites; norma y edición del proyecto se verifican separadamente.

Con cero errores en n casos inaceptables independientes, límite binomial unilateral95 % `1-0.05^(1/n)`: n10 da25.89 %, n≥59 baja a≤5 %. No convertir59 disparos del mismo sitio en59 sitios independientes. Para sitios agrupados diseñar análisis/potencia adecuados; hay que medir, no imponer receta universal.

- **V-E9-1:** corpus independiente con metas/CI predefinidos, distribución de fallas y matriz de confusión por técnica/estrato; distinguir falso PASS y abstención.
- **V-E9-2:** sensibilidad de umbrales ±50 % en calibración; variación±10 %/cambio≤5 % es hipótesis del corpus, no garantía universal. Fijar operating point antes de holdout.
- **V-E9-3:** piloto real y V&V posterior por tamaño/potencia necesarios; evidencia estadística para falso PASS≤5 % con95 % unilateral, concordancia objetivo≥85 % y acuerdo de expertos documentado.
- **V-E9-4:** rendimiento≤60 s/disparo y≤4GB medido offline por perfiles coherentes, primera/caché y por tendido. Hardware, threads, dependencias y dataset fijados antes del benchmark.
- **V-E9-5:** fuzz10000 y corrupción de forma/unidades/metadata/archivos en escritura: errores tipados o diagnóstico inválido, nunca PASS ni excepción no controlada.
- **V-E9-6:** formatos/endian reconocidos y cuantización comparable conservan resultado dentro tolerancia dimensional/representación, no identidad arbitraria para inputs físicamente distintos.
- **V-E9-7:** release elegible solo para combinación objetivo/técnica/formato/instrumentación/población validada; perfil nuevo o fuera de dominio bloquea elegibilidad y preserva diagnóstico.

Gate G9 incluye registro de calibración completo por todas las métricas/requisitos operativos del perfil y V&V ingenieril Vs30 si ese perfil se habilita. Pruebas sintéticas no lo sustituyen.

## E10 — Empaquetado y operación

Portable Windows/Linux por plataforma validada, instalación offline, configuraciones versionadas y carpeta vigilada sin leer archivo parcial. Manual de campo, limitaciones/estado de evidencia, recuperación/cancelación y trazabilidad. Datos de usuario no se borran al actualizar.

- **V-E10-1:** instalación en máquina limpia sin Python/red, smoke≤5min según hardware fijado; depende de G9 del perfil distribuido.
- **V-E10-2:** actualización config/calibración sin recompilar, migración y caché correcta, rechazo de esquema incompatible; regresión con datos/perfiles validables.

Release `demo-0.1`: diagnóstico explícito y requisitos no validados visibles; puede integrar UI antes de completar G9 solo como rama de demo no elegible, sin declarar gates finales aprobados. Release operativa `v1.0`: G0–G10 PASSED para alcance publicado. No fijar plazo de calibración sin corpus real/hardware/instrumentación.

## E11 — Extensiones

MASW pasivo/ReMi, SH/Love, 2D/3D ampliado y adquisición adaptativa requieren especificación y validación propias. La onda completa/Green **mínima necesaria para V-E3-8/E5-10 no se posterga a E11**. Modelado de producción más amplio puede ser extensión. ML asistente explicable sin reemplazar requisitos de evidencia.

## Anexo A — Configuración y perfiles

Perfiles de proyecto: `vs30_sitio` (z_obj30m y media armónica), `cimentacion_estandar` (z_obj15m como propuesta, no decisión confirmada). Geometrías de v1.3 se conservan como escenarios iniciales:48ch×2m y offsets6/12/24/40m, o24ch×2m y offsets6/12/20m. No se declaran certificables por aritmética sola. Equipo/instrumentación final sigue OQ.

Contrato de configuración requerido:

```yaml
schema_version: "1.4"
profile: vs30_sitio
profile_state: DRAFT
calibration_ref: null
project:
  z_obj_m: 30.0
  targets: [vs30]
  required_techniques: [MASW]  # TRS se agrega solo si el objetivo lo exige
  roi_ref: null             # debe definirse para aceptar
acquisition_ref: null        # geometría/instrumentación/tiempos verificados
metrics_registry_ref: null   # registro completo, no operativo hasta existir
validation_manifest_ref: docs/validation_manifest_v1_4.json
decision:
  require_calibration: true
  require_complete_mandatory_evidence: true
  derive_eligibility: true
```

Este ejemplo DRAFT es válido para **planificación incompleta**; el modo de aceptación lo rechaza por referencias faltantes. No es una plantilla operativa completa ni debe completar automáticamente sus nulls.

Cada entrada de registro de métrica contiene: ID, unidad, soporte/técnica, applicability rule, mandatory/critical por requisito, estimator/window refs, direction, warn/fail/boundaries —o regla binaria—, incertidumbre, manejo de desconocidos, acción, calibration ref/state y dominio. Debe cubrir todas las métricas invocadas por el perfil; clave/estimador desconocido o umbral sin dirección se rechaza. Validación teórica REQUIRED no sustituye calibración empírica REQUIRED.

Valores iniciales heredados únicamente como candidatos de laboratorio: phi1e-4/1e-3 con rails conocidos; logMAD3.5; repeatability0.85/0.6; jitter0.25msTRS/1msMASW; COV repetibilidad0.05/0.10; tol posición0.1m; Nyquist margin0.8. Ventanas/umbrales SNR/coverage/modalidad/coherencia deben especificarse y calibrarse juntos. Retirados como reglas automáticas: clipping desde máximo observado, polaridad cruda rho<-0.3, NACD=x1/lambda, sigma=FWHM/2.355, z_max físico del geófono y NA crítico tolerado por porcentaje.

## Anexo B — Requisitos y Definition of Done

Catálogo de pruebas del manifiesto:100 IDs, sin omisiones. IDs previos conservados con significado corregido; tests afectados se reimplementan contra esta especificación, no se declaran cumplidos por evidencia v1.3. Nuevos IDs:V-E0-9/10,V-E3-8,V-E5-21/22,V-E6-6,V-E8-4,V-E9-7. Un ID compartido por varios gates representa una sola obligación/version de prueba.

Requisitos funcionales a descomponer antes de E0: IO/formato-geometría-tiempo; QC/ventanas-canales-ruido-instrumento; SYN/referencia-independencia-dominio; TRS/onset-reciprocidad-cobertura-modelo; MASW/resolución-banda-modo-incertidumbre-objetivo; DEC/completitud-agregación-supersesión; UI/diagnóstico; RPT/procedencia-confianza; NFR/rendimiento-offline. Cada requisito individual tendrá contrato, datos necesarios y mapeo tests; no inventar REQ numerados como si estuvieran definidos.

DoD: gates y cobertura por alcance; core/qc/trs/masw/decision≥85 % líneas y io≥90 %, tipos strict/ruff; toda métrica operativa y requisito con evidencia vigente; sin skips obligatorios; docs de calibración, V&V/CI, límites de aplicabilidad y release; decisiones abiertas sin efecto operativo no resueltas ocultas. La cobertura de líneas no acredita validez física por sí sola.

## Anexo C — Fuentes y estado documental

La auditoría histórica contiene derivaciones y enlaces primarios por hallazgo. Revisión1.4 usa esas referencias y sus límites de acceso: no afirma lectura integral de normas de pago ni conformidad normativa. Fuentes matemáticas/numéricas siguen diferenciadas de evidencia experimental.

Los errores teóricos/documentales se corrigen aquí. Calibración cercana, intervalos estadísticos, identidad modal difícil, resolución/precisión Vs30, ruido real, atribución de fallas, rendimiento y eficacia de operación permanecen por comprobar en los gates correspondientes. El [registro de revisión](docs/revision_v1_4.md) conserva esta distinción.

## Anexo D — Refuerzos MASW-R1

Forma parte de esta especificación el [anexo D desarrollado en la revisión MASW-R1](docs/masw_review_2026_10_12.md#anexo-d-normativo--contratos-físicos-y-estadísticos): D.1 forward/dominio; D.2 velocidad aparente e identidad modal; D.3 covarianza y unión; D.4 sensibilidad/resolución/incertidumbre; D.5 Vs30 y modelos compatibles; D.6 fuente/campo cercano/atenuación/lateralidad; D.7 obligaciones; D.8 migración/evidencia.

No se adoptan como reglas universales: determinante menor que 1e-10, profundidad λ/3, corte kr>2π, anchura de resolución menor que z_obj/2, identidad M0 por continuidad/energía ni prueba de unicidad por un catálogo finito. La asíntota Rayleigh aplicable es cR del material, no Vs. Ninguna de estas correcciones habilita nuevos umbrales operativos.
