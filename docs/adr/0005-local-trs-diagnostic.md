# ADR 0005 — ampliación local TRS diagnóstica

Fecha: 2026-10-19. Estado: adoptado por solicitud explícita de procesar los KM
como TRS, refracción y tiempos de llegada.

El ADR 0004 estableció MASW como primer recorrido. Los KM son adquisiciones TRS;
su reutilización exploratoria para MASW no satisface la intención aclarada por el
usuario. Se añade selección explícita de técnica, sin sustituir los originales ni
reinterpretar runs existentes.

Se reutilizan ingesta SEG-Y/sidecar, transacciones, worker, almacenamiento y
revisión. El cálculo TRS usa el motor existente con protocolo tipado propio;
no pide exclusiones ni rejillas MASW. El dosier y su detalle tienen esquemas TRS
distintos. La publicación verifica correspondencia entre run y resultado.

Se permite declarar una ventana posterior como referencia de ruido cuando no hay
pretrigger, con flag explícito, ventanas no solapadas y evidencia pendiente de
validación en campo. Se conserva el comportamiento previo por defecto. No se
crean muestras ni sigmas temporales calibradas por inferencia.

La ampliación no habilita inversión/tomografía, verificación geológica, suficiencia
demostrada ni liberación operativa. Los supuestos de geometría/amplitud/stack del
ejemplo se conservan en procedencia. Las comprobaciones y el recorrido están en
[TRS local](../app_local_trs.md); las obligaciones científicas históricas siguen
su registro independiente.
