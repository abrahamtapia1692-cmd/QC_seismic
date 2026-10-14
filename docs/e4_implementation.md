# E4 — TRS en dominio sintético

Requisitos y protocolo: [requirements_e4.md](requirements_e4.md).
Verificación conjunta: `python tools/check_trs.py`; estados G0/G1/G2/G3/G4,
resultados por V-ID, versiones, hashes, denominadores e intervalos en `evidence/e4`.
Se conservan las ejecuciones históricas E0/E1/E3/E2; el manifiesto de diseño no se
promueve automáticamente. [Figura numérica](../evidence/e4/validation.svg).

## Reproducir

El entorno principal sigue usando `requirements-win-py312.lock` (NumPy 1.26.4).
pyGIMLi 1.6.1 necesita NumPy≥2.4 y se ejecuta en otro proceso/entorno, con lock
independiente; no se cambia NumPy del producto.

```powershell
.\.venv\Scripts\python.exe -m venv .venv-gimli
.\.venv-gimli\Scripts\python.exe -m pip install -r requirements-gimli-win-py312.lock
.\.venv\Scripts\python.exe tools/create_trs_demo.py
.\.venv\Scripts\python.exe tools/check_trs.py
.\.venv\Scripts\python.exe tools/plot_trs.py
.\.venv\Scripts\python.exe -m geoqc trs examples/e4/causal_trs.sgy --protocol examples/e4/protocol.json --calibration examples/e4/calibration.json
```

