# SDD — GeoQC-Field: QC de campo para MASW y TRS (Tomografía de Refracción Sísmica)

**Versión:** 1.3 · **Idioma:** ES · **Destinatario principal:** agente de IA ejecutor (con revisión humana en gates)

**Changelog v1.3 (revisión 3):**
- **Nuevo término en `feasibility()` (E0.4):** restricción del geófono, `z_max,geo = c(f_low)/(f_low·κ_z)`, con el cuello de botella explícito. Con el perfil v1.2 (geófono 4.5 Hz, suelo blando `Vs_min=180`) la profundidad alcanzable cae a ≈15 m aunque la geometría diera 32 m. Perfiles del Anexo C actualizados (V-E0-8).
- **Entregado y verificado (34 tests):** `core/physics.py` (+ `synth/modal.py`, `core/evidence.py`) con la solución de Rayleigh de semiespacio. La **cúbica** `ξ³−8ξ²+8(3−2κ²)ξ−16(1−κ²)=0` sustituye a la forma con radicales: `P(0)<0` y `P(1)=1` garantizan el intervalo `[0,1]` y no existe raíz trivial. Forma cerrada exacta para `ν=0.25`: `ξ=2−2/√3`.
- **Errata:** la aproximación de Viktorov **no** cumple "≤ 2e-3 en [0, 0.5]" (error 0.012 en `ν=0`); solo desde `ν≈0.237` (V-E3-4 corregido). Esquema numérico de Kluyver registrado como parte de la evidencia (E5.4b).

**Changelog v1.2 (revisión 2):**
- **Errata V-E3-4:** v1.0 daba `c_R/Vs(ν=0.45)≈0.9674` (imposible: supera el límite ν=0.5 ⇒ 0.95531). La revisión propuso `0.9503`, tampoco coincide con la solución exacta (`0.94896`, verificada con `brentq`). Además `ν=0.30` pasa de `0.9277` a `0.92741`. El test ahora resuelve la ecuación de Rayleigh numéricamente y las constantes son solo respaldo.
- **Inconsistencia config↔objetivo (crítica):** con la config v1.1 (`N=24, dx=2, x1=6, NACD_min=0.5`) `z_max=4.8 m` y `z_obj=30 m` nunca podía certificarse. Nuevo `core/feasibility.py` (E0.4), NACD en dos niveles (verde/ámbar), `x1` como lista multi-offset y perfiles consistentes (Anexo C).
- **V-E5-17 rehecho:** la aproximación Rayleigh `exp(−N a²)` es asintótica y *sobreestima* la cola (a p=1e-3, el cociente empírico/Rayleigh es 0.35, 0.66 y 0.81 para N=12, 24, 48: ni ±10 % ni ±20 % servían). Se usa el cuantil exacto de Kluyver y la aproximación queda como cota conservadora.
- **Notación única de longitudes** (`L_ap`, `L_eff`, `L_total`), `certifiable` propagado al hash del reporte (AP-8), hitos `demo-0.1`/`v1.0`, secciones reordenadas en Anexos A–F.

**Changelog v1.1 (integración de retro L0–L5):**
- **Corrección propia:** el umbral fijo `peak_min: 0.3` de v1.0 quedaba *dentro del ruido* para N≈24 canales; se reemplaza por umbral estadístico derivado de la distribución nula (E5.4b, V-E5-17).
- **Nuevo:** cobertura de rayos por celda (hits) y cobertura angular (E4.4b); ancho de banda coherente en octavas (E5.4b); modo diagnóstico con certificación bloqueada (E6.0); mapeo L0–L5 ↔ etapas (Anexo A); antipatrones (Anexo B); regla de triple test por métrica (§0.11).
- **Ajustado/rechazado:** ver Anexo A.3 (justificación técnica de lo no adoptado tal cual).
**Estado de umbrales:** *iniciales y calibrables* (ver Anexo C y ADR). Ningún umbral numérico de este documento es "verdad normativa"; todos viven en configuración YAML y se calibran contra sintéticos y datos reales.

---

## 0. Protocolo de ejecución para el agente de IA (OBLIGATORIO)

1. **Orden estricto:** ejecutar las etapas E0→E10 en orden. No iniciar una etapa si el *Gate* de la anterior no está en estado `PASSED`.
2. **TDD:** para cada subetapa, primero escribir los tests (IDs `V-*` definidos aquí), verlos fallar, luego implementar.
3. **Prohibido relajar tolerancias** para hacer pasar un test. Si un test falla: (a) diagnosticar, (b) corregir el código, (c) solo si el modelo teórico del test estaba mal, abrir un ADR (`docs/adr/NNNN-*.md`) justificando el cambio con derivación y esperar aprobación humana.
4. **Determinismo:** toda aleatoriedad usa `numpy.random.Generator(PCG64(seed))`; la semilla se registra en la evidencia. Mismos inputs + misma config ⇒ mismos outputs (bit a bit en CPU de referencia, o dentro de `rtol=1e-12`).
5. **Evidencia:** al cerrar cada subetapa, escribir `evidence/<ID>.json` con: `{id, status, metrics, tolerances, seed, git_hash, versions, timestamp}`. Un Gate se cierra solo si todos los JSON de sus subetapas son `PASSED`.
6. **Decisiones abiertas (OQ-*):** usar el valor por defecto indicado, marcarlo en `docs/open_questions.md` y **no** presentarlo como decisión tomada.
7. **Honestidad numérica:** reportar siempre incertidumbre y rango de validez. Nunca emitir un resultado sin su bandera de validez (`valid_band`, `reason`).
8. **Separación estricta:** el núcleo (`core`, `qc_*`, `trs`, `masw`, `decision`) es *headless* y no importa nada de UI.
9. **Evitar el "inverse crime":** los datos sintéticos de validación se generan con un método/malla distintos al usado por el algoritmo bajo prueba (ver V-T-*, V-M-*).
10. **Unidades SI** internamente (m, s, Hz, m/s). Conversión solo en I/O y UI.
11. **Triple test por métrica:** toda métrica con umbrales debe tener al menos tres sintéticos (uno que caiga en verde, uno en ámbar, uno en rojo) más tests de frontera en `umbral ± ε`. Sin ellos, la métrica no puede entrar al semáforo.
12. **Dirección explícita:** cada umbral declara `direction: higher_is_better | lower_is_better` en el YAML (evita semánticas ambiguas tipo "red: 1.0"); el validador de config rechaza umbrales incoherentes con la dirección.


---

## 1. Alcance, supuestos y no-objetivos

### 1.1 Objetivo
Dado un conjunto de registros sísmicos de campo (MASW y/o TRS), emitir **en < 60 s por disparo, offline**, un veredicto `PASS / WARN / FAIL` por registro, por técnica y por tendido, con causa cuantificada y acción correctiva, para decidir si se puede **abandonar el sitio** o se debe **repetir/extender** la adquisición.

### 1.2 Supuestos
- TRS = Tomografía de Refracción Sísmica (OQ-01).
- Fuente activa (martillo/caída de peso/vibrador); geófonos verticales (Rayleigh) para MASW y verticales u horizontales para P (OQ-02).
- Tendido lineal 2D con geometría conocida (cabeceras o CSV).
- Registros multicanal en SEG-2 / SEG-Y / miniSEED (OQ-03).

### 1.3 No-objetivos
- No es un procesamiento final ni una inversión de producción (MASW 1D/2D, tomografía final).
- No sustituye al criterio del geofísico; da alertas cuantificadas.
- No cubre MASW pasivo/ReMi (extensión futura §E11).

### 1.4 Convenciones
- Eje x creciente a lo largo del tendido; fuente en `xs`; offset firmado `x - xs`.
- t=0 = instante del trigger corregido por `delay` de cabecera.
- Dominio de Fourier: `U(f)=∫u(t)e^{-i2πft}dt`.
- **Longitudes del arreglo (notación única, v1.2).** Prohibido usar `L` sin subíndice en código o tests:
  - `L_ap = (N−1)·dx` — apertura física (tiempos de viaje, longitud de tendido TRS).
  - `L_eff = N·dx` — apertura efectiva para resolución en número de onda (`δk≈1/L_eff`).
  - `L_total = x₁ + (N−1)·dx` — de la fuente al receptor más lejano.
  Ejemplo `N=24, dx=2, x₁=6`: `L_ap=46`, `L_eff=48`, `L_total=52` (m). Test `V-E0-7` impide la ambigüedad (análisis estático).
- Ventana de ruido: `[−t_pre, −t_guard]` antes del trigger; ventana de señal: `[t_first_arrival, t_first_arrival + T_sig]`.


---

## 2. Arquitectura y contratos de datos

### 2.1 Estructura del repositorio
```
geoqc/
  core/        models.py  config.py  units.py  errors.py  evidence.py
  io/          readers.py  geometry.py  writers.py
  qc_common/   integrity.py channels.py noise.py repeatability.py timing.py
  synth/       wavelets.py faults.py modal.py eikonal_models.py
  trs/         picking.py reciprocity.py timedist.py coverage.py tomo.py
  masw/        preprocess.py dispersion.py picking.py resolution.py nearfield.py
               repeatability.py uncertainty.py depth.py
  decision/    rules.py actions.py aggregator.py
  report/      pdf.py json_log.py
  ui/          (PySide6 + pyqtgraph; capa delgada)   # OQ-04
tests/{unit,property,synthetic,regression,performance}/
evidence/   docs/adr/   configs/*.yaml
```

### 2.2 Stack (versión mínima, fijar en `pyproject.toml`)
Python ≥3.11 · numpy, scipy · obspy (SEG-2, miniSEED) · segyio · pydantic v2 · pyyaml · pygimli (tomografía) · scikit-fmm (eikonal de referencia, opcional) · disba (dispersión de referencia) · pytest, hypothesis, pytest-benchmark · ruff, mypy `--strict` en `core/` · reportlab/weasyprint (PDF) · PySide6, pyqtgraph.

### 2.3 Modelos de datos (pydantic, inmutables)
```python
class Trace:      data: ndarray[float64]; dt: float; t0: float; channel: int
class Geometry:   xr: ndarray (n_ch,); zr: ndarray; xs: float; zs: float; units="m"
class Shot:       id: str; traces: ndarray (n_ch, n_s); dt: float; geom: Geometry;
                  stack_count: int; meta: dict; source_type: str; gain: float|None
class Metric:     id: str; value: float|None; unit: str; threshold_warn: float;
                  threshold_fail: float; status: Literal["PASS","WARN","FAIL","NA"];
                  critical: bool; message: str; action_ids: list[str]
class QCReport:   scope: Literal["trace","shot","technique","survey"]; metrics: list[Metric];
                  status; evidence_refs; config_hash
```
Invariantes validados al construir: `dt>0`, `n_ch==len(xr)`, sin NaN/Inf (o declarados), `xr` estrictamente monótona (o permutación registrada).

