# Revisión MASW previa a continuar implementación — MASW-R1

Fecha: 2026-10-12. Base: SDD 1.4; suplemento documental `MASW-R1`.
Estado: especificación reforzada, obligaciones adicionales **NOT_RUN**.
**Avance posterior de implementación:** consultar [MASW-R1 inicial](masw_r1_implementation.md).
Los estados y brechas descritos en esta revisión corresponden al momento de la
auditoría; el runner posterior ya evalúa criterios del suplemento y conserva los
pendientes. El manifiesto de diseño mantiene los estados iniciales; la ejecución
actual se registra separadamente.
El [manifiesto complementario](validation_masw_r1.json) registra ocho obligaciones
RM y su correspondencia con los 100 IDs originales. No son ocho pruebas ejecutadas.
La [decisión ADR 0002](adr/0002-masw-r1.md) delimita alcance y migración.

## Dictamen

El SDD es una base defendible para QC diagnóstico. El adjunto identifica necesidades
reales de trazabilidad modal, covarianza y validación ingenieril, pero combina esas
necesidades con requisitos ya presentes y propuestas que introducirían errores.
No debe incorporarse literalmente ni usarse para declarar validación física.

La implementación existente incluye dos forward, kernels por diferencias finitas,
resolución local y ensambles discretos. Su evidencia G0–G5 pertenece a protocolos
sintéticos anteriores a este suplemento. No acredita cobertura de RM-01..08.
El cierre ampliado de G5 queda pendiente; se puede continuar desarrollando diagnóstico
y contratos E6, conservando aceptación operativa deshabilitada.

Alcance de esta revisión: SDD, adjunto, contratos y rutas MASW seleccionadas,
pruebas correspondientes y fuentes primarias accesibles. No es una auditoría
exhaustiva de TRS, de todos los formatos ni de la validez de campo del producto.
No se revisó un documento pedagógico adicional: no fue identificado como entrada.

## Evaluación del adjunto