Windows/CPython 3.12 es el entorno ejecutado. La referencia usa
[TravelTimeManager.simulate](https://www.pygimli.org/_modules/pygimli/physics/traveltime/TravelTimeManager/),
Dijkstra y nodos secundarios; FMM GeoQC y pyGIMLi no comparten ecuación de actualización.
El adapter convierte profundidad positiva a elevación y registra versión, malla,
muestreo de velocidad por celda y nodos secundarios. No sustituye el solver si falta
pyGIMLi. El lock aislado fija pgcore 1.6.0, NumPy 2.5.3, setuptools 84 y scooby 0.12.
La opción `include_ray_paths` registra polilíneas Dijkstra mediante `getRayPaths(model)`;
esta API calcula el Jacobiano y se usa solo en la malla de 0.5 m. Un control adicional
verifica los extremos, curvatura en el gradiente y conservación de longitud al
intersectar ese rayo independiente con Siddon (rtol=1e-10).

## Picking y confianza

`PickProtocol` declara ventanas físicas, banda nominal, STA/LTA y refinamiento.
El estimador usa media de ruido externo, energía corta causal y AIC ML ddof=0,
con piso de varianza relativo a escala. No aplica filtro fase cero ni usa curvatura
AIC como sigma. Rechaza huecos, falta de ruido/soporte, bursts aislados, mínimos de
borde y reactivaciones comparables. La banda es dominio nominal, no certificado
de banda de cada traza. Por defecto el onset queda UNCALIBRATED.

`PickCalibration` conserva los errores de train independientes, hash del protocolo,
código/dependencias del estimador, dt y dominio. Bias/sigma y cuantiles empíricos
se calculan sin holdout. Los 6000 picks holdout se reportan por SNR, con Wilson y
errores confiados fuera de 3sigma. Un CALIBRATED se limita al pulso causal con salto,
ruido iid y rango registrados; no es calibración de instrumentos/sitios G9. Fuentes
suaves, fase cero, hum/bursts largos y ruido correlacionado necesitan otro protocolo.
Invertir signo no cambia tiempo ni confirma por sí solo polaridad instrumental.

## Reciprocidad y modelos de tiempo

`reciprocal_pair` exige identidades físicas invertidas, corrige delays explícitos y
propaga covarianza AB/BA. Conserva diferencia operativa, estadística y potencia como
salidas distintas. Sigma cero es determinista; sigma alta no aumenta tolerancia.
Un error de 0.5 m/1500 m/s pasa tolerancia 1 ms. Trigger/clock/geometría/pick aparecen
como causas candidatas, sin atribución exclusiva.

`fit_branches` separa el modelo continuo (K=1..3) y likelihood gaussiana candidata.
Cuenta pendientes, intercepto, quiebres y ruido estimado en BIC; con sigmas conocidas
usa likelihood heterogénea. Discontinuidad y pérdidas robustas quedan MODEL_INAPPLICABLE
para ese BIC. `robust_line` usa Theil-Sen/rechazo explícito y no emite BIC heredado.
`layered_first_times` respeta accesibilidad de ondas refractadas y ramas ocultas.
No infiere número de capas desde K. Espesor requiere dos ramas y modelo horizontal
externo. El equivalente h≈5.2338536 m se calcula desde interceptos sin redondeo.

## Forward, inversión y cobertura

FMM admite frente inicial y fuente subnodo explícitos; fuentes fuera de dominio se
rechazan. Se prueba orden≥0.9 en frente plano suave v(x)=1000+50x, y por separado
fuentes puntuales, gradiente, interfaz, borde y horizonte. En pyGIMLi se estudian
paso y nodos secundarios por separado: sus errores firmados pueden cancelarse;
no se exige monotonicidad ficticia del error absoluto a nodos secundarios fijos.
El presupuesto 0.25 ms se comprueba en los casos registrados, no en cualquier malla.

`invert_two_layer` estima V1,V2,h bajo modelo horizontal/ROI declarado, con sigmas
independientes conocidas y cotas explícitas. Devuelve convergencia, nfev, Q, RMS,
sesgo, residuales, soporte por rama y sensibilidad local. Presupuesto rápido=5;
NOT_CONVERGED no diagnostica adquisición mala. Experimentos offline usan 80.
`normalized_misfit` admite C_d completa definida positiva; singularidad se rechaza.
Q divide por n y no equivale a chi² reducido. Regularización/ajuste flexible pueden
reducir Q sin recuperar verdad. Covarianza de inversión es local/paramétrica, no
prueba de resolución 2D ni de unicidad.

`siddon_segments` conserva longitud por celda para rectas/polilíneas en malla
rectangular 2D; bordes internos al lado positivo, máximo a última celda. DWS guarda
pesos, hits deduplica IDs de observación, span/tensor usan direcciones móduloπ.
La resolución se suministra con referencia independiente; hits/ángulos solos no
emiten PASS. Una máscara ROI puede ser discontinua. Refinar cambia hits por celda;
no se impone normalización invariante H*h/dx. Sensores superficiales en semiespacio
homogéneo no crean cobertura profunda al agregar fuentes off-end.

La asociación cobertura/error se estudia en tres familias lineales de rayos fijos,
con matriz independiente por intersección y ruido conocido. Se publica RMSE esperado
y medido con 200 réplicas por geometría, Spearman/bootstrap y confusores; no se extrapola a rayos dependientes del modelo o
tomografía no lineal de campo. Estados ROI son diagnósticos condicionados.
Los controles PASS/WARN/FAIL usan arreglos de rayos distintos y máscaras calculadas
desde el Jacobiano independiente, diagonal de resolución>0.95 y sigma relativa<5%.
No usan máscaras elegidas desde el estado esperado.

## CLI, rendimiento y alcance

`trs_diagnostics` preserva receptores, lados, onsets originales, corrección temporal
separada, fits, inversión, hashes y requisitos faltantes. `trs` devuelve 0 si logró
el diagnóstico y 2 ante entrada/protocolo inválido. Falta de confianza, reciprocidad,
resolución de sitio, covarianza compartida, capas ocultas o G9 queda explícita.
`eligible_for_acceptance=false` y `operator_decision=PENDING` en todos los casos.

Benchmark 24×12 en proceso separado, primera/caché, BLAS/OMP/MKL=1. Incluye picking,
fits por lado y doce inversiones de tablas independientes con sigma conocida;
excluye Monte Carlo y arranque de referencia. Hardware registrado i5-9400/6 cores,
SO/Python/identificador real en evidencia. Candidato 25 s; excederlo produce aviso
de rendimiento y conserva el estado de calidad.

G4 se limita a estos dominios: no habilita inversión 2D no lineal general, ray tracing
con relieve, calibración instrumental/real ni detector universal de capa oculta.
El siguiente gate es E5/G5 (MASW), que también requiere V-E3-8 de campo cercano
independiente; disponer de curvas disba no satisface esa obligación.