### 2.4 Configuración (YAML, validada por pydantic; hash SHA-256 en cada reporte)
Ver plantilla en Anexo C. Perfiles: `geotecnia_estandar`, `cimentacion_critica`, `exploracion_somera`.


---

## 3. Catálogo de requisitos (trazabilidad)

| ID | Requisito | Etapa |
|---|---|---|
| REQ-IO-1..4 | Lectura/validación de formatos y geometría | E1 |
| REQ-QC-1..10 | QC común (canales, ruido, disparo, estabilidad) | E2 |
| REQ-SYN-1..4 | Generación sintética y de fallas | E3 |
| REQ-TRS-1..8 | Picking, reciprocidad, t–x, cobertura, tomografía rápida | E4 |
| REQ-MSW-1..9 | Dispersión, resolución, campo cercano, repetibilidad, incertidumbre, profundidad | E5 |
| REQ-DEC-1..4 | Semáforo, acciones, agregación | E6 |
| REQ-UI-1..3 / REQ-RPT-1..2 | Interfaz y reportes | E7–E8 |
| REQ-NFR-1..5 | Rendimiento, reproducibilidad, offline, robustez | E9–E10 |

(La tabla completa test↔requisito se mantiene en `docs/traceability.csv`, generada automáticamente a partir de decoradores `@covers("REQ-...")` en los tests.)


---

## E0 — Preparación del proyecto

**E0.1 Esqueleto y herramientas.** Crear estructura §2.1, `pyproject.toml`, `pre-commit` (ruff, mypy), CI local (`make test`).
- **V-E0-1:** `pytest` descubre ≥1 test, `ruff` y `mypy` limpios.

**E0.2 Utilidades transversales.** `evidence.py` (escritura de JSON de evidencia), `config.py` (carga+validación+hash), RNG determinista.
- **V-E0-2:** dos corridas con misma semilla ⇒ arrays idénticos (`np.array_equal`).
- **V-E0-3:** config inválida (umbral warn > fail en métrica "mayor es peor") ⇒ `ConfigError`.

**E0.4 Coherencia objetivo↔geometría (`core/feasibility.py`, v1.2).** Una única función pura `feasibility(cfg) -> FeasibilityReport` calcula, con las fórmulas de E5.4/E5.7 (la UI y E5.7 la **reutilizan**, no la reimplementan):
`L_eff, λ_min, λ_max,green, λ_max,amber, z_max,cert, z_max,prov` y la `L_total` requerida, **más el término del geófono (v1.3)**:
```
z_max,array = α_L · L_eff / κ_z
z_max,nf    = (x₁,max / NACD_nivel) / κ_z                 (nivel = green para cert, amber para prov)
z_max,geo   = c(f_low) / (f_low · κ_z),   f_low = k_g · f_n
z_max,cert  = min(z_max,array, z_max,nf(green), z_max,geo)   ;   bottleneck ∈ {array, nearfield, geophone}
```
`c(f_low)` proviene de `site_prior`: (i) `c_lowfreq_ms` si el proyecto lo da (dispersión previa o `disba` con perfil previo) o (ii) la **cota inferior** `c_R(Vs_min, ν_prior)` calculada con `core.physics.rayleigh_halfspace_velocity` (≈0.93–0.95·Vs_min; es cota inferior solo si Vs crece con la profundidad). Ojo: `f_low` **no es un corte duro**: `|H(f)|=f²/√((f_n²−f²)²+(2h f_n f)²)` con `f_n=4.5, h=0.7` da `|H|=0.714` en `f_n` (−2.9 dB), `0.41` en 3 Hz (−7.8 dB), `0.195` en 2 Hz (−14.2 dB) y `0.111` en 1.5 Hz (−19.1 dB); con corrección instrumental y buen SNR se puede bajar `k_g` (def. conservador 1.0) y eso se decide por ADR, no por defecto.
- **Modo planificación** (`geoqc plan`): si `z_obj > z_max,prov` ⇒ error `InfeasibleProject` con recomendación cuantificada (qué `N·dx` y qué `x₁` hacen falta); si `z_max,cert < z_obj ≤ z_max,prov` ⇒ aviso "solo certificable como provisional".
- **Modo QC de campo:** la config *no* se rechaza (el levantamiento ya existe); se registra una métrica crítica `PROJECT_INFEASIBLE` ⇒ `FAIL` con la causa, para no abortar el análisis y sí impedir un falso `PASS`.
- **V-E0-4 (regresión del hallazgo):** la config v1.1 (`N=24, dx=2, x₁=6, NACD=0.5/0.25, κ_z=2.5, z_obj=30`) produce `z_max,cert=4.8`, `z_max,prov=9.6` e `InfeasibleProject`.
- **V-E0-5:** `feasibility()` coincide con los valores manuales de V-E5-9 y con la ruta de E5.7 (igualdad exacta; una sola implementación).
- **V-E0-6:** los perfiles de entrega del Anexo C (`vs30_sitio`, `cimentacion_estandar`) son factibles (`z_max,cert ≥ z_obj`); monotonicidad: aumentar `N·dx` o `x₁` nunca reduce `z_max`; fronteras `z_obj = z_max ± ε`.
- **V-E0-7:** análisis estático: ningún símbolo `L` sin subíndice en `masw/`, `trs/`, `core/feasibility.py` (§1.4).

- **V-E0-8 (geófono, v1.3):** (a) `N=48, dx=2, x₁=40, NACD=0.5, κ_z=2.5, f_n=4.5, Vs_min=180, ν=0.4` ⇒ `z_max,array=38.4`, `z_max,nf=32.0`, **`z_max,geo=15.08`**, `bottleneck=geophone`; con `f_n=2.0` ⇒ `z_max,geo=33.92`, `bottleneck=nearfield`, `z_max,cert=32.0` (cálculo manual en el test, `c=0.942195·180`). (b) Semántica de severidad: si `z_max,geo` es el único término bajo `z_obj` y proviene de la **cota inferior** (`c_lowfreq_ms` ausente) ⇒ aviso `GEOPHONE_BOUND` (WARN en planificación, no `InfeasibleProject`); si `c_lowfreq_ms` fue dado ⇒ `InfeasibleProject`. (c) Monotonía: bajar `f_n` o subir `Vs_min` nunca reduce `z_max,geo`. (d) El término `geo` usa exactamente la función de V-E3-4 (una sola implementación).

**Gate G0:** V-E0-1..8 `PASSED`.


---

## E1 — Ingesta y modelo de datos

### E1.1 Lectores
- Implementar `read_shot(path) -> Shot` para SEG-2, SEG-Y (rev 0/1, con `segyio`), miniSEED; auto-detección por firma de archivo.
- Extraer: `dt`, `n_samples`, delay, ganancia, stack count, posición de fuente/receptores (cabecera → CSV de respaldo).
- **V-E1-1 (round-trip):** escribir un `Shot` sintético en SEG-Y y releerlo ⇒ amplitudes iguales con `rtol=1e-6` (float32 IBM/IEEE según formato), `dt` exacto, geometría exacta.
- **V-E1-2 (robustez):** archivos truncados, vacíos, `dt=0`, endianness invertida ⇒ excepción tipada `IngestError` con mensaje accionable; **nunca** retorno silencioso.
- **V-E1-3 (property, hypothesis):** para `n_ch∈[1,96]`, `n_s∈[16,32768]`, `dt∈[1e-5,1e-2]` el round-trip conserva la forma de la matriz.

### E1.2 Geometría
- Validar monotonía, espaciamiento: `dx_i = x_{i+1}-x_i`; reportar `dx_med`, `max|dx_i - dx_med|/dx_med`, huecos, canales fuera de línea (`|z|` o desvío lateral).
- **V-E1-4:** tendido con un geófono desplazado 20 % de `dx` ⇒ WARN; 50 % ⇒ FAIL (umbrales configurables). Tendido perfecto ⇒ PASS con valor 0.
- **V-E1-5:** `xs` dentro del tendido (disparo "interno") se clasifica como tal; fuente a offset `x1` calculado exactamente al primer receptor.

### E1.3 Reconciliación cabecera ↔ CSV
- Discrepancias > `tol_pos` (def. 0.1 m) ⇒ FAIL de integridad (la geometría errada invalida MASW y TRS).
- **V-E1-6:** inyectar discrepancia de 0.5 m ⇒ detectada; 0.05 m ⇒ PASS.

**Gate G1:** V-E1-1..6 `PASSED`; cobertura de líneas en `io/` ≥ 90 %.


---

## E2 — QC común (REQ-QC)

Para cada métrica: definición matemática, estimador, umbral inicial, validación.

### E2.1 Integridad temporal y espectral
- Nyquist: `f_N=1/(2dt)`. Verificar `f_max_objetivo ≤ 0.8 f_N` (MASW: típico 100–200 Hz; TRS: 1–2 kHz).
- Longitud de registro: `T = n_s·dt`.
  - MASW: `T ≥ T_min = L_total/c_min + T_wavelet + margen`, con `c_min` configurable (def. 80 m/s) y resolución espectral `δf=1/T ≤ δf_max` (def. 0.5 Hz).
  - TRS: `T ≥ x_max/V_min_refractor + margen`.
- **V-E2-1:** para `L_ap=46 m (N=24, dx=2), x1=5 m ⇒ L_total=51 m, c_min=80 m/s, T_wavelet=0.3 s` ⇒ `T_min=51/80+0.3=0.9375 s` (exacto); registro de 0.5 s ⇒ FAIL, 2 s ⇒ PASS (valor exacto verificado analíticamente).

### E2.2 Canales muertos y ganancia anómala
- RMS por canal `r_i = sqrt(mean(u_i²))`; estadístico robusto `z_i = (log r_i − median(log r)) / (1.4826·MAD(log r))`.
- Muerto: `r_i < ε·median(r)` (ε=1e-3 inicial) o varianza exactamente 0 o valor constante.
- Ganancia anómala: `|z_i| > 3.5` (Iglewicz–Hoaglin).
- **V-E2-2:** inyectar k canales muertos (k=1..4 de 24) ⇒ recall = 1.0; en 200 realizaciones limpias, tasa de falsos positivos ≤ 2 %.

### E2.3 Saturación (clipping)
- `FS` = fondo de escala (de cabecera/ADC, o `max|u|` global si no disponible, marcado como estimado).
- Fracción saturada `φ_i = #(|u_i| ≥ 0.98·FS)/n_s`; detección de plateaus: ≥ 3 muestras consecutivas idénticas al máximo.
- **V-E2-3:** onda recortada al 80 % del pico ⇒ detectada; sin recorte ⇒ no detectada. Umbrales: WARN `φ>1e-4`, FAIL `φ>1e-3` (en ventana de señal).

