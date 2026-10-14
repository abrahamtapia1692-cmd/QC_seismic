# E5 — MASW diagnóstico v1.4

**Revisión 2026-10-12:** las capacidades descritas aquí corresponden al alcance base. [MASW-R1](masw_review_2026_10_12.md) identifica límites en confirmación modal, covarianza de unión, clases de incertidumbre y ensambles Vs30. La [primera implementación del suplemento](masw_r1_implementation.md) modifica confirmación/unión y migra el runner; los apartados siguientes conservan la descripción del alcance base. El cierre ampliado sigue pendiente.

Implementa phase-shift firmado, kernel de geometría real, resolución finita,
crestas por programación dinámica, bandas/procedencia, calibración empírica
separada para precisión y significancia, sensibilidad y referencia Vs30 sintética.
Los dominios y criterios previos están en [requirements_e5.md](requirements_e5.md).
G5 es evidencia sintética; aceptación de campo depende de E6/G9 y permanece deshabilitada.

## Reproducir

```powershell
.\.venv\Scripts\python.exe tools/create_masw_demo.py
.\.venv\Scripts\python.exe tools/check_masw.py
.\.venv\Scripts\python.exe tools/plot_masw.py
.\.venv\Scripts\python.exe -m geoqc masw examples/e5/masw_plane.sgy --protocol examples/e5/protocol.json
```

Entorno original CPython3.12/NumPy1.26/SciPy1.15/disba0.7, lock existente conservado.
El runner revalida G0..G5, ruff/formato/mypy y hashes antes/después; escribe en
subdirectorios únicos de `evidence/masw_r1/runs`, conserva evidencia E4/E5 anterior y usa el entorno pyGIMLi aislado para regresión TRS.
CLI devuelve0 si obtiene diagnóstico y2 por entrada/protocolo inválido.

## Transformador, curvas y bandas

FFT temporal exp(-i omega t), propagación exp(-ikx), steering exp(+i omega d x/c).
`I` es coherencia de fases normalizada por pesos activos, no energía modal.
Direcciones±1 se conservan. Canales sin energía o con ventana incompleta se excluyen
con motivo y soporte por frecuencia. Datos originales inmutables; ventanas comunes
Hann/rectangular, sin remuestreo oculto ni filtro instrumental no declarado.
La implementación inicial exige geometría horizontal along-x y relojes alineados;
frecuencias solicitadas deben ser bins observados. No se borra la onda a340 m/s.

`spatial_kernel` usa posiciones/pesos reales. FWHM de I/I² distintos y conversión
exacta q→c, sin límite finito si cruza q=0. Nyquist solo describe el uniforme;
aliases con signo, huecos y geometría irregular tienen controles separados.
f–k sin normalizar amplitudes y tau–p por interpolación temporal son referencias
con sesgos distintos. Padding no se presenta como ganancia de resolución.

DP minimiza -I+penalty[(dc/df)/slope_scale]²; unidades m/s/Hz. Refinamiento local
parabólico en q para máximos interiores, sin extrapolar bordes. Modos observados
son APPARENT/UNKNOWN; CONFIRMED exige evidencia externa explícita y no prueba
por sí solo suficiencia. El modo más lento y A1/A0 no identifican el fundamental.

Bandas diagnósticas contienen datos observados, máscaras, huecos y soporte.
La CLI deja bandas validadas vacías: SNR neto/response/alias/nearfield/resolución
de sitio no quedan validados por detectar una cresta. `near_offset_ratio` y
`NACD_center` son atributos de receptores activos; no generan banda ni profundidad.
Unión conserva contribuciones, modos, soporte y discrepancias; no interpola huecos.
Compatibilidad independiente-sigma requiere revisar covarianzas compartidas.
Repeatability usa curvas en soporte/modalidad común verificados; no atribuye causa única.

## Precisión y significancia

`CurveCalibration` contiene errores train conjuntos por frecuencia, sesgo,
covarianza e intervalos empíricos invertidos; no deriva sigma desde FWHM.
Compatibilidad exige protocolo/estimador/posición-pesos-receptores/dt/N_active,
frecuencias, dirección y dominio declarados. Cambios o falta de confianza →UNCALIBRATED.
Corrección o intervalo no físico también produce abstención con motivo. Ventanas
sin señal muestran velocidades ausentes y no generan ratios de lambda no observada.
`precision_cov` y `repeatability_cov` son cantidades distintas.

