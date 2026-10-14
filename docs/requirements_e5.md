# Protocolo científico E5 v1.4

**Suplemento 2026-10-12:** este protocolo base se conserva como antecedente de la ejecución E5. Los [contratos MASW-R1](masw_review_2026_10_12.md) y [ocho obligaciones RM](validation_masw_r1.json) requieren protocolos y evidencia adicionales antes del cierre ampliado; ninguna se aprueba por el texto o por una ejecución anterior. Nuevas tolerancias/poblaciones se fijan antes de ejecutar, sin cambiar las de este registro para lograr aprobación.

Se registra antes de ejecutar las pruebas. E5 es diagnóstico en dominios sintéticos,
sin aceptación de campo ni perfiles G9. No se modifican los umbrales usando holdout.

- Transformador: Fourier temporal exp(-i omega t), propagación exp(-ikx), dirección
  ±1; 24 receptores dx=2 m, bin exacto 5 Hz, c=100 m/s. Pesos no negativos,
  soporte explícito y exclusión por energía. Ventanas comunes, muting por canal,
  kernel real, referencias f-k y tau-p con rejillas convergidas. Tolerancia caso
  plano 1e-6; fase común controlada 1e-3 rad; referencias mediana≤2%.
- Resolución: raíces del kernel finito, FWHM amplitud y potencia separados,
  lambda/(N dx)=0.25/0.5/1, conversión exacta a c; no sigma desde FWHM.
  Aliases firmados lambda=1.5dx y 3dx, huecos y arreglo irregular.
- Curvas: modelos normal/inversión/contraste de E3, f=8..32 Hz; fuentes modales
  complejas con propagación independiente del transformador, SNR20/10 dB;
  objetivos RMS 3/6% en banda observable. Modos separados, superpuestos y ausentes;
  identidad aparente sin evidencia externa. DP penaliza dc/df en unidades declaradas.
- Precisión: 1000 train +1000 holdout por SNR20/10, semillas 6520/6510 y 7520/7510,
  ruido complejo circular independiente en el dominio espectral declarado;
  f=[8,16,32], N24, dx2, c=200, rejilla q±0.008 paso 0.00005 m^-1.
  Intervalos empíricos de error, sesgo y covarianza entre frecuencias; cobertura
  95% objetivo ±0.025 con Wilson. Apertura/N/SNR evaluados como factores, no ley universal.
- Nula: Kluyver integrado por Gauss-Legendre compuesto, corte100/200, orden32/64;
  N12/24/48 y ≥2 millones MC por N, semillas 812/824/848. Cuantiles cola0.0005
  a±0.005; comparación con CI binomial/multiplicidad y error de cuadratura.
  Contraejemplo cola N12,a=0.3167508. Máximo de rejilla con ruido coloreado y
  correlacionado: 2000 train/4000 holdout, semillas882/883, alpha0.05,
  Wilson compatible con alpha; el soporte y la rejilla son parte de calibración.
- Campo cercano: Green axisimétrico de semiespacio elástico homogéneo, fuente
  normal gaussiana finita en superficie, componente Z, ondas P/S/R y superficie
  libre; integral Hankel espectral independiente del phase-shift. No valida
  estratificación ni respuesta no declarada. Comparar Simpson uniforme y
  cuadratura adaptativa independiente, refinamiento dk y límite kmax, amortiguamiento
  causal explícito. Sesgo numérico de velocidad≤0.2%, menor que sesgo físico medido.
  Límite lejano contra cR secular; calibración/holdout por fuente y modelo distintos.
  Ratios cercanos son atributos; objetivos5/2% evaluados, nunca preset operativo.
- Sensibilidad/Vs30: derivadas de log c respecto log Vs por capa; convergencia
  de incremento y partición vertical; sensibilidad distinta de resolución.
  Vs30 con recorte exacto30 m, falta de profundidad no se extrapola. Ensambles
  discretos independientes con referencias FEM E3 para tres familias, curvas de
  alta/baja banda, modelos alternativos, errores/sesgo/CI y objetivo±15% sintético.
  Corpus300, 100 por familia/categoría, etiquetas por error real y evidencia modal,
  aceptación prohibida con banda/confianza/identidad/requisito faltante.
- Bandas: 8..32 Hz exactamente2 octavas; huecos, modos y soporte no se fusionan.
  Repeatability se calcula solo en solape compatible; precisión y dispersión entre
  disparos separadas. Tráfico coherente significativo sin evidencia de evento no acepta.

Fuentes primarias: [disba](https://keurfonluu.github.io/disba/),
[Green de semiespacio](https://link.springer.com/article/10.1186/s40623-023-01780-0),
[admitancia de Lamb](https://www.sciencedirect.com/science/article/pii/S0020722526000844).
La fórmula de admitancia se deriva también de potenciales P/S y tracciones libres;
las pruebas físicas documentan el alcance que realmente cubren.

Control adicional de integración (registrado antes de ejecutarlo): 1000 train y
1000 holdout por SNR10/20, semillas9500+SNR/10500+SNR. Waveform real multisinusoidal
con ruido complejo en bins8/16/32 Hz, N24/dx2/dt1ms/T2s, c200, rejilla150..250 paso1,
ventana rectangular, DP penalty0. Se ejercita toda la cadena CLI/domain usando
intervalos calibrados y cobertura95% ±0.025; no transfiere calibración desde la
rejilla q del experimento espectral anterior.

Controles adicionales de resolución: bloques verticales5/2.5m hasta60m más
semiespacio explícito; derivadas logc/logVs, densidad normalizada por espesor,
integral/máscara ROI30m y masa exterior. Cambio de fracción ROI≤0.02. DP:
rejillas2/1/0.5m/s y penalizaciones0/0.02/100, curva independiente300→190m/s,
documentar sensibilidad a prior fuerte. Filtro común Butterworth causal con4s
de historia y transferencia conocida; error de fase residual≤1e-3rad.