### E2.4 Ruido y SNR
- Ruido: `σ_n² = var(u_i[t∈ventana_ruido])`; señal: `P_s = mean(u_i²[t∈ventana_señal])`.
- `SNR_i (dB) = 10·log10( (P_s − σ_n²)_+ / σ_n² )` (corrección de sesgo por ruido en ventana de señal).
- SNR espectral: densidad espectral por Welch en ambas ventanas (mismo `nperseg`, misma ventana), `SNR(f)=PSD_s(f)/PSD_n(f)`.
- Líneas de red (50/60 Hz + armónicos): pico en PSD con prominencia `> 10 dB` sobre la mediana local (±5 Hz).
- **V-E2-4 (calibración):** señal Ricker + ruido blanco gaussiano con SNR verdadero ∈ {0,5,10,20,30} dB ⇒ error medio |SNR_est − SNR_verd| ≤ 1.5 dB (SNR ≥ 5 dB), sesgo ≤ 1 dB, sobre ≥ 500 realizaciones.
- **V-E2-5:** inyectar sinusoide 60 Hz a −10/0/+10 dB relativo al ruido ⇒ detectada desde 0 dB; frecuencia estimada con error ≤ 0.1 Hz.

### E2.5 Polaridad y acople
- Polaridad (TRS): signo del primer movimiento coherente entre canales vecinos; polaridad (MASW): correlación cruzada de trazas adyacentes en ventana de señal, `ρ_{i,i+1} < −0.3` ⇒ inversión.
- Acople: residual de ajuste robusto `log A(x)=a−n·log|x−xs|−α|x−xs|` (Huber); canal con `|resid| > 3.5 MAD` ⇒ mal acople.
- **V-E2-6:** invertir polaridad de 1–3 canales ⇒ detección ≥ 95 % (SNR≥10 dB); modular amplitud de un canal ×0.2 ⇒ marcado como acople.

### E2.6 Estabilidad del disparo y repetibilidad entre stacks
- Jitter de t0: lag de máxima correlación cruzada normalizada entre disparos/stacks sucesivos, refinado por interpolación parabólica (precisión sub-muestra). `σ_t0` = desviación estándar de los lags.
- Repetibilidad: `ρ = max_τ xcorr_norm(u^(a), u^(b))` en ventana de señal.
- Umbrales iniciales: `σ_t0 ≤ 0.25 ms (TRS), ≤ 1 ms (MASW)`; `ρ ≥ 0.85 (WARN <0.85, FAIL <0.6)`.
- **V-E2-7:** desplazar réplicas por lags conocidos ∈ [−3,3] muestras, incluidos no enteros (0.37 dt) ⇒ error de lag ≤ 0.05 dt con SNR ≥ 15 dB.
- **V-E2-8 (ganancia de stack):** apilar N=1,2,4,8,16 réplicas con ruido independiente ⇒ pendiente de `SNR_dB` vs `10·log10(N)` ∈ [0.85, 1.15] (teoría: +10·log10 N dB para ruido incoherente). Desviación indica ruido coherente/pérdida de coherencia y se reporta.

### E2.7 Respuesta del geófono
- Frecuencia natural `f_n`; amortiguamiento `h`≈0.7. Respuesta `|H(f)|=f²/ sqrt((f_n²−f²)²+(2h f_n f)²)`. Frecuencia mínima fiable: `f_low = k_g·f_n` (k_g=1.0–1.5).
- **V-E2-9:** para `f_n=4.5 Hz, h=0.7`, `|H(f_n)|` coincide con la fórmula analítica a `rtol=1e-9`; el flag MASW de banda baja se activa cuando `f_min_obj < f_low`.

### E2.8 Agregación del QC común
- Cada métrica → `Metric`; resumen por traza → por disparo (reglas en E6).
- **V-E2-10 (clasificación global sobre corpus sintético, REQ-QC-10):** 1000 registros (50 % limpios, 50 % con una falla inyectada de severidad "clara": canal muerto, clipping, SNR<3 dB, polaridad invertida, jitter>1 ms, geometría errada, `dt` errado ×2). Requisitos: **recall ≥ 0.95** por tipo de falla; **FPR ≤ 0.05** en limpios; matriz de confusión guardada en evidencia.

**Gate G2:** V-E2-1..10 `PASSED`.


---

## E3 — Generación sintética y falla controlada (base de toda validación)

> Principio: **todo algoritmo se valida contra una solución conocida**. E3 produce esas soluciones.

### E3.1 Wavelets y ruido
- Ricker: `w(t)=(1−2π²f_p²(t−t_0)²)e^{−π²f_p²(t−t_0)²}`; ruido blanco y coloreado (1/f^β, β∈[0,2]); ruido ambiental de tráfico (banda 5–30 Hz) y de red (50/60 Hz).
- **V-E3-1:** espectro de amplitud del Ricker tiene máximo en `f_p` (±1 bin); energía conservada (Parseval) a `rtol=1e-10`; ruido con SNR objetivo produce SNR medido con error ≤ 0.2 dB.

### E3.2 Sintético TRS (tiempos analíticos + eikonal independiente)
Soluciones analíticas de referencia:
- **Capa horizontal sobre semiespacio** (`V1<V2`, espesor `h`): onda directa `t=x/V1`; refractada `t=x/V2 + t_i`, `t_i = 2h√(V2²−V1²)/(V1V2)`; cruce `x_c = 2h√((V2+V1)/(V2−V1))`.
- **Capa inclinada** (buzamiento `φ`, `θ_c=asin(V1/V2)`): velocidades aparentes `V_d = V1/sin(θ_c+φ)` (buzamiento abajo), `V_u = V1/sin(θ_c−φ)`; reciprocidad exacta `t_AB=t_BA`.
- **Gradiente lineal** `v(z)=v_0+g z`: `t = (1/g)·arccosh(1 + g²r²/(2 v_s v_r))`, con `r` distancia fuente–receptor y `v_s,v_r` velocidades en los extremos.
- Fuente de verdad adicional: eikonal (FMM) con malla fina (≥ 10× más fina que la usada por la inversión).
- Waveform: convolución del Ricker con los tiempos + ruido + atenuación `A ∝ r^{-1}e^{−αr}`.
- **V-E3-2:** implementación de cada fórmula contra casos límite: `V2→∞` ⇒ `t_i→2h/V1`... (verificar con valores numéricos exactos a `rtol=1e-12`); en `x=x_c` ambas ramas coinciden a `1e-12`.
- **V-E3-3:** para modelo horizontal, `t_AB=t_BA` exacto a `1e-12`.

### E3.3 Sintético MASW (suma modal; independiente del transformador)
- Ecuación de dispersión de Rayleigh en medio estratificado: determinante de Haskell–Thomson (propagador) o `disba`. Para semiespacio homogéneo, `x=(c/V_s)²` resuelve `(2−x)² = 4√(1−x)√(1−κ²x)`, `κ=V_s/V_p`.
- Campo en el dominio de la frecuencia (campo lejano, modos `m`):
  `U(x,f) = S(f) Σ_m A_m(f) · exp(−i k_m(f)|x−x_s|) / √(k_m|x−x_s|) · exp(−α_m(f)|x−x_s|)`, con `k_m=2πf/c_m(f)`, `α_m=π f /(Q c_m)` (aprox.).
- Salida temporal por IFFT con relleno de ceros suficiente para evitar wrap-around (`T ≥ 2×` tiempo de viaje máximo).
- Modos superiores ponderados con `A_m/A_0` configurable; ruido de E3.1.
- **V-E3-4 (física de referencia, corregido v1.2):** el test **resuelve** la cúbica `ξ³ − 8ξ² + 8(3−2κ²)ξ − 16(1−κ²) = 0`, `ξ=(c/Vs)²`, `κ²=(1−2ν)/(2(1−ν))`, con `scipy.optimize.brentq` en `ξ∈[0,1]` (el intervalo encierra siempre la raíz: `P(0)=−16(1−κ²)<0`, `P(1)=1`; hay exactamente una raíz en (0,1)). La forma con radicales `(2−ξ)²=4√(1−ξ)√(1−κ²ξ)` **no** se usa para resolver (tiene la raíz espuria `ξ=0`) sino como **verificación independiente del residuo** (`|res|<1e-10`). Se compara con constantes de respaldo, **marcadas por origen**: *literatura/forma cerrada* (`ν=0, 0.25, 0.5` a `1e-4`; `ν=0.25` exacto `ξ=2−2/√3` a `1e-13`) y *regresión autogenerada* (resto, a `1e-5`; no es verdad independiente):
  | ν | c_R/Vs exacto | aprox. Viktorov `(0.862+1.14ν)/(1+ν)` |
  |---|---|---|
  | 0.25 | 0.91940 | 0.9176 |
  | 0.30 | 0.92741 | 0.9262 |
  | 0.45 | 0.94896 | 0.9483 |
  | 0.50 | 0.95531 (cota física) | 0.9547 |

  Además: Viktorov difiere del solver `≤ 2e-3` **solo para `ν ≥ 0.25`** (medido: desde `ν≈0.237`; en `ν=0` el error es `0.012`; Bergmann `(0.87+1.12ν)/(1+ν)` queda `≤ 4e-3` en todo el rango); `c_R/Vs` es estrictamente creciente en `ν`; continuidad en `ν=0.5` sin salto. Implementación y 34 tests: `geoqc/core/physics.py`, `tests/unit/test_rayleigh_halfspace.py`. Cualquier valor > 0.95531 es físicamente inadmisible y el test debe fallar.
  *Errata: v1.0 escribió 0.9674 para ν=0.45; la revisión externa propuso 0.9503. Ninguno coincide con la solución exacta.*
- **V-E3-5 (consistencia cruzada de dos implementaciones):** curva fundamental propia (Haskell–Thomson mínima) vs `disba` para 3 modelos (incluyendo uno con inversión de velocidad) ⇒ diferencia relativa ≤ 0.5 % en [f_min, f_max] salvo en el borde de corte.
- **V-E3-6:** límite de alta frecuencia: `c(f→∞) → c_R(capa 1)`; límite de baja frecuencia: `c(f→0) → c_R(semiespacio)` (tolerancia 1 %).

### E3.4 Inyector de fallas (`synth/faults.py`)
Funciones puras con parámetro de severidad `s∈[0,1]`: `dead_channel`, `clip`, `add_noise(snr)`, `flip_polarity`, `time_shift`, `bad_geometry`, `wrong_dt`, `mains_hum`, `traffic_burst`, `coupling_loss`, `trigger_jitter`, `truncated_record`.
- **V-E3-7:** cada inyector es determinista dada la semilla, y la falla medida con un estimador independiente coincide con la severidad pedida (p. ej. `add_noise(10 dB)` ⇒ 10±0.3 dB).

