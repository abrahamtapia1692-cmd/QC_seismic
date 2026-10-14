# ADR 0001 — Corregir el SDD antes de implementar criterios de aceptación

Fecha: 2026-10-03.
Estado: **incorporado a especificación v1.4**. Autorización de alcance: continuación de la revisión solicitada por el usuario tras comunicar la auditoría. No constituye aprobación experimental de umbrales ni aceptación de campo.

## Problema

La auditoría H01–H30 de v1.3 demuestra errores de definición, interpretaciones y pruebas, además de lagunas de contratos/evidencia. Mantenerlos obligaría a implementar garantías falsas o forzar pruebas.

## Decisión

Conservar v1.3 y su evidencia sin cambios; publicar una especificación v1.4 autosuficiente con estados de calidad/evidencia/aceptación separados, NACD del centro distinto de ratio próximo, ancho de resolución distinto de sigma, planificación distinta de banda observada y objetivos ingenieriles sujetos a evidencia.

Corregir las pruebas imposibles, no relajar sus tolerancias. Mantener IDs y registrar la nueva versión del estimando/alcance. Reordenar dependencias y enumerar todos los IDs en un manifiesto. Añadir validaciones de abstención, datos desconocidos, supersesión y elegibilidad por perfil.

## Derivaciones y contrapruebas

1. Para arreglo regular unilateral, promedio de offsets `x1+(N-1)dx/2`: con N24/dx2/x1=6/lambda48, NACD29/48=0.6041667; x1/lambda=0.125 es otra métrica.
2. Kernel Dirichlet: resolver D=0.5 para amplitud y D²=0.5 para potencia. Para N24, FWHM×Ndx es1.20747567 y0.88655739. Conversión exacta c=f/q da ancho relativo2a/(1-a²). El ancho no es densidad probabilística del centro estimado.
3. Kluyver N12,a=sqrt(-ln0.3/12): cola0.30636168>0.3; Monte Carlo independiente2 millones0.306121. No existe dominancia asintótica global en el rango exigido por v1.3.
4. Tres capas300/600/1500m/s con h5/0.5m y dos capas300/1500 con h5.23385359m tienen mismos primeros tiempos; se retira la exigencia de detección universal de capa oculta.
5. Correlación entre canales limpios con separación dx/lambda=1/3 es cos(2pi/3)=-0.5. Señal limpia cercana a su máximo no demuestra clipping del ADC.
6. Cero falsos PASS en10 casos inaceptables independientes da límite superior unilateral95 % de25.89 %, no5 %.

Ejecuciones y hashes están en [evidencia histórica](../../evidence/audit_plan_v1_3.json); las referencias primarias y límites de lectura están en [auditoría](../findings.md). Las comprobaciones de incorporación documental se generan en `evidence/plan_revision_v1_4.json`.

## Consecuencias

- G0–G10 continúan NOT_RUN: documentos corregidos no equivalen a algoritmos implementados.
- Los tests se implementarán para spec1.4; no reutilizar evidencia v1.3 como PASSED de un estimando cambiado.
- Umbrales empíricos/perfiles permanecen pendientes hasta experimentos prerregistrados y validación independiente. Se conservan metas iniciales razonables con dominio, denominador y CI, no como leyes universales.
- La referencia Rayleigh entregada es aprovechable, pero requiere empaquetado/dependencias y ejecución reproducible en el repositorio.
- La herramienta podrá producir diagnósticos antes de habilitar aceptación operativa; la falta de evidencia nunca se transforma en verde por cantidad de métricas opcionales.
