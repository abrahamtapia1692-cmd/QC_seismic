# Ejemplo MASW E5

24 receptores x=6+2j m, señal multisinusoidal 8..32 Hz, c=200 m/s,
dt=1 ms, registro4 s, ruido gaussiano con semilla202610056. SEG-Y+sidecar físicos.
Son datos sintéticos; identidad modal APPARENT, precisión y significancia
UNCALIBRATED sin artefactos de calibración compatibles.

```powershell
.\.venv\Scripts\python.exe tools/create_masw_demo.py
.\.venv\Scripts\python.exe -m geoqc masw examples/e5/masw_plane.sgy --protocol examples/e5/protocol.json
```

La cresta y los ratios geométricos son diagnósticos. Bandas validadas vacías,
suficiencia Vs30 no establecida y aceptación=false. El informe conserva cada
frecuencia, dirección, soporte físico, motivos y procedencia.
