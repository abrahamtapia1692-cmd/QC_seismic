# Protocolo MASW-R1 — primera implementación

Prerregistrado 2026-10-12 antes de ejecutar pruebas nuevas. Alcance: contratos
de evidencia modal, unión diagnóstica con covarianza y evaluación del suplemento.
No calibra un clasificador modal ni habilita E6/G9.

RM-02: referencia textual sin resolver, contenido alterado/rehasheado sin actualizar
autoridad, revocación, revisión/modelo/dirección/datos/soporte incompatibles => UNKNOWN.
Una aprobación externa explícita ligada al contenido permite confirmar únicamente
los puntos/etiquetas que cubre; ausencia de energía se conserva UNKNOWN. La autoridad
entra por dependencia de la aplicación, nunca desde el payload científico. Pendiente
la cohorte independiente de falsas confirmaciones/abstención del clasificador modal.

RM-03: ejemplo c=(100,101), sigma=(1,1), rho=0.99 frente a independencia.
Tres sigmas es criterio ilustrativo explícito de prueba, no umbral operativo.
Verificar C_delta=Ca+Cb-Cab-Cab^T, también para varias frecuencias; errores de
aritmética matricial rtol=1e-12/atol=1e-12 en las unidades mostradas. PSD/simetría
con tolerancia de redondeo 64 eps n ||C||2; no añadir ruido diagonal. Rango por la
misma escala numérica. Singularidad y discrepancia en espacio nulo son explícitas.
Duplicados comparten identidad de observación y no multiplican información.
Comparación desconocida si faltan modo, soporte, matriz o criterio. Conservar
matrices/referencias, orden y procedencia; no promediar ni interpolar puntos.

RM-08: conservar contratos 1.4 al leer; migración explícita a curva 1.4-r1 sin
inventar modo físico ni covarianza. Reporte nuevo 1.4-r1. Evidencia de ejecución
vinculada a revisión, suplemento, protocolo, código y casos realmente ejecutados.
Skip, omisión, resultado sin fases de pytest o revisión/hash distintos no aprueban.
Resultados base y ampliados separados; cualquier RM pendiente impide G5 ampliado.
Escribir nuevas ejecuciones en carpetas únicas; no sobrescribir evidence/e5.

Los IDs base siguen identificando obligaciones históricas. Marcador adicional
`rm(id, criterion)` identifica criterios de suplemento en casos ejecutados.
El evaluador exige todos los criterios registrados y fases setup/call/teardown
PASSED; las declaraciones JSON de estado por sí solas no bastan. Los resultados
se consumen desde la ejecución confiable del runner, no desde un reporte del usuario.
