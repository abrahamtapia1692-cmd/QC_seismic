# Decisiones abiertas — SDD v1.4

Fecha: 2026-10-03. Este registro contiene propuestas de trabajo, no decisiones de campo confirmadas. Se puede implementar contrato/diagnóstico antes de resolverlas; las que afectan un perfil bloquean su aceptación operativa hasta documentar resolución y evidencia.

| ID | Decisión pendiente | Propuesta de trabajo | Momento de resolución |
|---|---|---|---|
| OQ-01 | Significado de TRS en el proyecto | Tomografía de refracción sísmica P | Antes de habilitar perfil real TRS |
| OQ-02 | Ondas/componentes requeridas | Rayleigh vertical MASW y P TRS; SH/Love fuera del perfil inicial | Ingesta/perfil de adquisición |
| OQ-03 | Equipo, formatos, headers y convenios de tiempo | SEG-2 y SEG-Y rev0/1, CSV/manifiesto; miniSEED opcional con sidecar | G1 del formato real |
| OQ-04 | Interfaz y despliegue | CLI headless primero, PySide6/pyqtgraph después | Antes de G7 |
| OQ-05 | Hardware de referencia y SO | Laptop4 núcleos/16GB como candidato; falta modelo exacto, threads y plataforma | Protocolo de rendimiento antes de G4/5/9 |
| OQ-06 | Inversión en operación de campo | Opcional; validación offline de utilidad ingenieril obligatoria para perfil Vs30 | Antes de aceptar objetivo Vs30 |
| OQ-07 | Corpus real y verdad independiente | Corpus público preliminar Oysand/Chevremont descargado y probado exploratoriamente; falta corpus representativo con verdad independiente; piloto≥10 sitios no prueba falso PASS≤5 % | G9 |
| OQ-08 | Normativa local/edición y obligaciones de entrega | Referencias de método no equivalen a conformidad; identificar norma del proyecto | Definición de perfil operativo |
| OQ-09 | Requisitos y autoridad para abandonar sitio | Evidencia completa/calibrada y responsable de campo; advertencias no desaparecen por aceptación manual | Perfil/bitácora antes de operación |
| OQ-10 | Objetivo ingenieril, ROI y representatividad | Vs30 a30m y cimentación a15m como perfiles candidatos; técnicas obligatorias según objetivo | Antes de aceptar levantamiento |
| OQ-11 | Geometría, geófonos y fuente reales | Escenarios24/48ch; frecuencia natural no es corte físico; falta cadena instrumental/calibración | Planificación y corpus real |
| OQ-12 | Generador independiente de campo cercano | Green validado o solver de onda completa con convergencia; una curva disba no basta | V-E3-8 y G5 |
| OQ-13 | Umbrales/estimadores por población de sitio | Registro completo con dirección/unidades/fronteras, versión y dominio; candidatos heredados no calibrados | E0 contrato; G9 uso operativo |
| OQ-14 | Diseño estadístico y unidades independientes | Separar por sitio/familia, CI y potencia; no tratar disparos del mismo sitio como independientes | Antes de fijar calibración/holdout |
| OQ-15 | Autenticidad de reportes exigida | Hash científico reproducible; firma/registro confiable solo si el proyecto requiere autenticidad | Antes de G8 del alcance correspondiente |
| OQ-16 | Autoridad y protocolo de confirmación modal | MASW-R1 exige etiqueta de modo separada de confianza, referencia verificada y población/criterios de falsa confirmación; no basta texto libre | RM-02 y antes de usar CONFIRMED en E6 |
| OQ-17 | Referencia Vs30 y cobertura fuera del catálogo | Covarianza conjunta, nuisance, prior, familias holdout, sesgo/cobertura y objetivo definidos antes de calibrar | RM-04/05 y G9 del perfil Vs30 |
| OQ-18 | Dominios MASW 1D, fuente y atenuación habilitados | Mantener alcance homogéneo del Green existente; definir evidencia para estratificación, lateralidad, Q y ramas fuera del solver | RM-01/06/07 antes de ampliar dominio |

Toda resolución registra fecha, responsable, fundamento, artefactos y efectos en config/pruebas/calibración. Cambiar una decisión que afecte aceptación invalida evidencia incompatible; no borra resultados históricos.
