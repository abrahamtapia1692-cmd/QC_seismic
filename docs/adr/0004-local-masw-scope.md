# ADR 0004 — alcance inicial de la aplicación local MASW

Fecha: 2026-10-14. Estado: adoptado para iniciar el desarrollo local solicitado.
Especificación: [APP-LOCAL-0.1](../../app.md).
Antecedentes: [auditoría de arquitectura](../auditoria_arquitectura_app_2026_10_14.md) y [ADR 0003](0003-masw-diagnostic-usability.md).

## Contexto

Se necesita un primer recorrido implementable sin trasladar a la aplicación las suposiciones de los generadores históricos. El núcleo ya dispone de ingesta SEG-Y/SEG-2 con metadatos explícitos. Oysand está en ASCII y su adaptación exploratoria no construye un Shot plenamente validado. El ejemplo sintético E5 proporciona SEG-Y, sidecar y protocolo, pero no representa un segundo sitio de campo ni calibración empírica.

La propuesta preliminar mezclaba aprobación con suficiencia y suponía garantías de entrega y atomicidad que requieren protocolos adicionales. Distribuir todo el dominio en servicios desde el primer día aumentaría el trabajo operativo antes de verificar el cálculo reutilizable.

## Decisiones

1. El primer hito cubre MASW diagnóstica: carga, cálculo, dosier y anotación humana. La primera interfaz es Web; Android reutilizará contratos y semántica después.
2. El formato de carga inicial es el subconjunto SEG-Y rev0/1 ya soportado, con sidecar JSON obligatorio. Otros formatos requieren ampliación explícita del contrato.
3. Oysand es referencia de regresión del procesamiento actual. E5 es el primer caso del flujo validado y una prueba técnica independiente de las constantes Oysand. Un segundo sitio MASW real sigue pendiente para validación posterior.
4. Se implementará primero un adaptador científico con entradas tipadas y protocolo/política explícitos. No depende de HTTP, SQL, carpetas de ejemplos ni renderizadores. El procesamiento exploratorio Oysand conserva su naturaleza y faltantes.
5. Calidad, revisión y suficiencia mantienen estados separados. ACCEPTED es una anotación diagnóstica con salvedades. No habilita elegibilidad ni suficiencia demostrada.
6. El backend inicial será modular, con PostgreSQL y un worker separado del ciclo HTTP. Los trabajos se reclamarán de forma durable desde PostgreSQL con lease/token. No se introduce un broker externo como requisito inicial.
7. Los archivos locales se gestionarán mediante un puerto de almacenamiento, zona temporal, referencias finales no sobrescribibles y manifiestos confirmados. S3/MinIO y carga resumible se añadirán después.
8. La revisión se confirma con OCC atómico y efectos idempotentes. Trabajo, historia, cambios y outbox se registran con sus transacciones de dominio. Avisos y exportaciones no determinan la validez del resultado científico.
9. El estado de servidor se recupera inicialmente por HTTP. Registro de cambios por cursor y cache persistente serán condiciones previas de Android; push y WebSocket no serán fuente de verdad.
10. El primer desarrollo de código posterior a este ADR será la caracterización/extracción del adaptador, con comparación científica y evidencia nueva. No se modifica la evidencia histórica para acomodar una refactorización.

## Alternativas consideradas

| Alternativa | Motivo de la decisión |
| --- | --- |
| Habilitar solo ASCII Oysand como entrada de aplicación | Dejaría el flujo ligado a un conjunto exploratorio con metadatos incompletos |
| Convertir Oysand a SEG-Y y completar metadatos predeterminados | Inventaría evidencia científica y ocultaría faltantes |
| Usar E5 como validación de otro sitio de campo | Un experimento sintético comprueba integración, no generalización empírica |
| Envolver directamente los scripts de dosier | Mantendría rutas, políticas globales y carga/renderizado acoplados al cálculo |
| Microservicios, broker y cloud desde el comienzo | Añadiría decisiones de operación antes de verificar el primer recorrido local |
| SQLite o una cola solo en memoria para el hito transaccional | No comprobaría con la base elegida las reglas de concurrencia y recuperación requeridas |
| Web y Android completos simultáneamente | Aumentaría interfaces a mantener mientras los contratos aún se están implementando |

## Consecuencias

La extracción inicial requiere pruebas de caracterización y un mapeo explícito entre contratos de dosier y núcleo. No se presupone que sus curvas sean idénticas cuando cambian bins o refinamiento. El paquete científico puede desarrollarse y verificarse sin servidor o Docker; el hito transaccional sí requiere PostgreSQL.

El primer sistema local tendrá límites conservadores de admisión y carecerá de capacidades cloud/móvil completas. Esos límites no son reglas geofísicas ni capacidad medida. Los puertos y manifiestos permiten evolucionar almacenamiento y transporte sin cambiar el significado científico.

No se introduce C++, no se elige todavía framework móvil y no se declara aceptación operativa de campo. Los gates científicos existentes conservan su estado.

## Verificación y revisión de esta decisión

Los criterios APP-01 a APP-16 de la especificación son obligatorios para el primer hito integrado y están inicialmente NOT_RUN. Este ADR no afirma que hayan pasado.

Revisar la elección de cola/procesos cuando mediciones de carga, despliegue o aislamiento justifiquen otro broker. Revisar almacenamiento al necesitar carga directa/resumible o despliegue en varias máquinas. Revisar clientes al comenzar Android, resolviendo cache, cambios, compatibilidad y ciclo de vida de archivos. Cualquier ampliación de técnica/formato o aceptación científica exige actualizar alcance y verificaciones.