**Gate G3:** V-E3-1..7 `PASSED`.


---

## E4 — Módulo TRS (REQ-TRS)

### E4.1 Picking de primeros arribos con incertidumbre
**Algoritmo (cascada):**
1. Pre-filtro Butterworth fase-cero, banda `[f_lo, f_hi]` adaptativa al espectro de la traza.
2. Detección gruesa STA/LTA (ventanas `T_sta ≈ 1–2 periodos`, `T_lta ≈ 10–20 periodos`).
3. Refinamiento AIC (Maeda 1985) en ventana alrededor de la detección:
   `AIC(k) = k·log(var(u[1:k])) + (N−k−1)·log(var(u[k+1:N]))`, pick = `argmin`.
4. Incertidumbre `σ_t` por (a) curvatura de AIC y (b) SNR local; modelo empírico `σ_t = a·T_dom/√SNR_lin + b·dt`, con `a,b` **calibrados por Monte Carlo (V-E4-3)**, no asumidos.
5. Bandera `reliable = (SNR ≥ SNR_min) ∧ (σ_t ≤ σ_max)`.

- **V-E4-1 (exactitud):** sobre sintético de capa horizontal, `dt=0.25 ms`, Ricker 80 Hz, SNR ≥ 15 dB: mediana de `|t_pick − t_verdadero|` ≤ 1 dt; percentil 95 ≤ 3 dt. Para SNR = 5 dB: percentil 95 ≤ 1 periodo dominante/4.
- **V-E4-2 (robustez):** ráfaga de ruido, canal muerto o polaridad invertida ⇒ pick marcado `reliable=False` (nunca pick "confiado" erróneo); tasa de picks confiados erróneos (`|error|>σ_t·3`) ≤ 2 %.
- **V-E4-3 (calibración de incertidumbre):** en ≥ 5000 picks sintéticos, fracción con `|error| ≤ σ_t` ∈ [0.58, 0.78] (≈68 % ± 10 %) y con `|error| ≤ 2σ_t` ∈ [0.90, 0.99]; reportar curva de calibración.
- **V-E4-4 (invariancias):** escalar amplitud ×k, o desplazar toda la traza ⇒ pick idéntico (a ±1 muestra) tras corrección de desplazamiento; reordenar canales ⇒ picks permutados idénticamente.

### E4.2 Reciprocidad (control de calidad más robusto)
- Para pares recíprocos (A fuente→B receptor y B fuente→A receptor):
  `Δ_AB = t_AB − t_BA`, `σ_Δ = √(σ_AB² + σ_BA²)`, estadístico `z = Δ_AB/σ_Δ`.
- Criterio compuesto: PASS si `|Δ| ≤ max(tol_abs, tol_rel·t̄, 2σ_Δ)` con `tol_abs=1 ms`, `tol_rel=2 %` (iniciales).
- Métrica global: porcentaje de pares recíprocos que pasan, y `RMS(z)`; en datos buenos `RMS(z)≈1`; `RMS(z) ≫ 1` indica errores sistemáticos (geometría o t0), no solo ruido.
- **V-E4-5:** sobre modelo horizontal sin ruido: `Δ=0` exacto; con ruido gaussiano σ conocido ⇒ `RMS(z) ∈ [0.85, 1.15]` y fracción `|z|<2` ≈ 95 % ± 3 %.
- **V-E4-6:** inyectar error de geometría de +0.5 m en un receptor ⇒ pares recíprocos que lo involucran fallan, patrón detectado, y el diagnóstico apunta al receptor culpable (identificación correcta en ≥ 90 % de 200 realizaciones).
- **V-E4-7:** error de t0 de +2 ms en un solo disparo ⇒ firma sistemática: `mean(Δ)` del disparo ≈ 2 ms; se atribuye a trigger (no a geometría).

### E4.3 Curvas tiempo–distancia
- **Segmentación piecewise-lineal** (hasta `K_max=3` segmentos) con selección por BIC:
  `BIC = n·ln(RSS/n) + p·ln n`, `p = 2K + (K−1)`; puntos de quiebre continuos o con salto controlado.
- Ajuste robusto (Huber o RANSAC con umbral `3·MAD`) para identificar outliers.
- Salidas por segmento: pendiente (`1/V_apparent`), intercepto `t_i`, `R²`, residual MAD.
- Chequeos:
  1. **Monotonicidad:** `t` no decrece con |offset| salvo tolerancia `σ_t`.
  2. **Intercepto de onda directa** `|t_i,dir| ≤ tol_t0` (def. 1 ms) ⇒ valida `t0` y `xs`.
  3. **Velocidad plausible:** `V ∈ [V_min, V_max]` del perfil geotécnico.
  4. **Inversión de velocidad / zona ciega:** pendiente aparente creciente con el offset (velocidad decreciente) ⇒ alerta "posible capa de menor velocidad"; salto de tiempo anómalo ⇒ "posible capa oculta" (aviso informativo, no FAIL).
- **V-E4-8:** modelo de 2 capas: segmentación recupera `K=2`, `V1,V2` con error ≤ 2 % (SNR ≥ 15 dB), `t_i` con error ≤ 1 ms, y `h` por fórmula inversa `h = t_i V1V2/(2√(V2²−V1²))` con error ≤ 5 %.
- **V-E4-9:** modelo de 3 capas ⇒ `K=3`; modelo de 1 capa ⇒ `K=1` (BIC no sobreajusta: sobre 500 realizaciones, `K` correcto ≥ 90 %).
- **V-E4-10:** capa ciega (capa con velocidad intermedia demasiado delgada) y capa de baja velocidad ⇒ alerta emitida; modelo sin esos fenómenos ⇒ no emitida (FPR ≤ 5 %).
- **V-E4-11:** 10 % de outliers gruesos (picks desplazados ≥ 20 ms) ⇒ el ajuste robusto los identifica con recall ≥ 95 % y sesga la pendiente ≤ 1 %.

### E4.4 Cobertura y suficiencia geométrica
- Offset máximo y profundidad alcanzable: criterio práctico `L_tendido ≥ N_L · z_obj` con `N_L ∈ [3,5]` (def. 4; configurable); más preciso: `x_max ≥ k_c · x_c(h_obj)` con `k_c ≥ 1.5–2` para observar el refractor profundo con ≥ 3–4 puntos.
- Cobertura de rayos (ver E4.5): densidad de rayos por celda y **DOI** (profundidad de investigación) como la isóbata donde la cobertura cae bajo el umbral.
- Disparos: mínimo `n_shots_min` (def. 5: extremos, 1/4, centro, 3/4 + externos `±L_ap/2`), con disparos inversos para cada refractor.
- Aviso de heterogeneidad lateral: diferencia `V_d` vs `V_u` > umbral ⇒ buzamiento/lateralidad; se recomienda disparo adicional.
- **V-E4-12:** sobre un modelo con objetivo `z_obj=15 m, V1=300, V2=1500`: `x_c = 2h√((V2+V1)/(V2−V1)) = 2·15·√(1800/1200)=36.7 m` calculado exactamente; tendido de 46 m con `k_c=1.5` ⇒ FAIL/WARN según config; con 72 m ⇒ PASS.

### E4.4b Cobertura de rayos por celda: hits y cobertura angular (v1.1)

La no-unicidad de la tomografía se controla celda a celda, no solo con el DOI global.
- **Hits** `H_c`: número de rayos (de pares fuente–receptor con pick confiable) que atraviesan la celda `c`, calculado con longitud de intersección exacta rayo–celda (algoritmo de Siddon) sobre los rayos del eikonal. Variante complementaria: **DWS** (derivative weight sum) `Σ_k L_{k,c}`. Los umbrales dependen del tamaño de celda: se normalizan como `H_c · (h_celda/dx_receptores)` y se calibran (iniciales: verde ≥ 10, ámbar 4–10, rojo < 4 para `h_celda = dx/2`).
- **Cobertura angular** `Θ_c`: sean `θ_k ∈ [0, π)` las orientaciones (módulo π) de los segmentos de rayo en la celda. Se calculan dos indicadores:
  1. *Span angular*: `Θ_c = π − max(gap circular entre orientaciones ordenadas)`, en grados (iniciales: verde ≥ 60°, ámbar 30–60°, rojo < 30°).
  2. *Anisotropía del tensor de estructura* `T=(1/n)Σ [cos θ, sin θ]ᵀ[cos θ, sin θ]`: `A_c = λ_min/λ_max ∈ [0,1]` (0 = una sola dirección; 1 = isotrópico).
- Se evalúan en la zona objetivo (`z ≤ z_obj`, rango x del tendido) y se reporta el porcentaje de celdas objetivo en cada color; veredicto: verde si ≥ 90 % de celdas objetivo cumplen verde, rojo si > 20 % están en rojo.
- **V-E4-18 (exactitud geométrica):** en medio homogéneo (rayos rectos) el conteo de hits por Siddon coincide *exactamente* con la fuerza bruta (intersección geométrica de cada segmento con cada celda) en 100 % de las celdas; la longitud total de rayos por celda coincide a `rtol=1e-10`.
- **V-E4-19 (ángulos):** celda con rayos a {0°, 60°, 120°} ⇒ `Θ=120°`; un solo ángulo ⇒ `Θ=0°`, `A=0`; orientaciones uniformes en [0,π) ⇒ `A→1` (±0.05 para n≥200).
- **V-E4-20 (triple test, §0.11):** configuraciones de tendido con disparos solo en extremos (rojo en profundidad), con disparos intermedios (ámbar) y con intermedios + off-end (verde) ⇒ clasificación correcta; la acción recomendada pasa de "agregar shots intermedios/off-end/laterales" a ninguna.
- **V-E4-21 (correlación con error real):** sobre sintéticos, el error de velocidad recuperado por celda correlaciona negativamente con `H_c` y `Θ_c` (Spearman `ρ_s ≤ −0.5`); si no, los umbrales se recalibran por ADR.

### E4.5 Solver de referencia y tomografía rápida de prueba
- **Eikonal FMM** (primer orden mínimo; segundo orden recomendado). Orden de convergencia observado `p_obs` vía extrapolación de Richardson.
- **V-E4-13 (verificación del solver):**
  - medio homogéneo: error máximo de tiempo ≤ 1 % a 20 celdas por longitud característica, y ≤ 0.2 % a 80 celdas;
  - gradiente lineal (solución analítica de E3.2): `p_obs ≥ 0.9` (FMM 1er orden) al refinar `h→h/2→h/4`;
  - capa horizontal: tiempos de la onda refractada ≤ 1 dt de la solución analítica en malla fina.
