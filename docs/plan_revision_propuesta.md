# Propuesta de revisión del SDD posterior a la auditoría v1.3

Fecha: 2026-10-03. **Estado: propuesta histórica incorporada a la [especificación v1.4](../SDD_QC_Geofisico_MASW_TRS_v1_4.md).** Se conserva para trazabilidad; el documento consolidado vigente es la v1.4. Esta propuesta no aprueba umbrales experimentales. Las fórmulas verificables se distinguen de hipótesis pendientes de calibración y de los [hallazgos H01–H30](findings.md).

## 1. Objetivo y significado de resultados

Objetivo propuesto: evaluar calidad de adquisición y suficiencia **demostrada** de la evidencia para objetivos explícitos, con incertidumbre y acciones. No usar un control de adquisición como prueba de unicidad del subsuelo o del valor correcto de Vs30.

Representar por separado:

- `quality_status`: PASS/WARN/FAIL, para comprobaciones aplicables ejecutadas.
- `evidence_status`: COMPLETE/INCOMPLETE/OUT_OF_SCOPE, relativo a requisitos obligatorios.
- `eligible_for_acceptance`: booleano derivado de requisitos y evidencia; nunca recibido como orden de la UI.
- `operator_decision`: pendiente/aceptado/repetir/ampliar, con responsable, fecha, alcance y salvedades.

Un resultado INCOMPLETE no puede habilitar el semáforo verde de suficiencia. Un diagnóstico fallido debe poder exportarse sin autorización de aceptación. La decisión de abandonar el sitio necesita los requisitos del proyecto y criterio del responsable.

## 2. Matemática y estados de planificación

Definir receptores activos `A`, distancias reales `r_j`, dirección/componente y criterios de validez antes de calcular:

```text
lambda(f)       = c(f) / f
nacd_center(f)  = mean_{j in A}(r_j) / lambda(f)
near_ratio(f)   = min_{j in A}(r_j) / lambda(f)

# Solo arreglo regular, unilateral, completo:
L_ap            = (N - 1) dx
L_eff           = N dx                 # escala del kernel rectangular regular
r_mean          = x1 + L_ap/2
L_total         = x1 + L_ap
```

Los umbrales de ambos ratios son parámetros diferentes. No trasladar 0.5/0.25 a la definición corregida sin calibración. En arreglos irregulares, evaluar el kernel con posiciones reales y pesos; L_eff no reemplaza esa evaluación. Declarar si q se mide en ciclos/m o k en rad/m.

Planificación devuelve escenarios nominales con rango de priors, fuentes e instrumentación, no profundidad certificada. La banda prevista tiene que ser no vacía y cumplir ambos extremos del objetivo. Clasificaciones propuestas:

| Estado | Significado |
|---|---|
| FEASIBLE_UNDER_ASSUMPTIONS | La envolvente del escenario permite el objetivo; falta evidencia de campo |
| NOT_DEMONSTRATED | Priors o instrumentación no bastan para demostrarlo |
| INCOMPATIBLE_WITH_ASSUMPTIONS | Restricciones adoptadas contradicen el objetivo |

Reservar un rechazo definitivo para condiciones efectivamente demostradas, como geometría/muestreo incompatibles con el alcance adoptado. Una cota inferior que no alcanza el objetivo no demuestra imposibilidad física.

## 3. Banda observada y resolución

Calcular por disparo/componente/dirección `B_s`, con máscaras separadas para:

- Datos utilizables, respuesta relativa conocida y SNR observado válido.
- Muestreo espacial/temporal y ambigüedades del arreglo real.
- Contaminación cercana bajo un modelo validado.
- Significancia contra una nula adecuada a la dependencia real.
- Identidad modal confirmada o curva aparente marcada.
- Continuidad y precisión de estimación calibrada.

Combinar bandas únicamente con trazabilidad por punto y consistencia entre registros en sus solapes. La unión no rellena huecos ni establece el modo en segmentos incompatibles. Informar `lambda_max_observed` del segmento admisible y `nominal_depth=lambda_max_observed/kappa_z` como alcance aproximado condicionado, separado de resolución del objetivo.

Mantener el kernel como resolución espectral:

```text
D_N(Delta q) = |sin(pi N dx Delta q)/(N sin(pi dx Delta q))|

FWHM_q(amplitud) ~ 1.20671/(N dx)   # límite de N grande
FWHM_q(potencia) ~ 0.885893/(N dx)

a = (FWHM_q/2) / q0
FWHM_c/c0 = 2a/(1-a^2)              # ambas fronteras positivas
```

