# Golpes individuales o apilamientos: análisis de KM 40+672

Fecha: 2026-10-19. Resultado: **golpes individuales es la hipótesis de trabajo
mejor respaldada; stack_count permanece sin certificar**.

Se leyeron los 29 SEG-2 activos de KM 40+672, verificando sus hashes contra el
inventario. No se modificaron, filtraron, realinearon ni apilaron los archivos.

## Qué esperamos según las notas

El Readme indica nueve fuentes y 3–4 golpes por fuente. Se encontraron cuatro
archivos en F1/F2 y tres en F3–F9: 29 registros en total. Es exactamente compatible
con guardar cada golpe por separado. Guardar únicamente un apilamiento final por
fuente produciría nueve archivos, si la exportación fuera completa y sin copias.
Guardar cada estado de un apilamiento acumulado también puede producir 29: el
conteo por sí solo no distingue esos dos casos.

El [manual DAQLink 4, secciones 5.4.9 y 5.4.11](https://geodevice.uz/upload/iblock/86a/DAQLink-4-Manual.pdf)
ofrece exportación de registros individuales y exportación de stacks como opciones
separadas. No se recuperó la selección usada en esta campaña.

## Comprobaciones numéricas

Se compararon registros consecutivos dentro de cada carpeta de fuente. Por canal
se retiró su media para calcular RMS y correlación; no se alteraron los originales.
Los resúmenes son medianas entre canales con energía no nula. Se calculó también
una regresión de ganancia por canal y el residuo relativo, para no confundir un
cambio de escala con una onda diferente. El reporte conserva todos esos valores.

En F1, las cuatro medianas RMS de canal son aproximadamente 3,1e-5, 2,5e-5,
3,0e-5 y 2,9e-5 en unidades almacenadas, sin asignarles voltios o counts.

| Par consecutivo de F1 | Correlación mediana completa | Correlación mediana de mitad final | Razón RMS por canal, mediana |
| --- | ---: | ---: | ---: |
| 1 → 2 | 0,704 | 0,033 | 0,830 |
| 2 → 3 | 0,378 | 0,017 | 1,046 |
| 3 → 4 | 0,892 | 0,045 | 1,080 |

Las razones RMS son medianas de cocientes por canal, no cocientes de las medianas
RMS anteriores. Los intervalos entre tiempos de cabecera en F1 son 79,47, 15,69 y
10,86 segundos: compatibles con registros separados, sin certificar golpe único.

Las correlaciones de mitad final en las nueve fuentes son generalmente próximas
a cero. La señal completa muestra repetibilidad variable, incluida correlación
negativa o casi nula en un registro débil de F2; no se ocultó ese registro.

En un modelo ideal de ruido independiente y de igual varianza por golpe, un
apilamiento acumulado comparte ruido entre estados consecutivos. Su correlación
esperada es sqrt(k/(k+1)): aproximadamente 0,71, 0,82 y 0,87 para k=1,2,3.
Esto vale tanto para suma como para promedio en ese modelo. Los valores finales
observados no apoyan ese patrón sencillo de acumulación compartida.

La mitad final **no está verificada como ruido puro**; puede incluir coda u otras
señales. Cambios de ganancia, alineación, ruido o selección de golpes podrían
romper el modelo. No se calculó probabilidad de clasificación ni umbral calibrado.

## Qué podemos y qué no podemos inferir

Los conteos, notas y comparaciones favorecen guardar golpes individuales frente
a una secuencia simple de stacks acumulados. No prueban que cada archivo sea un
golpe: varios stacks independientes también pueden tener residuos no compartidos.

Matemáticamente no existe una identificación universal a partir de las muestras:
un golpe con forma 2*x y la suma de dos golpes idénticos x producen exactamente
el mismo archivo. Del mismo modo, una secuencia cualquiera se puede expresar
como sumas acumuladas de sus diferencias sin conocer la plausibilidad física de
esas diferencias. Se necesitan restricciones o información de adquisición.

Por ello se registra la hipótesis en un campo exploratorio, sin sustituir
`stack_count=null` ni `stack_kind=UNKNOWN` por metadatos confirmados. El resultado
tampoco determina la escala de voltaje ni convierte STACK=0 en STACK=1.

## Evidencia y reproducción

- [Reporte numérico y hashes](../../evidence/app_local/km_stack_analysis/analysis.json).
- [Comparación gráfica de F1](../../evidence/app_local/km_stack_analysis/f1_comparison.svg).
- [Tres pruebas satisfactorias, 0,91 s](../../evidence/app_local/km_stack_tests.xml):
  indistinguibilidad entre golpe escalado y suma, abstención en canales constantes
  y rechazo de dimensiones incompatibles. Ruff pasó.

```powershell
.\.venv\Scripts\python.exe tools/analyze_km_stacking.py --output .local/km_stack_analysis_nuevo
.\.venv\Scripts\python.exe -m pytest tools/tests/test_km_stacking.py -q
```

La herramienta genera evidencia nueva en un directorio no existente. No actualiza
automáticamente metadatos científicos ni procesa MASW.