- **Tomografía rápida** (`pygimli.physics.traveltime`): malla gruesa, regularización suave, 3–5 iteraciones, límites `V∈[V_min,V_max]`.
- Métricas:
  - `χ² = (1/N)·Σ((d_i−f_i(m))/σ_i)²` (objetivo ≈ 1; WARN `>2`, FAIL `>4`);
  - `RMS` absoluto (ms) y su ratio con `mean(σ_t)`;
  - residuo normalizado por receptor/fuente (detecta outliers de picking o geometría);
  - cobertura de rayos y DOI.
- **V-E4-14 (recuperación):** datos generados con eikonal en malla fina + ruido `σ_t=0.5 ms` sobre un modelo de 2 capas con ondulación suave; la inversión rápida alcanza `χ²∈[0.7,1.5]` y recupera `V` promedio por capa con error ≤ 10 %.
- **V-E4-15 (sensibilidad a errores):** inyectar 5 % de picks erróneos ⇒ `χ²` sube ≥ 50 % y los residuos normalizados > 3 identifican ≥ 80 % de los picks erróneos.
- **V-E4-16 (tiempo):** ≤ 25 s para 24 canales × 12 disparos en laptop de referencia (OQ-05).

### E4.6 Veredicto TRS
Combinar con reglas de E6: reciprocidad (crítica), % picks confiables, `χ²`, intercepto directo, cobertura/DOI, número de disparos.
- **V-E4-17:** matriz de decisión sobre 300 escenarios sintéticos etiquetados (buen/regular/malo según criterio teórico establecido a priori) ⇒ acuerdo ≥ 90 %, nunca "PASS" para un escenario "malo" severo.

**Gate G4:** V-E4-1..17 `PASSED`.


---

## E5 — Módulo MASW (REQ-MSW)

### E5.1 Preprocesamiento
- Muting de ruido pre-trigger y de refracciones/aire (ventana por velocidad `c_air≈340`, `c_P`).
- Banda y normalización de trazas opcional (afecta amplitud relativa; si se normaliza, queda registrado).
- **V-E5-1:** el preprocesamiento no altera la fase del plano de onda inyectado: error de fase ≤ 1e-3 rad en la banda útil.

### E5.2 Transformada de dispersión (phase-shift, Park et al. 1998)
Definición:
```
U(x_j,f) = FFT{u_j(t)}
I(f,c)   = | (1/N) Σ_j  exp(+i 2π f x_j / c) · U(x_j,f)/|U(x_j,f)| |
```
(con `x_j` = offset respecto a la fuente; **el signo del exponente se fija por V-E5-2**, no se asume).
Alternativas implementadas para validación cruzada: **f–k** (FFT 2D con relleno) y **τ–p / slant-stack**.

- **V-E5-2 (onda plana monocromática):** `u(x,t)=cos(2πf₀(t − x/c₀))` con `N=24, dx=2 m`. El máximo de `I(f₀,c)` está en `c₀` con error relativo ≤ 0.5 % (rejilla `δc` ≤ 0.1 m/s), y `I_max = 1 ± 1e-6`. Con signo invertido el test debe fallar ⇒ fija la convención.
- **V-E5-3 (resolución teórica):** FWHM del pico en `c`: `δc/c ≈ 0.886·λ/(N·dx)` (kernel de Dirichlet ⇒ ancho en `k` ≈ `0.886/(N dx)`, y `δc/c=δk/k=λ δk`). Verificar medido vs teoría dentro de ±15 % para `λ ∈ {L_eff/4, L_eff/2, L_eff}`.
- **V-E5-4 (aliasing espacial):** `k_N = 1/(2dx)` ciclos/m ⇒ `λ_min = 2dx`. Onda plana con `λ = 1.5 dx` ⇒ `I` presenta lóbulo alias (en `k−1/dx`); la métrica de aliasing lo señala. Con `λ=3dx` ⇒ sin alias. Frecuencia límite en la curva: `f_alias(c)=c/(2 dx)`.
- **V-E5-5 (equivalencia de métodos):** para el mismo sintético dispersivo, picos de phase-shift vs f–k vs τ–p coinciden en la banda de alta SNR con diferencia mediana ≤ 2 %.
- **V-E5-6 (invariancias):** (a) escala de amplitud ×k ⇒ `I` idéntica (la normalización de fase lo garantiza); (b) desplazamiento temporal constante ⇒ `|I|` idéntica; (c) inversión del orden de canales con `x→−x` ⇒ `I` idéntica; (d) adición de canal muerto ⇒ degradación acotada (≤ 10 % en `I_max`) *si* se excluye correctamente (la exclusión debe mejorar `I_max`).

### E5.3 Picado del modo fundamental
- Extraer, por frecuencia, máximos locales de `I(f,c)` con prominencia; trayectoria por **programación dinámica (Viterbi)** que maximiza `Σ I(f,c_f)` penalizando saltos `|Δc|` (suavidad) y priorizando el modo de menor `c` con energía significativa.
- Detección de **saltos de modo**: discontinuidad `|c(f_{i+1}) − c(f_i)| > ν·δc_FWHM` ⇒ "posible contaminación/ transición de modo".
- Razón de energía modal `R_m(f)= I_peak(modo superior)/I_peak(fundamental)`.
- **V-E5-7:** modelos con (a) dispersión normal, (b) inversión de velocidad (capa blanda), (c) rigidez fuerte contraste: el picado recupera la curva fundamental teórica (E3.3) con **error RMS relativo ≤ 3 %** en la banda válida para SNR ≥ 20 dB, y ≤ 6 % para SNR=10 dB; sin saltos de modo erróneos en ≥ 90 % de las realizaciones en (a), ≥ 75 % en (b),(c) (se reporta el resto como WARN).
- **V-E5-8:** cuando el modo 1 supera en energía al modo 0 en banda concreta (A₁/A₀=2), el sistema marca "modo aparente ≠ fundamental" en esa banda (recall ≥ 90 %).

### E5.4 Límites de validez (banda fiable)
Definir `valid_band = {f : λ(f) ∈ [λ_min, λ_max]} ∩ {f ≥ f_low} ∩ {NACD(f) ≥ NACD_amber} ∩ {SNR(f) ≥ SNR_min} ∩ {I_peak ≥ I_min(N, α, N_eff)}` (umbral estadístico, ver E5.4b), con:
- `λ_min = α_alias · dx`, `α_alias ≥ 2` (def. 2.5).
- `λ_max = α_L · L_eff`, `L_eff = N dx`, `α_L ≤ 1` (def. 1.0; justificado por `δc/c = λ/L_eff`).
- `f_low = k_g · f_n` (E2.7).
- **Campo cercano en dos niveles** (Yoon & Rix 2009): `NACD(f) = x₁/λ(f)`.
  - `NACD ≥ NACD_green` (def. 0.5) ⇒ **banda certificable**: `λ ≤ x₁/NACD_green`.
  - `NACD_amber ≤ NACD < NACD_green` (def. 0.25) ⇒ **banda provisional (WARN)**: se reporta con la etiqueta *"sesgo de campo cercano no despreciable"* y el sesgo estimado (V-E5-10). Por debajo de `NACD_amber` el punto queda fuera de la banda.
  - Presets: `estricto: green=1.0, amber=0.5`. **Calibrar en E5.9 y E9.**
- **Multi-offset (v1.2):** `x₁` puede ser una lista (`x1_list_m`). La validez se evalúa **por disparo** y se toma la unión de bandas: `λ_max,valid = max_s min(α_L·L_eff, x₁,s/NACD)`. Es la forma práctica de cubrir bajas frecuencias sin un único offset enorme.
- **Profundidades (v1.3):** `z_max,cert = min(z_max,array, z_max,nf(green), z_max,geo)` y `z_max,prov = min(z_max,array, z_max,nf(amber), z_max,geo)` (definidos en E0.4); el informe indica siempre el **cuello de botella** (`array`, `nearfield` o `geophone`).
- **Campo lejano:** atenuación excesiva del extremo del arreglo ⇒ SNR local insuficiente (ya en E2.4).
- **V-E5-9 (aritmética exacta, regresión del hallazgo v1.2):** `N=24, dx=2, x₁=6, NACD_green=0.5, κ_z=2.5`: `L_eff=48`, `λ_min=5`, `λ_nf,green=12`, banda certificable `λ∈[5,12]`, **`z_max,cert=4.8 m`**; con `NACD_amber=0.25`: `λ_nf=24`, `z_max,prov=9.6 m`. Otros valores de control: `N=48,dx=2,x₁=8 ⇒ 6.4 m`; `N=48,dx=2,x₁=40 ⇒ 32.0 m`; `N=48,dx=2,x₁=24,NACD=0.3 ⇒ 32.0 m`. Si `λ_nf<λ_min` el arreglo es inválido (FAIL). Los tests comparan contra estos cálculos manuales y contra `core/feasibility.py` (misma función, V-E0-5).
- **V-E5-10 (contaminación de campo cercano, cuantitativa):** con simulación de campo cercano (modelo de ondas cilíndricas/esféricas con corrección de campo cercano, o `disba` + términos evanescentes de orden bajo), medir `Δc/c` vs `NACD` y verificar que `NACD_min` elegido mantiene el sesgo ≤ 5 % (preset estándar) / ≤ 2 % (estricto) en los modelos de prueba. Si no se cumple, **ajustar el preset por ADR**, no el test.

### E5.4b Umbral estadístico de coherencia y ancho de banda en octavas (v1.1)

**Distribución nula del phase-shift.** Si las fases `φ_j` en la frecuencia `f` son aleatorias (solo ruido), `S=(1/N)Σ e^{iφ_j}` cumple, para N moderado, `N|S|² ~ Exp(1)`, es decir:
```
P(|S| > a) = exp(−N a²)
```
Con `N_eff ≈ (c_max − c_min)/δc_FWHM` bins independientes de velocidad y probabilidad de falso pico por frecuencia `α` (corrección de Bonferroni):
```
I_min^Ray(N, α, N_eff) = sqrt( ln(N_eff/α) / N )     (aproximación asintótica; cota conservadora)
```
Ejemplo (Rayleigh): `N=24, N_eff=20, α=0.01` ⇒ `≈0.563`; `N=48` ⇒ `≈0.398`.