Para N finito calcular raíces del kernel; para anchos grandes reportar fronteras asimétricas. No definir `sigma_c` como FWHM dividido por 2.355. La incertidumbre de `c_pick` debe venir de un modelo estadístico/repeticiones calibradas, con sesgo y covarianza entre frecuencias. La identificación modal necesita una prueba aparte.

## 4. Nula del phase-shift y muestreo de incertidumbre

Para receptores independientes, fases uniformes y peso unitario, la integral de Kluyver sigue siendo una referencia válida para el módulo normalizado. Definir explícitamente `Q_N` para `R/N`, no para R. Los cuantiles confirmados de cola 0.0005 son 0.744483/0.545573/0.392000 para N=12/24/48.

Retirar la afirmación de que `exp(-N a²)` es siempre una cota superior. Verificar numéricamente su error en el dominio declarado. Contrastar proporciones con intervalos binomiales y controlar la multiplicidad de las comparaciones.

Separar número de receptores activos, dependencia de canales y número de hipótesis buscadas. Para ruido correlacionado, calibrar la nula del máximo de la búsqueda completa con datos/surrogates que preserven dicha correlación. No repararla solo cambiando el número de velocidades. Registrar si el falso pico se controla por frecuencia o por registro y cuál es la unidad de validación.

Bootstrap/jackknife son herramientas condicionadas: documentar unidad de remuestreo, dependencia y cambios de geometría. No asumir que su fórmula nominal proporciona intervalos calibrados sin comprobar cobertura y sesgo.

## 5. TRS: hipótesis observables y abstención

Especificar por fórmula hipótesis de topografía, lateralidad, isotropía, rama y dominio angular. Separar el control de calidad de un diagnóstico geológico. Añadir pruebas donde dos modelos tienen los mismos primeros arribos: el comportamiento correcto es reconocer la no identificabilidad del fenómeno, no inventar un detector.

Definir el onset de la fuente como verdad causal independiente del centro de una Ricker. Validar el picker con señal causal, instrumento y filtrado especificados. Invertir polaridad no invalida automáticamente el tiempo; sí genera un diagnóstico de sensor cuando está demostrado.

Reciprocidad:

```text
Delta = t_AB - t_BA
var(Delta) = var(t_AB) + var(t_BA) - 2 cov(t_AB, t_BA)
```

Incluir errores compartidos de fuente/clock/geometría. No dividir por sigma cero. Evaluar tolerancia operativa y potencia de detección por separado. Una diferencia bajo tolerancia con sigma grande significa evidencia débil. Exigir el par recíproco físico, no inferirlo por el orden de archivos. Una atribución única de causa requiere suficientes observaciones y un modelo identificable.

Hits, tensor angular y DWS son atributos de cobertura. Complementar con resolución/ensembles y registrar modelo de rayos. El misfit normalizado se reporta como tal, junto con convergencia; no garantiza modelo correcto. Distinguir solver propio FMM y forward de la inversión de referencia.

## 6. QC común y unidades

Confirmar clipping mediante escala/rails conocidos. Sin ellos, clasificar sospecha y conservar su evidencia, no convertir máximo observado en ADC confirmado. Calcular fracciones con la misma ventana en numerador y denominador.

Corregir polaridad usando alineación física y controles multibanda/repeticiones, y reportar amplitud/acople como diagnósticos de causas múltiples. Definir casos MAD=0, RMS=0, offset=0 y canales completamente inválidos.

Unificar estimandos de SNR:

```text
SNR_net_linear = (P_total_signal_window - P_noise)_+ / P_noise
SNR_total_linear = P_total_signal_window / P_noise
SNR_db = 10 log10(SNR_linear)

N_req = ceil(N_actual * 10^((SNR_target_db-SNR_actual_db)/10))
```

La sugerencia N_req aplica solo cuando ruido y señal cumplen el modelo de stack independiente y comparable. Valores censurados, ruido cero y ventanas ausentes necesitan estados específicos. La recomendación debe registrar esos supuestos.

Definir dt y delay representables por formato; cuantización en I/O con error documentado. No afirmar amplitudes físicamente comparables sin ganancia/stack/unidades conocidas. Para miniSEED, definir revisión y sidecars de fuente/geometría/instrumentación.

## 7. Datos y configuración antes de los algoritmos

