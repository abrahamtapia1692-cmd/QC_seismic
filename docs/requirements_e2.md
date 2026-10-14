# E2 — QC común: protocolo sintético registrado

Fecha: 2026-10-05. Especificación vigente: SDD v1.4, V-E2-1..10.
Este protocolo fija experimentos antes de ejecutar G2. Sus umbrales son candidatos
diagnósticos; no acredita calibración de campo G9.

| Obligación | Experimento y dominio | Criterio |
|---|---|---|
| V-E2-1 | offsets 51/134 m, grupo 80 m/s, pulso 0.3 s, dt 0.5 ms | presupuestos 0.9375/1.975 s; banda máxima 800 Hz |
| V-E2-2 | 24 canales, k=1..4 muertos, 250 realizaciones limpias con modelo de atenuación/gain y DC; rama MAD cero | sensibilidad muertos 1; FPR por realización ≤0.02, Wilson 95% y denominador |
| V-E2-3 | rails ±1, ganancia explícita, máscara, seno/plateaus cuantizados, stacks RAW/MEAN/SUM/UNKNOWN | fracción exacta y fronteras inclusivas 1e-4/1e-3; agregados abstienen |
| V-E2-4 | 0/5/10/20/30 dB; ruido blanco 2048 y 8192 muestras, AR(1) rho=0.6 con 8192; 500 realizaciones por estrato | MAE≤1.5 dB y abs(sesgo)≤1 dB para ≥5; censura registrada a 0 dB; CI de media y PSD aparte |
| V-E2-5 | red 50/60 Hz, seno amplitud 0.5, ruido sigma 0.05, 20 s/dt 1 ms, 100 fases independientes por red | detección y error ≤0.1 Hz; control de 0.1 s abstiene |
| V-E2-6 | onda periódica lambda=3dx; réplicas transitorias de banda conocida e inversión de signo; amplitud ×0.2 | periodicidad abstiene; signo relativo identificable; anomalía sin causa única |
| V-E2-7 | pulso gaussiano modulado 40 Hz/sigma 0.025 s, registro 1.024 s, dt 1 ms, banda 10..100 Hz, búsqueda ±10 ms, señal sin ruido | 201 delays analíticos en ±2.4dt; error máximo ≤0.05dt; fuera de banda/comparabilidad abstiene |
| V-E2-8 | seno limpio con ruido blanco independiente, N=1/2/4/8/16, 200 realizaciones de 4096 muestras | pendiente vs 10log10N entre 0.85 y 1.15 con CI 95%; ruido común rompe predicción |
| V-E2-9 | complejo nominal contra ecuación diferencial de segundo orden; fn 4.5/10 Hz; damping 0.7/0.4 | fase/módulo; respuesta bajo fn no nula; referencia nominal no acredita cadena real |
| V-E2-10 | 1200 realizaciones independientes, 12 clases: limpio, muerto, constante, clip, hum, ruido, signo, delay, amplitud, combinación, dt ambiguo, geometría ambigua | recall≥0.95/FPR≤0.05 por falla identificable, Wilson 95%; dt/geometría sin referencia quedan no identificables |

Semillas PCG64 fijas por experimento. Unidades estadísticas: realización sintética
independiente; para SNR una pareja de ventanas independientes. No se interpreta
como población de sitios. Intervalos Wilson de proporciones y t de medias/regresión.
Las metas se aplican a estimaciones puntuales, y los intervalos se publican para
mostrar la incertidumbre y el tamaño de muestra.

Corpus: las ocho etiquetas identificables describen diagnósticos, no causas
exclusivas. Hum también constituye ruido/SNR bajo. La clase combinada tiene un
canal muerto y clipping en otros canales; todos respetan los rails ADC declarados.
Se evalúa clip en el canal 1 de esa clase y los demás diagnósticos en el canal 0.
Amplitud se evalúa solo en transitorios comparables: limpio, signo, delay, amplitud
y metadatos ambiguos; constantes, clipping, hum/ruido y combinaciones invalidan ese
modelo. Sus denominadores propios se publican, sin contar esos casos como aciertos.

Contrato: `[start_s,end_s)` relativo al trigger de Shot, sin comprimir máscaras.
Estadísticas de amplitud usan muestras válidas; espectros y lag exigen ventanas
completas. DC se elimina por ventana. Welch usa Hann, overlap 50%, density y la
misma longitud de segmento en ruido/señal; resta neta truncada a cero con máscara.
DOF=2K es cota superior, no CI efectivo bajo overlap. No se inventa un SNR desde
100 ms pretrigger ni una precisión espectral por padding.

Rails ADC se convierten mediante `rail_scale_to_data` explícito; un stack agregado
no demuestra ausencia de clipping en réplicas. Repetición requiere misma fuente,
componente/banda y adquisición comparable. Un lag no identifica causalmente trigger.
Normalización de amplitud exige modelo/gain externo; no ajusta automáticamente
propagación para ocultar anomalías. Sin referencia, dt plausible no es identificable.