**Cuantil exacto con N finito (v1.2, el que se usa en producción).** La cola de Rayleigh es asintótica y *sobreestima* la probabilidad con N finito: medido con 2×10⁶ realizaciones, cociente empírico/Rayleigh a `p=10⁻³`: `0.35` (N=12), `0.66` (N=24), `0.81` (N=48). La distribución exacta de la longitud `R` de una suma de `N` fasores unitarios con fases uniformes es (Kluyver, 1906):
```
P(R ≤ r) = r · ∫₀^∞ J₁(r t) · J₀(t)^N dt        con  |S| = R/N
I_min(N, α, N_eff) = Q_N(1 − α/N_eff)           (cuantil exacto)
```
Valores de control (`N_eff=20, α=0.01 ⇒ p=5·10⁻⁴`): `I_min = 0.745 (N=12), 0.546 (N=24), 0.392 (N=48)` (Rayleigh: 0.796, 0.563, 0.398). Se implementa con integración numérica y tabla precalculada en caché. **Esquema numérico (ADR, registrado en la evidencia):** cuadratura adaptativa por subintervalos de `∫₀^{t_max}` con `t_max` fijado por la cota de envolvente `|J₀(t)| ≤ √(2/(πt))`; el JSON guarda `{method, t_max, n_subintervals, epsabs, epsrel, scipy_version}`. Verificado: para `N=12, 24, 48` truncar en `t_max=20, 40` o `200` cambia la cola `P(|S|>I_min)` en `≤1e-10` absoluto, y la identidad de momentos `E|Z|⁴=2N²−N` (exacta, frente a `2N²` de la exponencial) se confirma por Monte Carlo y explica que la cola real sea más ligera (la identidad es coherente con ello, no una prueba por sí sola; la prueba es la integral de Kluyver). **Limitación:** el modelo supone fases independientes y uniformes; el ruido real está correlacionado entre geófonos, por lo que además se verifica con ruido real (V-E5-17b). Un pico por debajo de `I_min` es indistinguible de ruido. El umbral operativo es `max(I_min exacto, floor_config)`; el semáforo ámbar/verde (p. ej. 0.70/0.85) se calibra *por encima* de este piso y depende de N, por lo que **no es transferible entre arreglos sin recalibrar**: el YAML guarda `peak_levels.n_reference` (def. 24) y, si el `N` del registro difiere, el motor emite `WARN: levels_uncalibrated_for_N`, aplica solo el piso estadístico `I_min(N)` y no asigna verde por nivel (V-E5-20).

- **V-E5-17 (rehecho v1.2):** (a) la integral de Kluyver coincide con Monte Carlo independiente (≥ 2×10⁶ fases uniformes) dentro de `3σ` binomial para `a` con `p∈[10⁻³, 0.3]`, `N∈{12,24,48}` (medido: concordancia a 3 cifras); (b) la aproximación Rayleigh es **conservadora**: `P_emp ≤ exp(−N a²)·(1+3σ)` en todos los puntos, y se reporta el cociente (no se exige ±x %); (c) `I_min` exacto reproduce los valores de control `0.745/0.546/0.392` a `±0.005`; (d) sobre ruido gaussiano blanco, 24 canales, tasa de falsos picos por frecuencia en todo `I(f,c)` ≤ `1.5·α`.
- **V-E5-17b (ruido real):** ventanas pre-disparo de registros reales o ruido coloreado/correlacionado espacialmente pasadas por la transformada: la tasa de falsos picos con `I_min` es ≤ `3·α`; si no, se aumenta `N_eff` por una corrección por correlación (ADR).
- **V-E5-20:** con `N ≠ n_reference` el motor emite `levels_uncalibrated_for_N` y ningún verde por nivel de coherencia.
- **V-E5-18 (triple test, §0.11):** onda plana + ruido con SNR que produce `I_peak` en verde/ámbar/rojo ⇒ cada caso se clasifica correctamente; test de frontera en `I_min ± 0.01`.

**Ancho de banda coherente (octavas).** Sea `S_v` el segmento contiguo más largo de `valid_band` (sin saltos de modo): `B_oct = log2(f_max,v / f_min,v)`. Umbrales iniciales: verde ≥ 2, ámbar 1–2, rojo < 1. Es una métrica de *poder de resolución en Vs(z)* complementaria a `z_max` (más octavas ⇒ más grados de libertad independientes en profundidad).
- **V-E5-19:** curva sintética coherente solo en [8, 32] Hz ⇒ `B_oct = 2.0 ± 0.1`; dos segmentos separados por un salto de modo ⇒ se reporta solo el contiguo mayor.

### E5.5 Incertidumbre del picado
Dos estimadores independientes:
1. **Local (resolución):** `σ_c,res ≈ δc_FWHM/(2√(2 ln 2))` (ancho del pico).
2. **Re-muestreo (jackknife sobre canales):** `σ_c,JK² = ((N−1)/N) Σ (c_(−j) − c̄)²`, y bootstrap sobre disparos si hay stacks múltiples.
- Barra final `σ_c(f) = max(σ_c,res, σ_c,JK)` y `COV(f) = σ_c/c`.
- **V-E5-11 (calibración):** en 500 realizaciones sintéticas con ruido, fracción `|c_pick − c_teo| ≤ σ_c` ∈ [0.55, 0.85], y ≤ 2σ_c ∈ [0.90, 1.0].
- **V-E5-12:** `σ_c` crece al aumentar `λ` (más allá de `L_eff/2`) y al disminuir SNR (monotonicidad probada con regresión ⇒ pendiente con signo correcto, p < 0.01).

### E5.6 Repetibilidad entre offsets y direcciones
- Para cada par de registros `(a,b)` (offsets distintos o directo/inverso): curvas `c_a(f), c_b(f)`; en banda común: `COV(f)=std/mean`, mediana de COV, y **diferencia sistemática** `Δ̄ = mean(c_a−c_b)/mean(c)`.
- Interpretación: COV pequeño y Δ̄≈0 ⇒ medio lateralmente homogéneo y datos consistentes; Δ̄ ≠ 0 grande ⇒ buzamiento/variación lateral (alerta ingenieril, no error de datos).
- Umbrales iniciales: mediana COV `≤ 5 % PASS`, `5–10 % WARN`, `> 10 % FAIL`.
- **V-E5-13:** réplicas del mismo modelo con ruido ⇒ mediana COV coherente con `σ_c` esperado (±30 %); modelo con variación lateral conocida (±10 % en `Vs` a lo largo de 40 m) ⇒ Δ̄ detecta la dirección correcta del gradiente.

### E5.7 Cobertura de profundidad y requisito ingenieril
- `z_max,cert = λ_max,green/κ_z` y `z_max,prov = λ_max,amber/κ_z` (E5.4), `κ_z ∈ [2,3]` (def. 2.5; la sensibilidad de Rayleigh decae con la profundidad). Veredicto: `z_obj ≤ z_max,cert` ⇒ PASS; `z_max,cert < z_obj ≤ z_max,prov` ⇒ WARN (provisional); `z_obj > z_max,prov` ⇒ FAIL.
- Comparar con `z_obj` del proyecto (Vs30 ⇒ `z_obj = 30 m ⇒ λ_max,valid ≈ 60–90 m`).
- Si `z_max < z_obj`: FAIL con recomendación cuantificada: *aumentar `L_eff=N·dx` hasta ≥ λ_req/α_L*, *fuente más energética/menor frecuencia*, *geófonos de menor `f_n`*, *agregar un disparo con `x₁ ≥ λ_req·NACD_green` (o `≥ λ_req·NACD_amber` con veredicto provisional)*.
- **V-E5-14:** sensibilidad `∂c/∂Vs_j` calculada por diferencias finitas (`disba`) para el modelo de prueba: el 90 % de la sensibilidad acumulada de `c(f)` a `Vs` se concentra a profundidad `≤ λ/κ_eff` con `κ_eff∈[2,3.5]` en ≥ 80 % de los puntos; si no, se recalibra `κ_z` por ADR.

### E5.8 Veredicto MASW
Combinar: calidad común (E2), SNR espectral en banda, continuidad (saltos de modo), `valid_band` vs objetivo, COV entre disparos, `z_max` vs `z_obj`, contaminación de campo cercano.
- **V-E5-15:** 300 escenarios sintéticos etiquetados a priori ⇒ acuerdo ≥ 90 %; nunca "PASS" si `z_max < 0.8·z_obj` ni si COV mediana > 15 %.

### E5.9 Calibración con inversión de prueba (opcional rigurosa)
- Inversión 1D rápida (p. ej. Occam o MC acotado) sobre la curva picada + incertidumbre; compararla con el modelo verdadero sintético: `Vs30` recuperado ± 15 % (OQ-06). No es criterio de campo, sino de **validación de que las alertas correlacionan con error ingenieril**.
- **V-E5-16:** correlación de rango (Spearman) entre el veredicto numérico del QC y el error de `Vs30` recuperado: `ρ_s ≤ −0.6` (peor QC ⇒ mayor error).

**Gate G5:** V-E5-1..16 `PASSED` (V-E5-16 puede quedar `ADVISORY` si OQ-06 no se aprueba).


---

## E6 — Motor de decisión (REQ-DEC)

### E6.1 Estados y reglas
Cada `Metric` produce `PASS/WARN/FAIL/NA`. Reglas (en `configs/*.yaml`, jamás hardcodeadas):
1. Cualquier métrica `critical=true` en `FAIL` ⇒ registro `FAIL`.
2. `≥ k_warn` métricas en `WARN` (def. 3) ⇒ `WARN`.
3. `NA` no degrada, pero > 30 % de métricas `NA` ⇒ `WARN: cobertura insuficiente de QC`.
4. Agregación jerárquica: traza → disparo → técnica → levantamiento; el peor estado crítico domina.
5. Puntaje `0–100` solo informativo; **el estado lo gobierna la regla lógica**.
- **V-E6-1:** tabla de verdad exhaustiva sobre combinaciones de estados (hasta 6 métricas) coincide con la implementación (test paramétrico).
- **V-E6-2 (monotonicidad):** empeorar el estado de una métrica nunca mejora el veredicto global (property test).

### E6.0 Dependencia jerárquica y modo diagnóstico (v1.1)

Los niveles de QC dependen unos de otros (ver Anexo A.1): un FAIL en integridad, canales o disparo invalida lo que se calcule aguas abajo.
- **Regla:** si L0–L2 tienen un `FAIL` crítico sin resolver, L3/L4 **no emiten veredicto certificable**. Se pueden calcular en **modo diagnóstico** (útil en campo para ver *por qué* falla) pero todas sus métricas llevan `certifiable=false` y el semáforo del sitio no puede pasar de `FAIL`.
- **Semáforo de sitio:** `GREEN` (entregar), `YELLOW` (entregar con salvedades documentadas en la bitácora), `RED` (no abandonar sin repetir). Equivale a `PASS/WARN/FAIL` del motor.
- **V-E6-4:** con una métrica L0 crítica en FAIL, ningún conjunto de métricas L3/L4 en verde produce un veredicto distinto de `RED` (test paramétrico exhaustivo); en modo diagnóstico las métricas L3/L4 existen y están marcadas `certifiable=false`.
- **V-E6-5:** el estado `YELLOW` exige al menos una salvedad registrada en la bitácora; sin ella, el reporte no se genera.

