# E4 — protocolo de TRS sintético

Fecha: 2026-10-05. SDD v1.4, V-E4-1..21. Este documento registra experimentos antes
de ejecutar las pruebas. G4 es validación del dominio declarado, sin aceptación G9.

Picking: dt=0.25 ms, registro -25..175 ms, señal causal H(u) exp(-u/40 ms)
cos(2π80u), onsets continuos uniformes 35..80 ms, sin filtro fase cero. SNR AC
15/20/30 dB en primeros 25 ms después del onset, ruido iid gaussiano independiente.
STA=2 ms contra LTA de ruido externo de 20 ms; trigger ratio=8; refinamiento AIC
[-12,+25] ms; segmentos≥8, ddof=0 y piso relativo 1e-8. Este pulso con salto de
amplitud tiene onset identificable; no representa cualquier fuente/instrumento.
El pulso suave de E3 y bursts/episodios ambiguos son controles fuera del dominio.

Calibración: 2000 realizaciones train por SNR, semillas 4415/4420/4430; holdout
2000/2000/2000, semillas 5415/5420/5430, total 6000 picks. Bias/sigma e intervalos
empíricos 68/95% provienen exclusivamente de train. La cobertura holdout se evalúa
por estrato, con Wilson 95%. Criterio de equivalencia registrado: abs(cobertura
observada-nominal)≤0.03 (68%) / 0.02 (95%); no se ajusta usando holdout. Sesgo y
errores se publican; mediana error≤dt/P95≤3dt para SNR≥15; fracción confiada fuera
de 3sigma≤0.02. Calibración solo sintética, con coincidencia de dt/protocolo/dominio.

Reciprocidad: 10000 realizaciones por rho=0/0.6, sigma AB=0.3 ms/BA=0.4 ms.
Orientación A→B menos B→A, sigma cero determinista; error 0.5 m/1500 m/s bajo
tolerancia 1 ms; efectos 0.333/2 ms y potencia gaussiana bilateral alpha=0.05.
No se atribuyen causas únicas ni se eleva tolerancia según sigma.

Tiempo-distancia: offsets 1..120 m, ≥5 puntos por rama; modelos 300/1500,h=5;
300/600/1500,h=5/8 y caso oculto h=5/0.5. K=1/2/3 continuo: p=2K+1 cuando se
estima ruido, p=2K con sigmas conocidas. Piso varianza=1e-16 s²; likelihood
gaussiana explícita; discontinuidad/robustez no heredan ese BIC. Recuperación de
dos capas con ruido 20 μs: V≤2%, ti≤1 ms,h≤5%; fuera de rama observada abstención.
Outliers: 100 experimentos, 100 offsets 5..100 m, rama única V=1500 m/s,
ruido 0.05 ms, 10% errores aleatorios ±20..40 ms, rechazo 6sigma; recall≥0.95,
sesgo relativo de pendiente≤1%, Wilson y denominadores explícitos.

Solver: FMM propio cartesiano de primer orden. Convergencia suave con frente plano
en v(x)=1000+50x m/s (sin singularidad puntual) y refinamiento 1/0.5/0.25 m,
norma L∞ e interior definido, p_obs≥0.9. Fuente puntual/gradiente/interfaz, bordes,
fuente fuera de nodo y horizonte son pruebas separadas frente a tiempos analíticos
y pyGIMLi Dijkstra (secNodes y versión registrados). Presupuesto de tiempo objetivo
0.25 ms se declara por caso; incumplimiento queda explícito, sin ocultarlo en RMS.

Inversión: dos capas horizontales, ROI nominal 0..10 m, offsets 1..120 m,
ruido independiente 0.5 ms, 100 realizaciones, datos analíticos independientes;
evaluar Q, convergencia y error V≤10%. Q media 0.7..1.5, no exigido universalmente
por realización. Protocolo científico max_nfev=80; presupuesto rápido=5 y puede
abstenerse NOT_CONVERGED. Corrupción 5% en observaciones ±5 ms: detectar aumento
de Q y potencia; no exigir aumento si un modelo libre absorbe el error.

Cobertura: Siddon contra slab clipping independiente por rectángulo; 200 rectas,
bordes/vértices y polilíneas. rtol=1e-10,atol=1e-12 m. Bordes internos al lado
positivo, máximo a última celda; conserva solo longitud dentro del dominio.
Hits deduplican IDs físicos, DWS conserva pesos y direcciones móduloπ. Span y
tensor exactos para 0/60/120°, único/vacío/uniforme. Resolución requiere evidencia
independiente de Jacobiano/modelo/ROI: cobertura sola nunca autoriza PASS.

Corpus: 300 escenarios, 100 por recuperable/ambiguo/inaceptable con etiquetas
externas; no habilitan aceptación aunque un diagnóstico aislado pase. Asociación
cobertura/resolución/error: tres familias independientes de sistemas de rayos
rectos en dominio lineal declarado, 100 realizaciones por familia, niveles de
observación/direcciones y ruido fijos; Spearman, bootstrap CI y confusores. La meta
rho≤-0.5 se prueba como hipótesis, no demuestra unicidad ni calibra contra holdout.
Los estados ROI se calculan desde matrices independientes de intersección (rayos
verticales por celda o horizontales degenerados), diagonal R>0.95 y error relativo
de ruido<5%. Asociación: RMSE analítico y observado en 200 réplicas por geometría.

Rendimiento: 24 canales×12 disparos, picking+ajuste por lado+inversión diagnóstica,
primera/caché con hardware/SO/threads registrados. Candidato 25 s; excederlo emite
aviso de rendimiento separado de calidad. No incluye arranque del entorno pyGIMLi
de referencia ni validaciones Monte Carlo offline.
Hardware registrado por WMI: Intel Core i5-9400 2.90 GHz, 6 núcleos/6 threads.
Benchmark en proceso separado con OMP/OPENBLAS/MKL_NUM_THREADS=1; incluye doce
inversiones de tablas temporales independientes con ruido conocido 0.5 ms.
