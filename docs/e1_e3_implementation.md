# Ingesta y sintéticos de referencia

La ejecución conjunta se realiza con `python tools/check_foundation.py`. Guarda `evidence/e1_e3/execution.json`, estados G0/G1/G3 y evidencia por ID, incluida la comparación numérica y sus estudios de convergencia. Los resultados de E0 en `evidence/e0` se conservan como ejecución histórica; el estado vigente tras ampliar el código se consulta en la ejecución conjunta. El manifiesto del diseño no se autoactualiza a PASSED.

## Reproducción

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-win-py312.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe tools/check_foundation.py
.\.venv\Scripts\python.exe -m geoqc inspect ruta\disparo.sgy --sidecar ruta\disparo.sgy.json
```

El lock es de versiones para Windows/CPython 3.12.3 y se amplió con dependencias transitivas y referencias externas. Otro sistema requiere ejecutar las comprobaciones antes de reutilizar estados. ObsPy 1.4.2 no importaba con setuptools 82 por `pkg_resources`; se reemplazó dentro de `.venv` por ObsPy 1.5.1. NumPy/SciPy usados en la auditoría se conservaron. disba puede compilar kernels al primer uso; no se confunde esa latencia con rendimiento de un QC de campo.

## Alcance de ingesta

Habilitados: SEG-Y rev0 IBM32, rev1 IBM32/IEEE32, ambos endians reconocidos; cabeceras extendidas de conteo conocido. SEG-2 rev1 códigos int16/int32/float32/float64 (1/2/4/5), endians y terminadores declarados. miniSEED es opcional en el plan y no está habilitado; tampoco SEG-D, SEG-Y rev2/2.1, SEG-2 código3 ni cabeceras SEG-Y de conteo −1. Se rechazan explícitamente. Un PASS de G1 se limita a estos formatos/variantes.

El sidecar JSON `IngestContext` requiere adquisición con receptores físicos, onda/componente/fuente, unidad de amplitud explícita, precedencia de geometría y convención temporal con procedencia. `geometry_policy=HEADER` requiere coordenadas lineales, measurement_system reconocido, CRS e incertidumbre de cabecera declarados; `SIDECAR` requiere Geometry SI completo. No se usa la secuencia de trazas como ID físico. Instrumento/ganancia/calibración/stack desconocidos siguen desconocidos.

SEG-Y: escalares positivos multiplican, negativos dividen y cero equivale a uno; feet se convierte por 0.3048. z es elevación; fuente enterrada usa elevación superficial menos profundidad de fuente. dt son microsegundos, DELAY milisegundos con times_scalar en rev1. `SOURCE_INITIATION_VERIFIED` significa que el proyecto verificó que su trigger cero representa iniciación física de la fuente; no se corrige LagB suponiendo otro trigger. `SIDECAR_AUTHORITATIVE` usa t0 por canal explícito. SEG-2 sin DELAY necesita esa alternativa; no se inventa t0=0. Los campos brutos se conservan para analizar otros convenios de equipo. Estas conversiones se basan en los estándares [SEG-Y rev1](https://seg.org/wp-content/uploads/2025/11/seg_y_rev1.pdf) y [SEG-2](https://seg.org/wp-content/uploads/2025/11/seg_2.pdf).

Se conservan headers brutos hex, campos interpretados, contenido del sidecar y hashes de ambos archivos. SHA-256 vincula sidecar y waveform si se declara; no autentica al autor. Muestras no finitas/canales cortos se enmascaran con motivo. CSV exige receiver_id,x_m,y_m,z_m,uncertainty_m y correspondencia explícita. La comparación por RSS presupone incertidumbres independientes por receptor y usa una banda de ±1σ, no un intervalo de confianza ni autoridad automática de CSV/cabecera. La incertidumbre de fuente no está definida en el contrato inicial: su desplazamiento se reporta nominalmente, sin intervalo calibrado.

La exportación crea archivos nuevos, con cuantización dt/coordenadas/delay y cota de medio ULP por traza para IBM/IEEE. IBM no representa NaN/Inf; IEEE32 preserva faltantes bajo máscara/sidecar. Un archivo exportado no acredita adquisición aceptable ni reexporta sin cambios cada header del formato original.

## Referencias físicas y dominio

TRS: primera llegada es mínimo de ramas físicamente accesibles, con x_critical distinto de x_cross. Gradiente usa `2 asinh(g r/(2 sqrt(vs vr)))/g`, equivalente a acosh y estable al tender g a cero. La referencia FMM resuelve el eikonal cartesiano de primer orden con superficie/dominio explícitos. Los resultados de malla 0.5/0.25/0.125 m y dominio ampliado se registran: no se declara precisión de malla a partir de una sola discretización.

Dispersión: disba 0.7.0 usa Dunkin, port de CPS/surf96. La alternativa implementada aquí discretiza solo z, integra exactamente elementos lineales y resuelve `K(k)u=ω²M u`; k se ajusta a la frecuencia objetivo. No llama disba ni usa su ecuación secular. Superficie libre natural, base Dirichlet y límites materiales conforme a la malla. Admite la rama fundamental ligada al semiespacio; modos superiores/leaky y seguimiento de modos cruzados no están habilitados. La formulación de elementos finitos para ondas Rayleigh se describe en [Haney y Tsai, 2017](https://doi.org/10.1190/geo2016-0397.1); el [origen de disba](https://github.com/keurfonluu/disba) identifica su referencia CPS.

El contraste usa tres modelos en SI (h,Vp,Vs,rho):

| Modelo | Capas, última h=0 |
|---|---|
| Dos capas | (5,400,200,1800); (0,800,400,2000) |
| Gradación | (3,360,180,1700); (8,600,300,1900); (0,1000,500,2100) |
| Vs invertido | (4,700,350,1900); (6,400,200,1800); (0,1000,500,2100) |

Se comparan siete frecuencias logarítmicas de 4 a 40 Hz, tolerancia relativa 0.5 %, mallas de 20/40 puntos por escala de decaimiento y semiespacio truncado a 12/16/22 escalas 1/k. FEM homogéneo también converge hacia la referencia Rayleigh de E0. No se ocultan puntos faltantes de disba. El límite baja/alta frecuencia se prueba en el modelo de dos capas pertinente con una secuencia de frecuencias, sin atribuir esas asíntotas a cualquier inversión.

La suma modal de campo lejano usa IFFT conjugada/real y compara ventanas extendidas; si no converge o el retardo excede el presupuesto, falla explícitamente. Banda finita y aproximación de amplitud/atenuación quedan documentadas. El modelo no es un Green completo, no representa interferencia de ondas de cuerpo y no valida V-E3-8 ni criterios cercanos de G5. Las señales con banda limitada tampoco se usan como verdad causal de onset.

Ricker bilateral sirve para espectro/Parseval. El pulso causal es cero antes del onset analítico; se conserva el primer sample no nulo y la respuesta causal conocida. El ruido se escala por energías sin DC de la ventana suministrada, con modelos/semilla explícitos. Doce inyectores registran perturbaciones y combinaciones; shifts enteros usan copia exacta, fraccionarios interpolación lineal sin wrap. Ninguno promete que el detector pueda identificar la causa en datos reales.

Los [requisitos de esta etapa](requirements_e1_e3.md) fijan contratos y obligaciones. G2 será el siguiente gate del grafo después de G1/G3; calibración G9 y las decisiones del proyecto permanecen pendientes.