### E6.2 Catálogo de acciones correctivas
Mapa `causa → acción` cuantificada, p. ej.:
- Canal muerto → "reacoplar/cambiar geófono canal N, repetir disparo".
- SNR bajo → "aumentar stacks a N≥ (SNR_obj/SNR_act)·N_actual, o más energía de fuente" (usar el resultado de V-E2-8: `ΔSNR=10log₁₀N`).
- `z_max<z_obj` → ver E5.7.
- Reciprocidad falla en receptor j → "revisar posición/nivelación del geófono j".
- `σ_t0` alto → "revisar trigger/cableado".
- **V-E6-3:** cada `Metric` con `action_ids` referencia acciones existentes (test de integridad referencial); la sugerencia de stacks reproduce el cálculo analítico.

**Gate G6:** V-E6-1..3 `PASSED`.


---

## E7 — Interfaz de usuario

- Vistas: (1) sismograma con picks y semáforo por canal; (2) imagen de dispersión `I(f,c)` con picks, banda válida y curvas límite `λ=2dx, λ=L_eff, NACD`; (3) curvas t–x con ajuste y reciprocidad; (4) mapa de cobertura y DOI; (5) panel de veredicto con acciones; (6) comparación de registros.
- Flujo: arrastrar archivos ⇒ análisis automático ⇒ resultados en < 60 s ⇒ decisión "abandonar/continuar".
- **V-E7-1 (smoke):** UI levanta, carga fixtures, muestra los 6 paneles (pytest-qt, modo offscreen).
- **V-E7-2:** la UI no contiene lógica numérica: grep de importaciones y revisión de dependencias (`core` no depende de `ui`).
- **V-E7-3 (usabilidad):** accesible con pantalla de 1366×768; trabaja con 96 canales × 32k muestras sin congelarse (> 20 fps al hacer zoom con decimación).

**Gate G7:** V-E7-1..3 `PASSED`.


---

## E8 — Reportes y trazabilidad

- PDF de campo (1–2 págs.): veredicto, tabla de métricas, 3 figuras clave, acciones, hash de configuración y de datos (SHA-256), versión de software.
- JSON por registro con todas las métricas y parámetros.
- **V-E8-1:** reproducibilidad: re-ejecutar con el JSON de configuración y los datos ⇒ el mismo reporte (hash de métricas idéntico).
- **V-E8-2:** esquema JSON validado por JSON-Schema versionado; campo `schema_version`.
- **V-E8-3 (certifiable en el hash):** `certifiable` y `diagnostic_mode` forman parte del payload hasheado. El generador de PDF rechaza imprimir el sello "CERTIFICADO" si cualquier métrica o el reporte tiene `certifiable=false`, aunque la UI lo solicite (test: forzar la bandera desde la capa UI ⇒ excepción `CertificationError`; modificar el JSON a mano ⇒ el hash no valida).

**Gate G8:** V-E8-1..2 `PASSED`.


---

## E9 — Verificación y validación integral (V&V)

### E9.1 Pruebas de sistema sobre corpus sintético
- Generar corpus `C₁` (≥ 2000 registros: 1000 MASW, 1000 TRS), parametrizado por: espaciamiento, N, SNR, modelo geológico, tipo/ severidad de falla, fuente. Etiquetas por teoría (no por el propio algoritmo).
- Métricas: recall/FPR por tipo de falla, matriz de confusión del semáforo, ROC por umbral clave (SNR, COV, χ²), calibración de `σ`.
- **V-E9-1:** objetivos agregados: recall (fallas severas) ≥ 0.95, FPR (limpios) ≤ 0.05, acuerdo del semáforo ≥ 0.90.

### E9.2 Análisis de sensibilidad de umbrales
- Barrido de cada umbral ±50 %; informar curvas ROC y elegir puntos de operación; documentar en ADR.
- **V-E9-2:** estabilidad: variar umbrales ±10 % cambia el veredicto en ≤ 5 % de los casos (robustez de las reglas).

### E9.3 Datos reales (OQ-07)
- Mínimo 10 sitios con calidad conocida (buenos y problemáticos), con verificación independiente (inversión final, perforación/ensayos down-hole, interpretación experta).
- **V-E9-3:** concordancia con experto ≥ 85 %; falsos "PASS" en datos que el experto califica "no aceptables" ≤ 5 % (**error de tipo II es el costoso en campo**).

### E9.4 Rendimiento y robustez
- **V-E9-4:** ≤ 60 s por disparo (24–48 ch, 2 s, 0.5 ms) y ≤ 4 GB RAM en el equipo de referencia; sin acceso de red.
- **V-E9-5 (fuzzing):** 10 000 entradas aleatorias/corruptas ⇒ ninguna excepción no controlada; todas producen `IngestError` o reporte con `NA`.
- **V-E9-6:** formatos y endianness diferentes producen resultados idénticos (±1e-6).

**Gate G9:** V-E9-1..6 `PASSED`.


---

## E10 — Empaquetado y operación de campo

- Ejecutable portable (PyInstaller/Briefcase) Windows y Linux; instalación offline; modo "carpeta vigilada" (analiza automáticamente nuevos archivos).
- Manual de usuario de 2 páginas + guía de umbrales + changelog + política de versionado semántico.
- **V-E10-1:** instalación limpia en máquina sin Python ni internet ⇒ ejecuta suite de humo en ≤ 5 min.
- **V-E10-2:** actualizaciones de configuración sin recompilar; cambio de perfil afecta veredictos de forma predecible (test de regresión con "golden files").

**Gate G10:** V-E10-1..2 `PASSED`. **Release candidato.**


---

## E11 — Extensiones (post-v1; no bloquean release)
MASW pasivo/ReMi; MASW 2D (ventana móvil) con mapa de variabilidad lateral; sísmica de refracción 3D; calibración por aprendizaje automático **solo como asistente** (nunca reemplaza reglas explicables); validación con modelado de onda completa (FD 2D elástico) para campo cercano y topografía.


---

## Anexo A — Integración de la retro L0–L5 (v1.1)

### A.1 Mapeo de niveles a etapas

| Nivel retro | Qué valida | Etapa SDD |
|---|---|---|
| L0 Integridad | formato, headers, geometría, ganancia, clipping | E1, E2.1, E2.3 |
| L1 Canal | muertos, ruido, polaridad, red eléctrica, DC, acople | E2.2, E2.4, E2.5 |
| L2 Shot/Spread | trigger, pre-trigger, stacking, repetibilidad, reciprocidad | E2.6, E4.2 |
| L3 Atributos físicos | SNR espectral, coherencia, first-breaks, λ_min/λ_max | E4.1, E4.3, E5.2–E5.4b |
| L4 Inversion-readiness | rango de dispersión, cobertura de rayos, no-unicidad | E4.4–E4.5, E5.6–E5.7 |
| L5 Decisión de campo | semáforo y acciones | E6 |

### A.2 Métricas de la retro incorporadas o ya cubiertas
- **Adoptadas como nuevas:** R4/R5 (hits y cobertura angular, E4.4b); M4 (octavas coherentes, E5.4b); regla jerárquica L0–L2 → L3 (E6.0); semáforo de sitio GREEN/YELLOW/RED; bitácora de decisiones; reglas "si X rojo → acción Y" (se suman al catálogo E6.2: *off-end shots* y *shots laterales* para R4/R5; *revisar acople antes de continuar* para ≥ 2 canales muertos; *reducir dx o fuente de mayor frecuencia* para aliasing; *alejar fuente* para campo cercano).
- **Ya cubiertas:** U1–U8 (E1, E2), M1 (aliasing, E5.4), M2 (campo cercano vía NACD, E5.4), M6/M7 (modos superiores y repetibilidad, E5.3/E5.6), M8 (`z_max=λ_max/κ_z`, E5.7), R1/R3/R6/R7/R9 (E4.1–E4.5).
- **Pre-trigger ≥ 100 ms (U6):** se agrega a E2.1 como métrica de ventana de ruido; sin ella no se puede estimar `σ_n` ni el SNR.

### A.3 Puntos no adoptados tal cual (y por qué)
1. **M3 "offset_max ≥ 1–2·λ_max".** Mezcla dos fenómenos. La resolución en número de onda limita `λ_max ≲ N·dx` (V-E5-3: `δc/c ≈ λ/L_eff`); exigir `offset_max ≥ 2λ_max` con 24 geófonos a 2 m (`L_ap=46 m`, `L_total≈52 m`) limitaría `λ_max` a ~26 m, es decir, `z_max` ≈ 10 m, más estricto que la resolución (`L_eff/κ_z≈19 m`). *(El cuello de botella dominante en esa geometría es en realidad el campo cercano: V-E5-9.)* El efecto de campo lejano real es la atenuación, ya cubierta por el SNR espectral en los canales lejanos (E2.4/E5.4). Se conserva solo como *métrica informativa* configurable, no como criterio de semáforo.
2. **M5 "coherencia ≥ 0.85" como umbral universal.** La amplitud del phase-shift depende de N (ver E5.4b): su nivel de ruido es `≈ sqrt(ln(N_eff/α)/N)`. Con N=24 el piso ya es ≈ 0.56. Los niveles 0.70/0.85 se mantienen pero **por encima del piso estadístico** y recalibrados por N.
3. **R1 "|t_AB − t_BA| ≤ 1 ms" fijo.** Se mantiene como piso, pero el criterio completo es `max(tol_abs, tol_rel·t̄, 2σ_Δ)` con el estadístico `z` (E4.2): un tolerancia absoluta penaliza injustamente offsets largos y velocidades bajas, y no distingue ruido de error sistemático.
4. **R2 "sin inversión de pendiente".** Ambiguo. Lo que debe ser monótono es el *tiempo* con el offset; la *pendiente aparente* sí puede cambiar legítimamente (refractores más rápidos). Una pendiente que *aumenta* (velocidad decreciente) es una alerta geológica de capa de baja velocidad/oculta (E4.3), no necesariamente un error de picking.
5. **"L3 no corre si hay FAIL en L0–L2".** Se refina a *modo diagnóstico sin certificación* (E6.0): en campo el operador necesita ver las gráficas que explican la falla.
6. **Plan de "MVP en 3 semanas".** No es compatible con los gates de calibración (E9), que requieren sitios con verdad de terreno (OQ-07). Un MVP en 3 semanas es viable para E0–E3 y un TRS/MASW *demostrativo*, no para un release certificable.
7. **Stack.** Verificar antes de depender de ellos: soporte SEG-D (no es nativo de ObsPy; requiere paquete adicional), módulo de ondas superficiales de pyGIMLi y los paquetes `pyfoc/fkmig`, cuya existencia o mantenimiento no pude confirmar. El SDD usa implementación propia de f–k/τ–p/phase-shift con `disba` como referencia, lo que evita esa dependencia. Regla: ninguna dependencia entra al `pyproject.toml` sin un test de humo (`V-E0-*`) que la ejercite.
8. **Un detalle de frecuencia de red.** La lista de líneas a vigilar (`mains.freqs_hz`) debe fijarse por sitio (50 o 60 Hz); vigilar ambas es el defecto seguro.


