# Evidencia del adaptador MASW local

Alcance: implementación del adaptador y regresiones seleccionadas. Esta evidencia no aprueba gates científicos ni demuestra funcionamiento del backend, worker persistente o aplicaciones.

## Ejecución final archivada

Estado PASSED: 43 pruebas de aplicación/dosier y 40 regresiones seleccionadas del núcleo; cero fallos, errores o skips. Ruff y mypy también pasaron durante la implementación; el colector de reportes no ejecuta esas herramientas.

- [Resumen, hashes y procedencia](runs/20261015T045324Z_2750c032/validation.json).
- [Dosier E5 generado por el adaptador](runs/20261015T045324Z_2750c032/e5_dossier.json).
- [JUnit de aplicación/dosier](runs/20261015T045324Z_2750c032/application_tests.xml).
- [JUnit de regresión del núcleo](runs/20261015T045324Z_2750c032/core_regression_tests.xml).

La ruta de ejecución usa UTC; la entrega está fechada el 14 de octubre de 2026 en America/Mexico_City. El colector conserva los XML y captura hashes al archivarlos; no certifica por sí solo qué código ejecutó cada prueba. El estado corresponde únicamente a los escenarios seleccionados.

## Capturas y ensayos intermedios

- La caracterización previa a la extracción está en [oysand_before_extraction.json](../../../tests/fixtures/app_adapter/oysand_before_extraction.json). Su hash de fuente corresponde al generador anterior; se conserva sin regenerar.
- application_tests_final.xml y core_regression_tests_final.xml contienen las ejecuciones finales seleccionadas, copiadas al directorio de ejecución enlazado arriba. Sus contadores y referencias se resumen en su validation.json.
- application_tests.xml y core_regression_tests.xml conservan ejecuciones intermedias fallidas: una comprobación de importación restringía indebidamente lecturas de metadatos de dependencias y el exportador JUnit requería xunit1 para record_property. No son resultados de aceptación.

Un ensayo intermedio largo se interrumpió después de modificar el límite entre cálculo y captura de procedencia; la regresión final se ejecutó de nuevo sobre el código estabilizado. No se incluye ese ensayo como evidencia de aprobación.

Los XML finales se deben leer junto con validation.json y sus hashes. No afirmar éxito por el nombre del archivo; comprobar contadores de failures/errors/skipped y el estado registrado. La definición de alcance y los casos verificados están en [la documentación del adaptador](../../../docs/app_local_adapter.md).