Ampliar contratos para contener tiempo por canal, geometría completa, incertidumbre, componente, máscaras, procedencia, respuesta, unidades y tipo de stack. Agregar modelos de picks, curvas con bandas/mode_identity/sigma/covarianza, cobertura y evidencia de objetivo.

Cada métrica debe declarar `mandatory`, `critical`, `applicability`, `validity`, `reason`, `direction`, umbrales con inclusión de frontera, versión de calibración y acciones. La configuración debe contener todos los parámetros usados; los comentarios no sustituyen claves YAML. No aprobar niveles de coherencia de N=24 en un perfil de N=48 sin calibración.

Separar COV de precisión y COV entre disparos. Congelar contenido mutable donde se prometa inmutabilidad y especificar representación JSON/digest. Reportes inválidos de ingesta no requieren construir un Shot ficticio.

## 8. Reglas completas de decisión

Reglas propuestas a convertir en una tabla de verdad explícita:

1. Un FAIL crítico sin resolución válida impide aceptación del requisito afectado.
2. Un requisito obligatorio faltante/invalidado produce evidencia INCOMPLETE y no permite verde de suficiencia.
3. Un FAIL aplicable no puede mejorar el estado previo de la métrica ni del ámbito; definir cómo se propaga si no es crítico.
4. Cada WARN aplicable produce una salvedad visible; definir cuáles bloquean aceptación. `k_warn` puede escalar advertencias opcionales, pero no borrar una salvedad obligatoria.
5. NA solo excluye del denominador requisitos realmente no aplicables. Ausencia o fallo de una prueba aplicable es otro estado de evidencia.
6. Agregar por requisitos de técnica/objetivo y cobertura espacial. Un registro repetido puede sustituir otro para el requisito si se cumplen condiciones explícitas; ambos permanecen en la bitácora.
7. El score sigue siendo informativo; elegibilidad se deriva del manifiesto y de evidencia vigente. La UI no puede forzar flags ni el generador PDF aceptarlos sin validación.

## 9. Dependencias y gates

Sustituir el orden lineal por fases con dependencias explícitas:

```text
A. Contratos, unidades, entorno y referencias analíticas mínimas
B. Ingesta + generadores/inyección independientes para validar QC común
C. QC común validado en el dominio sintético declarado
D. TRS/MASW + generadores físicos necesarios + validación de cada módulo
E. Reglas, interfaz y reportes con manifiesto de evidencia
F. Calibración + holdout por sitio + utilidad ingenieril + rendimiento
G. Empaquetado y aceptación operativa en el alcance demostrado
```

Mantener IDs existentes donde correspondan y renumerar etapas con tabla de migración. Generar gates desde una lista de IDs obligatorios, incluyendo los omitidos G4/18..21, G5/17..20 y 17b, G6/4..5 y G8/3. Definir gates de implementación distintos de los de validación; ningún SKIPPED obligatorio cierra un gate.

Un script de auditoría o un test que escribe PASSED no aprueba toda una subetapa. La evidencia agregada debe derivarse de resultados actuales, entradas/configuración/código identificados y estado de todas las pruebas requeridas.

## 10. Criterios de V&V pendientes

Prespecificar escenarios, denominadores y tamaños por tipo de falla. Separar calibración y validación por sitios y familias geológicas. Informar falsos PASS entre casos realmente inaceptables con intervalo y agrupación por sitio; diez sitios no sostienen por sí solos un límite del 5 %.

Exigir evidencia de utilidad Vs30 cuando se habilite ese perfil: ensembles/inversión de referencia y error de la media armónica en modelos independientes, además de verificación de campo. La inversión de referencia puede quedar offline, pero esa validación no puede ser opcional si se promete suficiencia para el objetivo.

Definir duración pre/posttrigger, banda/muestreo y hardware/condiciones del benchmark. Medir por disparo y por tendido, tiempo de primera ejecución y de caché, concurrencia, cancelación y tamaño máximo admitido. Evitar criterios de latencia incompatibles con más disparos obligatorios o con compilación inicial.

Se mantienen abiertos hasta medirlos: umbrales de campo cercano, resolución útil en profundidad, identidad modal en casos difíciles, calibración de incertidumbre, error Vs30, comportamiento de ruido real, tasas de falsos PASS y tiempos en hardware de referencia. La auditoría ya aporta contraejemplos y cambios documentales concretos; estos puntos requieren evidencia nueva.