Kluyver usa CDF_R y convierte R=N*S; cuadratura Gauss-Legendre compuesta,
corte/orden refinados y MC2 millones para cada N12/24/48. La cola exp(-Na²)
se conserva solo como aproximación, con contraejemplo explícito.
No reutiliza tablas con N bajos, pesos distintos o fases dependientes.
La API de Kluyver admite únicamente N12/24/48; otros tamaños requieren una
validación numérica propia o calibración empírica compatible.
Bonferroni usa número real de hipótesis de la rejilla; no requiere independencia.

`PeakCalibration` guarda máximos de registros train sobre toda la búsqueda
f/c/d; threshold por rango finito bajo exchangeability del dominio declarado.
Hay holdout coloreado/correlacionado explícito. **No hay corpus de ruido real de
arreglo en este workspace**: la calibración de campo sigue UNCAlIBRATED y no se
transfiere desde ruido sintético. Significancia no identifica evento activo;
tráfico coherente sin evidencia de disparo no habilita aceptación.

## Green independiente de campo cercano

`synth.nearfield` implementa el Green completo axisimétrico homogéneo Z de Lamb:
fuente normal gaussiana finita, superficie libre salvo tracción aplicada, ondas
P/S en cortes de raíz y Rayleigh en el polo. No usa disba ni steering MASW.

Con p=sqrt(k²-kP²),q=sqrt(k²-kS²), D=(2k²-kS²)²-4k²pq,
admitancia=-p*kS²/(mu*D). La integral es ∫admitancia exp[-(ka)²/2]J0(kr)k dk/(2pi).
Convención exp(+i omega t), z hacia abajo, omega complejo con Im<0 y amortiguamiento
registrado; no pretende dar una verdad de onset causal por un espectro bandlimitado.
La fuente multiplica la respuesta, no define una curva impuesta al transformador.

V-E3-8 estudia dk, cola kmax, Simpson frente a quad_vec adaptativo,
tracciones libres/aplicadas, límite estático Boussinesq gaussiano y lejano contra
secular Rayleigh. V-E5-10 usa fuentes/modelos distintos train/holdout y ambos ratios;
error numérico inferior al sesgo cercano medido. Se publican cumplimientos y fallas
de objetivos5/2%, sin convertirlos a límites universales de política.
**Campo cercano estratificado, fuentes arbitrarias y respuesta de campo permanecen
UNCALIBRATED**; esta referencia valida un dominio homogéneo con interferencia P/S/R.

Fórmula contrastada con [admitancia de Lamb](https://www.sciencedirect.com/science/article/pii/S0020722526000844)
y [Green de semiespacio](https://link.springer.com/article/10.1186/s40623-023-01780-0).

## Sensibilidad, Vs30 y límites

Derivadas log c/log Vs por capa, pasos refinados y partición vertical independiente.
Normalización usa magnitudes de derivadas y medida declarada; sensibilidad no es
resolución. La matriz local incluye covarianza y regularización explícitas.
Alternativas con curvas casi iguales y Vs30 distintos conservan no unicidad.
Vs30 recorta espesores exactamente a30 m; perfil finito<30 m no extrapola.

Ensamble discreto con prior uniforme declarado, candidatos disba y verdad FEM
independiente en tres familias. Intervalos del ensamble son condicionales al prior,
sin afirmar cobertura frecuentista universal. Error±15%, sesgo, intervalos y
asociación calidad/error se registran por estrato y bootstrap. El corpus≥300
se etiqueta con objetivo observado/verdad modal y error, no solo geometría.
No valida un perfil operativo Vs30 ni sustituye resolución de sitio/G9.

El siguiente módulo es E6/G6: decisión y acciones. Antes de confiar en salidas
MASW para ese motor, incorporar RM-08/RM-02/RM-03 y conservar los bloqueos del
resto de MASW-R1. Los requisitos reales y dominios fuera de alcance siguen pendientes.
