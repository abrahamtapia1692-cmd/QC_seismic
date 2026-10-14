# Ejemplo TRS causal E4

24 receptores entre 3 y 24 m, fuente x=0, dos capas horizontales Vp=300/1500 m/s,
h=5 m. Pulso causal de 80 Hz, dt=0.25 ms, retardo de fuente conocido de 30 ms y
ruido gaussiano 20 dB en la ventana activa declarada. No son datos de campo.

```powershell
.\.venv\Scripts\python.exe tools/create_trs_demo.py
.\.venv\Scripts\python.exe -m geoqc trs examples/e4/causal_trs.sgy --protocol examples/e4/protocol.json --calibration examples/e4/calibration.json
```

`calibration.json` contiene los 2000 errores de train independientes PCG64/4420,
hash de protocolo y estimador; solo aplica al dominio sintético declarado. No usa
las 6000 realizaciones holdout. La corrección de fuente se aplica al tiempo-distancia
y no modifica los picks originales ni sus intervalos. `report.json` conserva
receptores físicos, intervalos, lados, BIC/soporte e inversión con presupuesto 5.
La reciprocidad, cobertura/resolución de sitio, capas ocultas y G9 siguen pendientes;
`eligible_for_acceptance=false` incluso si el ajuste local converge.