| Propuesta o afirmación | Resolución |
|---|---|
| Falta un forward estable | Ya exigido en E3.3/V-E3-5 y existe `phase_disba` más FEM. Completar diagnóstico de raíces, autofunciones y alcance modal, RM-01. |
| `det D < 1e-10` universal y matriz siempre 6×6 | Rechazar como contrato general. Tamaño, unidades y escala dependen de formulación; `det(aD)=a^n det(D)` sin cambiar raíces. Usar residuales normalizados y convergencia. |
| Dos capas tienen una solución analítica de referencia | Distinguir ecuación secular implícita de fórmula cerrada universal de c(f). Usar raíz independiente convergida; semiespacio sí dispone de referencia cerrada en casos concretos. |
| disba es un nuevo método espectral independiente de CPS | Corregir: implementa algoritmos de CPS; dos envoltorios del mismo núcleo no son forward independientes. [Documentación oficial](https://github.com/keurfonluu/disba). |
| Kernels y no unicidad ausentes | Ya presentes en E5.4/V-E5-14/16. Formalizar estimando, covarianza y alcance de la inferencia, RM-04/05. |
| Pico del kernel siempre en λ/3, semiespacio resuelto si λ>3z | Rechazar como teoremas/umbrales universales. Dependen del modelo, modo, parámetros y banda. |
| `spread <= z_obj/2` | No adoptar: faltan medida, normalización y calibración. Según cómo se discretice R cambian las unidades; la amplitud del kernel altera el valor no normalizado. D.4 define una alternativa dimensionalmente explícita, todavía diagnóstica. |
| Asíntota fundamental c→Vs de cada material | Incorrecta para los límites Rayleigh de semiespacio aplicables: c→cR(Vp,Vs), no Vs. El propio E0 da cR/Vs≈0.9194 para ν=0.25. Las asíntotas dependen de la existencia/continuación de la rama. |
| Faltan ausencia modal, multiplicidad y FWHM finita | Ya cubiertos documentalmente en V-E5-7/8, E5.3 y E5.1 (`a<1`). Reforzar implementación y medición de falsa confirmación modal, sin duplicar IDs históricos. |
| Continuidad, energía o coherencia confirman M0 | Rechazar como criterio suficiente. Son atributos condicionados; una cresta puede ser mezcla. Separar identidad de modo y confianza, RM-02. |
| Nula de fase para probar M0 frente a M1 | Separar detección bajo ruido de clasificación entre hipótesis modales. Se necesita población con verdad modal, abstención y error condicionado, no reutilizar Kluyver. |
| `kr` aporta criterio distinto de r/λ | `kr=2π(r/λ)` es cambio exacto de escala para la misma c y r. Es útil reportarlo, pero no agrega información ni un corte universal. |
| Siempre kr>2π implica campo lejano | No adoptar como garantía: fuente, banda, estratificación y componente intervienen. Registrar también tamaño de fuente ka y dominio del Green, RM-06. |
| Q y Kramers–Kronig PASS/FAIL en todo registro | No identificables en general desde amplitud de campo o I normalizada. Verificar causalidad del modelo viscoelástico cuando se use; datos/banda insuficientes dejan estado desconocido. |
| Imponer una inversión de producción antes del QC | Fuera de alcance inicial. Sí exigir referencia offline y validación del objetivo Vs30 antes de habilitar dicho perfil. |
| Unión con covarianza, incertidumbre hasta Vs30 y ensambles | Adoptar con correcciones: covarianza conjunta, sesgo, incertidumbre modal, prior, muestreo y discrepancia del modelo deben declararse. |
| Detección universal de modos leaky | No exigir a un solver elástico de raíces reales lo que no puede demostrar. `NOT_ASSESSED/OUT_OF_SCOPE` es válido; ausencia de detección no significa ausencia física. |

## Brechas observadas en el código

| Prioridad | Evidencia inspeccionada | Consecuencia y obligación |
|---|---|---|
| Alta antes de E6 | [MASWProtocol](../geoqc/masw/contracts.py) permite CONFIRMED con cualquier referencia textual no vacía; [report](../geoqc/masw/report.py) la copia. | No hay resolución/verificación de autoridad y alcance de esa referencia en esta ruta. No derivar aceptación de ese flag. RM-02/08. |
| Alta antes de E6 | [DispersionCurve](../geoqc/core/models.py) almacena confianza modal, pero no índice/rama física; [merge_curves](../geoqc/masw/curves.py) compara ese enum y `band_refs`. | Dos curvas CONFIRMED no necesariamente son el mismo modo. Añadir etiqueta modal separada y soporte físico, RM-02/03. |
| Alta antes de fusionar | `merge_curves` usa `hypot(sigma_a,sigma_b)` y no resuelve `covariance_ref`; su salida omite dicha referencia. | Compatibilidad basada en independencia no verificada. La advertencia de limitación no valida la compatibilidad. RM-03. |
| Alta antes de inferencia | [parameter_resolution](../geoqc/masw/engineering.py) devuelve `covariance=G_w G_w^T` bajo damping y blanqueo. | Es propagación de ruido del estimador, no posterior ni incertidumbre total. Puede tender a cero al aumentar damping mientras empeora resolución. RM-04. |
| Alta antes de Vs30 operativo | `ensemble_reference` solo recibe sigmas y usa likelihood diagonal con prior discreto uniforme. | No propaga covarianzas entre frecuencias ni incertidumbre del catálogo/modalidad. RM-05. |
| Media, antes de ampliar dominio | [phase_disba](../geoqc/synth/dispersion.py) fija `mode=0`; FEM calcula la rama de menor autovalor sin devolver autofunción. | No demuestra inventario multimodal ni clasificación leaky. RM-01. |
| Alta para interpretar evidencia | [test_e5_engineering](../tests/synthetic/test_e5_engineering.py) calcula cobertura de intervalos, pero no exige su calibración nominal por estrato; las verdades pertenecen a familias presentes en el catálogo. | El forward FEM es independiente; ese hecho no prueba generalización a parametrizaciones/familias omitidas. Añadir verdades fuera del catálogo y cobertura, RM-05. |
| Alta antes de nuevo cierre | Runner/manifiesto base reconocen 100 IDs y desconocen RM. | Un PASSED del runner anterior no cierra este suplemento. Migrar evaluación/evidencia antes de cierre ampliado, RM-08. |

La CLI mantiene `eligible_for_acceptance=false`; estas brechas no prueban una
aceptación operativa indebida en la versión inspeccionada. Sí comprometerían una
futura decisión que confiara directamente en estas salidas.

## Anexo D normativo — contratos físicos y estadísticos

### D.1 Forward, raíces y dominio

Declarar modelo 1D de sólidos elásticos, isotrópicos, capas horizontales soldadas,
superficie libre y semiespacio; SI al entrar/salir. Fluidos, anisotropía, lateralidad
y viscoelasticidad requieren adaptador/dominio propios o abstención explícita.
Parámetros mínimos: espesores, Vp, Vs, densidad, convención temporal y límites.

Para `u=Re{û(z) exp(iωt-ikx)}`, resolver
`∇·σ + ρω²u=0`, `σ=λ_L tr(ε)I+2με`, `ε=(∇u+∇uᵀ)/2`,
con tracciones nulas en superficie, continuidad de desplazamiento/tracción en
interfaces y decaimiento en profundidad para modos ligados. Una matriz de borde
`B(k,ω;m)` singular expresa la condición modal. Su dimensión depende del método;
la normalización de estados debe distinguir desplazamiento y tracción.

Usar propagación estable (Dunkin/delta, rigidez u otra derivada y verificada).
No aceptar una raíz solo por un determinante pequeño. En formulación matricial,
un residual posible es `||Bv||/(||B|| ||v||)` tras escalado declarado; en FEM,
`||Kv-ω²Mv||/[(||K||+ω²||M||)||v||]`. Comprobar también fronteras e interfaces
con normas y escalas físicas. Un residual pequeño no sustituye convergencia en
velocidad, malla, profundidad, búsqueda ni comparación independiente.

Por rama/frecuencia conservar: método/versión, índice y convención modal,
intervalo de búsqueda, modos solicitados/encontrados, puntos faltantes y motivos,
normalización/residuales disponibles y referencia de convergencia. Comprobar
suficiencia del inventario en la banda/modelos declarados variando búsqueda y
número de ramas; no prometer contar todos los modos físicamente posibles.
Autofunciones usadas para derivadas o seguimiento requieren verificación de
fronteras/normalización; la amplitud absoluta de una autofunción es arbitraria.

Leaky: declarar si el método admite k complejo y condición radiativa saliente.
Un solver de raíces reales no confirma que no existan modos radiantes; registrar
`NOT_ASSESSED` y abstenerse donde su dominio no sea defendible. No convertir una
rama truncada en fundamental por seleccionar la raíz restante. El trabajo de
[Bhaumik y Naskar](https://arxiv.org/abs/2402.00573) distingue modelado del campo
forzado de curvas de vibración libre; su existencia no valida nuestro adaptador.

### D.2 Velocidad aparente, modo y confirmación

Cada punto/segmento distingue `velocity_kind=APPARENT/MODAL_PHASE`, etiqueta
modal (M0/M1/otra según convención, o desconocida), confianza
CONFIRMED/APPARENT/UNKNOWN, técnica/componente/dirección y soporte espacial.
El enum de confianza no reemplaza el índice del modo. La identificación puede
cambiar con frecuencia; una etiqueta global solo vale en segmento homogéneo.

CONFIRMED exige evidencia resuelta, íntegra, vigente y compatible con datos,
protocolo, rama y dominio; una cadena/archivo existente no basta. Registrar
método, alternativas consideradas, autor o calibración, soporte y limitaciones.
La confirmación manual conserva procedencia humana y no equivale a calibración
automática. Si no se verifica, conservar la declaración original por trazabilidad
y emitir resultado efectivo APPARENT/UNKNOWN con motivo.

Continuidad, polarización/autofunciones cuando existan, offsets, observabilidad
y compatibilidad multimodal pueden informar la decisión. Ninguno por sí solo
prueba M0. No exigir que toda curva llegue a una asíntota fuera de banda ni que
los modos crucen siempre: incluir proximidad, osculación e intercambio de cresta
en modelos que realmente los presenten. La prueba debe conocer las ramas del
generador y distinguir mezcla aparente de una velocidad modal.

Prerregistrar falsa confirmación M0 entre casos realmente no-M0, error entre
confirmados, abstención y cobertura por familia/SNR/banda. Umbrales y mínimos
por clase dependen del perfil; quedan pendientes, no reciben defaults numéricos.
La nula del máximo evalúa detección de señal; la clasificación modal tiene otra
población y otro denominador. Toda selección de offset/trayectoria/ventana/modo
posterior a mirar datos integra la búsqueda calibrada o usa evaluación independiente.

### D.3 Covarianza, soporte y unión

Cada curva conserva matriz conjunta o referencia verificable con orden de puntos,
unidades, soporte, origen y estados de conocimiento. `C_d` en c tiene unidades
(m/s)²; al trabajar en log c, usar aproximadamente
`C_logc=diag(1/c) C_c diag(1/c)` solo en el régimen lineal justificado.
Validar simetría, semidefinición positiva, rango y coherencia con sigmas.
Una covarianza singular puede ser física (duplicados); no añadir jitter oculto.

Para diferencias entre curvas alineadas:
`C_Δ=C_a+C_b-C_ab-C_abᵀ`. En un punto,
`var(Δ)=σ_a²+σ_b²-2cov(a,b)`. Cero varianza exige comparación determinista;
covarianza desconocida no se sustituye por independencia tácita. La comparación
conjunta usa rango/soporte identificable y criterio calibrado. Duplicar el mismo
registro no añade información independiente ni estrecha su incertidumbre.

Unión conserva datos y bloques cruzados cuando se conocen; no fuerza un promedio.
Si existe transformación lineal fija `y'=A y`, propagar `C'=A C Aᵀ` y procedencia.
Si A depende de selección por datos, evaluar también el efecto de esa selección.
Puntos interpolados no se convierten en observaciones adicionales. Sin modelo de
covarianza defendible puede mostrarse la unión diagnóstica, con compatibilidad
estadística UNKNOWN y suficiencia no demostrada.

### D.4 Sensibilidad, resolución y clases de incertidumbre

Fijar `d_i=log(c_i/c_ref)` y `m_j=log(Vs_j/Vs_ref)` para el bloque Vs; declarar
Vp, densidad y espesores fijos o incluirlos como parámetros/nuisance con prior.
El Jacobiano discreto es `J_ij=∂d_i/∂m_j`, adimensional. Un kernel continuo
se define por `δd_i=∫K_i(z)δlog Vs(z) dz`, con K en m⁻¹; en capas,
`J_ij=∫capa_j K_i(z) dz`. No confundir J con densidad por metro.
Conservar signo del kernel; normalizar |K| sirve como atributo, no como prueba
de resolución. Comparar derivadas por pasos y perturbaciones independientes,
incluyendo nuisance y continuidad de la rama al perturbar el modelo.

Para derivación local lineal, prior fijo y pérdida cuadrática:

```text
min_δm (δd-Jδm)ᵀ C_d⁻¹ (δd-Jδm) + η² ||Lδm||²
H = Jᵀ C_d⁻¹ J + η² Lᵀ L
G = H⁻¹ Jᵀ C_d⁻¹
R = G J
C_noise = G C_d Gᵀ
```

Resolver sistemas con factorizaciones; no formar inversas por obligación de la
notación. Registrar rango, condicionamiento, escalado, L, η y método para fijarlos.
Si H es singular, declarar subespacio identificable y tratamiento del nulo;
una pseudoinversa no crea información. La derivación supone C_d definida positiva
en el soporte usado; una proyección por rango requiere justificación registrada.

`C_noise` describe dispersión por ruido bajo estimador/prior fijos. No incluye
sesgo regularizador `(R-I)δm_true`, selección modal, modelo equivocado ni variación
de hiperparámetros. En modelo lineal gaussiano con prior gaussiano propio y
precisión `η²LᵀL`, `C_post=H⁻¹` es posterior condicional. No intercambiar C_post
y C_noise. Para no linealidad/multimodalidad usar ensambles o muestreo con
convergencia y cobertura contrastadas, conservando incertidumbre entre hipótesis.
Estas ecuaciones se derivan del problema cuadrático escrito arriba; la
[formulación de Tarantola](https://epubs.siam.org/doi/10.1137/1.9780898717921.ch3)
delimita el uso de aproximaciones gaussianas locales en problemas no lineales.

R caracteriza resolución local en la parametrización declarada. No implica
resolución global ni unicidad. Si se informa anchura espacial, definir primero
kernel de resolución `R_c(z,z')` y cuadratura. Una medida diagnóstica posible es
`ell(z)=sqrt[∫(z-z')²|R_c(z,z')|² dz' / ∫|R_c(z,z')|² dz']`, en metros.
Si se parte de parámetros por capa, transformar R mediante la base/espesores
antes de interpretarlo como R_c. Denominador cero => UNKNOWN. Reportar también
ganancia, centro/sesgo espacial, lóbulos y masa fuera de ROI: un kernel casi nulo
puede ser estrecho sin resolver nada. No se aprueba el umbral `ell<=z_obj/2`.

### D.5 Vs30, modelos compatibles y prior

Método mínimo de referencia offline: likelihood con covarianza defendible,
catálogo/ensamble con pesos de prior explícitos, control de densidad de muestreo,
modelos alternativos y estudio de expansión del dominio. Si no converge o no hay
modelos compatibles, resultado no demostrado. No se prescribe MCMC ni Occam
como garantía; cualquier método propuesto debe demostrar su cobertura y límites.
Un conjunto de modelos aceptables sin pesos probabilísticos no genera por sí
solo un intervalo de probabilidad 95 %.

Para espesor fijo recortado a 30 m, `T=Σh_j/Vs_j`, `Vs30=30/T` y
`∂Vs30/∂log Vs_j=30 h_j/(T² Vs_j)`. Aproximación local:
`var(Vs30)=gᵀ C_m g`, declarando la clase de C_m. Si espesores/profundidades son
inciertos, incluir sus derivadas/covarianzas o integrar muestras; el recorte a
30 m es no suave cuando cambia la capa que contiene esa profundidad.
Cuantiles de Vs30 se calculan sobre cada modelo completo, con incertidumbre de
modo/modelo/prior cuando aplique; promediar curvas o perfiles primero cambia el estimando.

Evaluar exactitud, sesgo y cobertura nominal por estrato; no exigir insesgamiento
universal a un estimador regularizado. Usar verdades ausentes del catálogo,
alternativas de parametrización, nuisance y banda limitada. Separar incertidumbre
del perfil Vs(z) de incertidumbre del funcional Vs30: un objetivo puede estar
mejor determinado que cada capa. No exigir unicidad global del perfil para todo
objetivo ni declarar UNIQUE desde una búsqueda finita. Estados recomendados:
`NON_UNIQUE_DEMONSTRATED`, `UNRESOLVED`, `CONSTRAINED_WITHIN_DECLARED_FAMILY`.
La [inversión por búsqueda directa de Wathelet et al.](https://geopsy.org/publi/Wathelet2004.pdf)
documenta no unicidad y dependencia de las restricciones; no convierte nuestro
catálogo discreto en una distribución posterior de campo validada.

### D.6 Campo cercano, fuente, atenuación y lateralidad

Por frecuencia/rama y receptores activos registrar `kr_j=2πr_j/λ`, distribución
de offsets, near_offset_ratio y NACD_center. Con fuente de escala a, registrar
`ka=2πa/λ`, forma, tipo, componente, espectro y dominio. `kr_min` solo equivale
a `2π near_offset_ratio` bajo las mismas definiciones; con modo desconocido,
usar longitud de onda aparente etiquetada, sin confirmar régimen físico.

Separar pruebas de fuente finita/puntual, término cilíndrico lejano e interferencia
P/S/R. El Green homogéneo existente cubre su dominio explícito; fuera de él no
calibra sesgo estratificado. Declarar dominio no demostrado es aceptable; no se
obliga aquí a implementar todo Green estratificado antes de diagnóstico.
El artículo de [Rahimi, Wood e Himel](https://doi.org/10.1093/gji/ggac011)
se mantiene como referencia bibliográfica; su página editorial no fue accesible
en esta revisión y no se extrae de ella ningún nuevo umbral.

`alpha≈πf/(Qc)` es atenuación modal débil aproximada, no identificación directa
de Q material. Si se usa, documentar banda/error de aproximación y Q supuesto o
medido. La dispersión geométrica elástica por capas existe aun sin absorción.
La fase normalizada de una única onda conserva I bajo factores positivos de
amplitud por canal con soporte fijo; atenuación sí puede alterar SNR, soporte y
mezcla modal. Una caída de amplitud no identifica Q sin fuente/geometría/gain.

Para viscoelasticidad física emplear módulo complejo causal con convención de
signo y frecuencia de referencia; evaluar dispersión y absorción juntas. Una
prueba de Kramers–Kronig de banda finita necesita hipótesis sobre colas y estimando;
no exigir PASS/FAIL a cualquier registro MASW. [Mikhaltsevitch et al.](https://agupubs.onlinelibrary.wiley.com/doi/10.1002/2016GL069269)
validan una relación local en mediciones de laboratorio específicas, no un test
universal de adquisición. Ausencia de información => UNKNOWN/UNCALIBRATED.

Geometría colineal no prueba subsuelo 1D. Cambios con offset/dirección o ventana
pueden responder a lateralidad, fuente o modalidad. Con evidencia insuficiente,
reportar c aparente y validez 1D UNKNOWN/MODEL_INAPPLICABLE según fundamento;
una buena cresta no habilita automáticamente inversión 1D ni Vs30 representativo.

### D.7 Obligaciones y secuencia de implementación

Los criterios siguientes se incorporan de forma aditiva. Todos están NOT_RUN
en el manifiesto complementario, incluso si existe implementación parcial.
Antes de su ejecución deben fijarse tolerancias numéricas, estimandos y poblaciones
en protocolo versionado. No inventar límites empíricos para convertir esta revisión
en una aprobación automática.

| ID | Cierre requerido | Pruebas base afectadas |
|---|---|---|
| RM-01 | Referencia de semiespacio y capas convergida; residuales escalados/autofunciones cuando se usen; seguimiento e inventario multimodal o exclusión explícita; leaky no evaluado no se informa ausente. | V-E3-5/6, V-E5-7/8 |
| RM-02 | Separar etiqueta/confianza por punto; referencia inexistente, alterada o incompatible nunca confirma; M0 ausente/débil, cresta mezclada y ramas cercanas con verdad independiente, abstención y falsas confirmaciones. | V-E0-9, V-E5-7/8/18/21 |
| RM-03 | Unión conserva covarianza/orden/procedencia; duplicados no añaden precisión; errores correlacionados cambian prueba de diferencia; desconocidos se abstienen; CONFIRMED de M0 y M1 no permite fusionar. | V-E5-11/13/22 |
| RM-04 | J con parámetros/unidades y convergencia; caso lineal independiente comprueba G/R/C_noise/C_post/sesgo; damping alto no implica precisión total; matriz singular y nulo explícitos; anchura espacial con base/medida y refinamiento. | V-E5-11/14 |
| RM-05 | Ensamble con C_d conjunta/prior trazable; propagación Vs30 por derivada y Monte Carlo independiente; no unicidad, verdades fuera de catálogo, error/sesgo/cobertura por estrato y sensibilidad al prior; sin probabilidad inventada para ensembles sin pesos. | V-E5-14/15/16, V-E9-1/7 |
| RM-06 | Identidades kr/ratios y ka; barrido del dominio de fuente/medio contra Green convergido; atenuación fenomenológica vs modelo causal, Q no identificable; abstención fuera de dominio y ausencia de corte universal kr. | V-E3-8, V-E5-9/10 |
| RM-07 | Distinguir velocidad aparente/modal y aplicabilidad 1D; controles de lateralidad/mezcla/fuente con etiquetas independientes; familia de búsqueda incluye toda selección adaptativa usada o evaluación independiente; perfiles fuera de alcance no aceptan. | V-E5-17b/18/21/22, V-E9-7 |
| RM-08 | Migrar esquemas y runner para leer revisión+suplemento; preservar evidencia original; referencia de revisión/hash obligatoria; prueba que PASSED base, flag JSON o RM omitida/skipped no cierran alcance ampliado; decisión/reportes verifican fuente de confianza. | V-E0-9/10, V-E6-1/4, V-E8-3/4 |

Orden recomendado: RM-08 (contratos/evidencia) y RM-02/03 antes de conectar salidas
MASW a E6; RM-01/04 antes de ampliar inferencia; RM-05 antes de suficiencia Vs30;
RM-06/07 antes de declarar los respectivos dominios validados. Preparar protocolos
y nuevas pruebas significativas, observar fallos y luego implementar (TDD).
El cierre ampliado requiere todas las RM, además de dependencias/pruebas base.
G9 sigue siendo obligatorio para cualquier aceptación de campo.

### D.8 Versiones, evidencia y reproducción

La revisión científica se identifica por `(specification_version=1.4,
document_revision=MASW-R1, supplement_hash)`. No cambia por sí misma el esquema
de los objetos runtime; los nuevos campos necesitan migración explícita antes
de implementar. Los 100 IDs y los artefactos antiguos permanecen intactos;
el manifiesto complementario contiene ocho obligaciones adicionales, sin fingir
que el runner actual las evalúa. Hasta migrarlo, solo puede verificar el alcance base.

El [SDD anterior al suplemento](archive/SDD_v1_4_before_masw_r1.md) conserva el
texto inspeccionado. El [verificador documental](validate_masw_r1.py) revisa
integridad, vínculos/IDs y contrapruebas algebraicas acotadas. Su resultado se
escribe en [evidence/masw_review_r1.json](../evidence/masw_review_r1.json);
no ejecuta ni aprueba las obligaciones RM ni G5/G9.

```powershell
.\.venv\Scripts\python.exe docs/validate_plan_v1_4.py
.\.venv\Scripts\python.exe docs/validate_masw_r1.py
```

La validación documental y las contrapruebas no sustituyen una nueva suite de
implementación. En esta revisión se ejecutó:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_e5_boundaries.py tests/synthetic/test_e5_curves.py -q
```

Resultado observado: **15 passed in 63.66s**, sin skips. No se reejecutó la suite
completa G0–G5 ni G9. Pasar estas pruebas existentes no cierra los contratos RM.
Las sondas del verificador reprodujeron aceptación de referencia modal textual
sin resolver, compatibilidad sin covarianza cruzada y pérdida de la referencia
de covarianza en la unión; la aceptación de campo siguió deshabilitada.