---

## Anexo B — Antipatrones prohibidos (reglas duras, verificadas por tests)

| ID | Prohibición | Verificación |
|---|---|---|
| AP-1 | Relajar un umbral para hacer pasar un sitio | Cambio de umbral sin ADR ⇒ el hash de config difiere del registrado ⇒ reporte marcado `UNCERTIFIED` (V-E8-1) |
| AP-2 | Interpolar canales muertos y reportarlos como válidos | Canal enmascarado ⇒ no entra a ninguna métrica y se reporta; test: reemplazar un muerto por interpolación ⇒ el veredicto no mejora |
| AP-3 | Reportar Vs(z) o dispersión sin banda λ y sin barras de incertidumbre | Esquema JSON exige `valid_band` y `sigma_c` (V-E8-2) |
| AP-4 | Tomografía sin mapa de hits y cobertura angular | El reporte TRS no se genera sin E4.4b (V-E4-18..20) |
| AP-5 | Decisión por un solo score | El estado lo gobierna la lógica (E6.1); el score es solo informativo |
| AP-6 | Umbrales *hardcoded* | Test estático: ningún literal de umbral en `qc_*/trs/masw` fuera de `config` |
| AP-8 | Certificar un reporte con bandera diagnóstica por un bug de UI | `certifiable` hasheado y validado en el generador (V-E8-3) |
| AP-7 | Mezclar datos de calibración y validación | Los corpus de calibración y de V&V usan semillas y sitios disjuntos (V-E9-1) |


---

## Anexo C — Plantilla de configuración (YAML, valores iniciales calibrables)

```yaml
# Perfil por defecto: Vs30. Alternativa 'cimentacion_estandar':
#   project.z_obj_m: 15 ; acq.masw: { n_ch: 24, dx_m: 2.0, x1_list_m: [6, 12, 20], f_geophone_hz: 4.5, site_prior: {vs_min_ms: 200, nu: 0.40} }  -> z_max,cert = min(19.2, 16.0, 16.75) = 16.0 m (cuello: campo cercano)
profile: vs30_sitio
project: { z_obj_m: 30.0, vs30_required: true, vp_range: [200, 6000], vs_range: [60, 2500] }
acq:
  # N=48, dx=2 -> L_eff=96 m ; x1=40, NACD_green=0.5 -> lambda<=80 m ; geofono 2 Hz, Vs_min=180, nu=0.40 -> c(f_low)=169.6 m/s -> lambda=84.8 m
  # z_max,cert = min(38.4, 32.0, 33.9) = 32.0 m >= 30 m (cuello: campo cercano). Con geofono 4.5 Hz el termino 'geophone' cae a 15.1 m (V-E0-8).
  # (physics: Vs30 activo exige L_total = 40 + 94 = 134 m de linea; si no es viable, usar MASW pasivo o aceptar WARN provisional)
  masw: { n_ch: 48, dx_m: 2.0, x1_list_m: [6, 12, 24, 40], f_geophone_hz: 2.0, k_g: 1.0, h_geophone: 0.7, c_min_ms: 80,
          site_prior: { vs_min_ms: 180, nu: 0.40, c_lowfreq_ms: null } }   # null -> cota inferior conservadora (GEOPHONE_BOUND)
  trs:  { n_ch: 24, dx_m: 5.0, n_shots_min: 5, f_geophone_hz: 14 }
common:
  clip:        { warn_frac: 1.0e-4, fail_frac: 1.0e-3, fs_ratio: 0.98 }
  dead:        { eps_rms: 1.0e-3 }
  gain_outlier_mad: 3.5
  snr_db:      { masw_warn: 12, masw_fail: 6, trs_warn: 10, trs_fail: 5 }
  mains:       { freqs_hz: [50, 60], prominence_db: 10 }
  jitter_ms:   { trs: 0.25, masw: 1.0 }
  repeat_rho:  { warn: 0.85, fail: 0.6 }
  geometry:    { tol_pos_m: 0.1, dx_dev_warn: 0.2, dx_dev_fail: 0.5 }
trs:
  picker:   { sta_periods: 1.5, lta_periods: 15, snr_min_db: 6, sigma_max_ms: 2.0 }
  recip:    { tol_abs_ms: 1.0, tol_rel: 0.02, z_crit: 2.0, pass_fraction_warn: 0.9, pass_fraction_fail: 0.7 }
  timedist: { k_max: 3, direct_intercept_tol_ms: 1.0, ransac_k_mad: 3.0 }
  coverage: { n_L: 4.0, kc: 1.5, doi_min_ray_density: 1 }
  tomo:     { chi2_warn: 2.0, chi2_fail: 4.0, max_iter: 5 }
masw:
  alpha_alias: 2.5       # lambda_min = alpha * dx
  alpha_L: 1.0           # lambda_max = alpha * N*dx
  nacd_levels: { green: 0.5, amber: 0.25 }   # estricto: {1.0, 0.5}; direction: higher_is_better (calibrar, V-E5-10)
  kappa_z: 2.5           # z_max = lambda_max / kappa
  snr_spec_min_db: 6
  peak_alpha: 0.01       # prob. de falso pico por frecuencia (I_min estadistico, E5.4b)
  peak_floor: 0.5        # piso operativo; I_min = max(I_min exacto Kluyver(N,alpha,N_eff), peak_floor)
  peak_levels: { green: 0.85, amber: 0.70, n_reference: 24 }   # higher_is_better; si N != n_reference -> levels_uncalibrated_for_N
  bandwidth_oct: { green: 2.0, amber: 1.0 }   # direction: higher_is_better
  cov_median: { warn: 0.05, fail: 0.10 }
  mode_jump_nu: 3.0
decision: { k_warn: 3, na_fraction_warn: 0.3 }
```


---

## Anexo D — Registro de decisiones abiertas (usar defecto y marcar)

| ID | Pregunta | Defecto |
|---|---|---|
| OQ-01 | ¿TRS = refracción? | Sí |
| OQ-02 | ¿Ondas P (vertical) y/o SH (horizontal) en refracción? | P vertical |
| OQ-03 | Formatos reales y modelo de sismógrafo | SEG-2 (adquisición) + SEG-Y rev1 (archivo) + CSV de geometría; miniSEED opcional; **SEG-D fuera de alcance v1** |
| OQ-04 | UI: PySide6+pyqtgraph vs Streamlit | PySide6 |
| OQ-05 | Hardware de referencia | laptop 4 núcleos, 16 GB |
| OQ-06 | ¿Inversión de prueba para MASW? | Opcional (advisory) |
| OQ-07 | Disponibilidad de datos reales con verdad terreno | Pendiente |
| OQ-08 | Normativa a respetar | Perfil configurable. Refracción: guía ASTM D5777. MASW: guías de buena práctica (Foti et al., 2018), sin norma ASTM que yo pueda confirmar. ⚠ ASTM D7400 es de ensayo *downhole* (no MASW): útil como **verdad de terreno** en E9. Clasificación sísmica: la norma local vigente del proyecto (verificar edición) |
| OQ-09 | Umbral mínimo de acuerdo para "abandonar sitio" | PASS global sin FAIL críticos |
| OQ-10 | Uso ingenieril y profundidad objetivo | **Propuesto (revisión 2):** doble propósito: Vs30/clasificación sísmica (`z_obj=30 m`) + perfil Vs(z) para cimentaciones (`z_obj=15 m`). Dos perfiles en Anexo C. *Pendiente de confirmación del proyecto.* |
| OQ-11 | Equipo de campo | **Propuesto:** MASW 24–48 geófonos verticales, `dx=2 m`, `x₁` múltiple, sledge 10 kg o caída de peso; TRS 24 geófonos 14 Hz, `dx=5 m`, 5–7 disparos (extremos, intermedios, off-end). **Limitante conocida:** con geófonos de 4.5 Hz y suelo blando (`Vs_min≈180`), la profundidad MASW activa queda ≈15 m aunque la geometría dé más (V-E0-8); para Vs30 en suelo blando usar 1–2 Hz o MASW pasivo (E11). *Pendiente de confirmación.* |


---

## Anexo E — Definition of Done y hitos

**Hitos con nombres distintos (v1.2):**
| Hito | Alcance | Plazo orientativo | ¿Certificable? |
|---|---|---|---|
| `demo-0.1` | E0–E3 + TRS/MASW demostrativo con UI mínima; banner "NO CERTIFICABLE" | ~3 semanas | **No** |
| `v1.0` | G0–G10 completos, incluida calibración con datos reales (OQ-07) | depende de OQ-07 | Sí |

- Todos los gates G0–G10 `PASSED` con evidencia versionada.
- Cobertura de líneas ≥ 85 % en `core`, `qc_*`, `trs`, `masw`, `decision`.
- `mypy --strict` en `core/`; `ruff` sin avisos.
- Trazabilidad requisito↔test al 100 % (sin requisitos huérfanos).
- ADRs de toda decisión de umbral/modelo.
- Informe de V&V (`docs/vv_report.md`) con: curvas de calibración, matrices de confusión, ROC, resultados con datos reales, limitaciones conocidas y rangos de validez.


---

## Anexo F — Referencias teóricas clave
- Park, C.B., Miller, R.D., Xia, J. (1998/1999). Multichannel analysis of surface waves (MASW); imaging dispersion curves by phase-shift.
- Yoon, S., Rix, G.J. (2009). Near-field effects on array-based surface wave methods with active sources. *JGGE*.
- Haskell, N.A. (1953); Thomson, W.T. (1950): propagadores en medios estratificados.
- Maeda, N. (1985). AIC picker. Allen, R. (1978): STA/LTA.
- Hagedoorn (1959), Palmer (1980): método plus-minus / GRM para refracción.
- Sethian, J.A. (1996): Fast Marching Method. Rücker et al. (2017): pyGIMLi.
- Iglewicz & Hoaglin (1993): detección robusta de outliers.
- Rawlinson et al.: tomografía de tiempos de viaje; Zelt & Smith (1992): incertidumbre.
- Lai & Rix (1998); Foti et al. (2018): *Guidelines for the good practice of surface wave analysis* (INSEA).

> **Nota final para el agente:** este documento define *qué* debe cumplirse y *cómo se demuestra*. Cuando una validación teórica falle, el hallazgo (incluso si implica corregir este documento) es más valioso que un test forzado a pasar. Registrar siempre el hallazgo en `docs/findings.md`.
