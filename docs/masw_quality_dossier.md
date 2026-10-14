# Dosier MASW — ejercicio Oysand / P1

Entregables: [HTML autónomo](../evidence/masw_quality/dossier.html),
[PDF](../evidence/masw_quality/dossier.pdf), [JSON](../evidence/masw_quality/dossier.json),
[bandas CSV](../evidence/masw_quality/bands.csv), [puntos CSV](../evidence/masw_quality/points.csv),
[trazas CSV](../evidence/masw_quality/traces.csv), [comparaciones CSV](../evidence/masw_quality/comparisons.csv).

Se reprocesan los cuatro originales Oysand del manifiesto: 24 canales por registro,
96 trazas, offsets 10/15/20/30 m, dx 2 m, apertura 46 m. Un sitio/perfil, no cuatro
sitios independientes. No se construye un Shot con instrumentación inventada.
Se conserva el convenio de 24 canales del ejemplo original y se prueba por separado
la exclusión del canal 1, cuyo papel como trigger está pendiente.

El [protocolo prerregistrado](requirements_masw_dossier.md) fija procesamiento y
criterios. No se introducen umbrales de coherencia/SNR ni calificación 90/75 por bins.
La imagen es coherencia I; la amplitud Fourier se muestra aparte, sin denominarla
energía modal o SNR. Dirección inversa incluida para visualizar ambigüedades.

## Resultado del ejercicio

- Integridad de muestras PASS: no se encontraron canales constantes/cero.
- Soporte candidato geométrico, pendiente de validación: r1 5.452–31.349 Hz;
  r2/r3/r4 5.452–31.804 Hz. Son centros de bins con separación ≈0.454 Hz.
- Desde el siguiente bin y hasta 69.968 Hz, la cresta requiere revisión del muestreo
  espacial. Estar dentro del dominio Nyquist tampoco demuestra ausencia de alias.
- Diferencias entre pares en soporte candidato: medianas 1–2 m/s, máximos 24–53 m/s.
  No se interpretan como error respecto a verdad, repetibilidad, lateralidad ni
  compatibilidad estadística: faltan covarianza y control modal.
- Evaluación integral NO_EVALUABLE, evidencia INCOMPLETE y aceptación deshabilitada.
  No se infiere mala adquisición por los faltantes. No se calcula ni certifica Vs30.

El PDF tiene siete páginas: síntesis, comparación, geometría/bandas y cuatro fichas
multicanal. El HTML incorpora imágenes sin recursos externos, selector de registro
y tablas desplegables. Los espectros NPZ permiten reproducir las figuras. JSON/CSV
conservan soportes, motivos, máscaras, versiones y hashes; se comprueban originales
antes y después del análisis. El hash junto al informe no autentica una autoridad.

La geometría es un esquema relativo por registro, no un mapa de posiciones absolutas.
El porcentaje de cobertura del estudio es null: falta el plan de posiciones y la banda
objetivo. No se promedian curvas ni se une su soporte para declarar suficiencia.

## Reproducción y validación

```powershell
.\.venv\Scripts\python.exe tools/report_masw_quality.py
.\.venv\Scripts\python.exe tools/validate_masw_dossier.py
```

La generación admite `--output`. Requiere el entorno de informes ya instalado
(NumPy, SciPy, matplotlib); funciona offline. Pruebas de señal plana independiente,
ceros, entradas inválidas, fronteras, huecos, hash alterado y generación completa.
El runner guarda resultados reales por prueba, logs, hashes y entorno en carpetas
únicas dentro de `evidence/masw_quality/validation`. No modifica gates G5/G6/G9.

Próxima adquisición/evidencia: verificar trigger y metadatos instrumentales/geométricos;
capturar ruido independiente y réplicas comparables; resolver banda/modo y objetivo
antes de evaluar incertidumbre, resolución o suficiencia ingenieril.
