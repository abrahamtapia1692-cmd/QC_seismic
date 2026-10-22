# Evidencia del backend local

La ejecución [20261016T134244Z_197836da](runs/20261016T134244Z_197836da/execution.json)
archiva **69 pruebas satisfactorias**: 17 de detalle paginado y 52 regresiones
del backend/exportaciones. Comprueba fidelidad científica, cursores firmados,
filtros, presupuesto de respuesta, ETag, permisos e integridad de archivos.
Ver [app_local_detail.md](../../../docs/app_local_detail.md).

La ejecución [20261016T050954Z_1b949d6f](runs/20261016T050954Z_1b949d6f/execution.json)
archiva **52 pruebas satisfactorias**: 15 de exportaciones CSV/HTML/PDF y 37
regresiones del backend. Incluye ejemplos del dosier E5 en los tres formatos,
marcados como snapshots suministrados, separados de una publicación en base.
Las instrucciones y límites están en [app_local_exports.md](../../../docs/app_local_exports.md).

La ejecución [20261016T043151Z_c5e8a8cd](runs/20261016T043151Z_c5e8a8cd/execution.json)
archiva **37 pruebas satisfactorias**, incluyendo cancelación/expiración de cargas,
migración del esquema 1 al 2, conservación de originales, transferencias HTTP,
recuperación de procesos y las regresiones previas del backend.

La ejecución [20261016T041315Z_d9f703d4](runs/20261016T041315Z_d9f703d4/execution.json)
archiva **25 pruebas satisfactorias** de PostgreSQL, recuperación de procesos
API/worker, revisión, concurrencia, almacenamiento y reconciliación. El timestamp
de la carpeta está en UTC; corresponde al 15 de octubre de 2026 en Ciudad de México.

Cada ejecución conserva JUnit y hashes/versiones capturados por
`tools/summarize_app_backend.py`. No incluye DSN, contraseñas ni bearer tokens.
El colector no ejecuta las pruebas ni vincula retrospectivamente su resultado
a una versión de fuentes; esa correspondencia se registra durante el trabajo.

Los límites y las instrucciones reproducibles están en
[docs/app_local_backend.md](../../../docs/app_local_backend.md).
Esta evidencia no acredita los gates científicos ni el primer hito Web integrado.
