# Ejemplo sintético de ingesta

`synthetic_ieee.sgy` y su sidecar contienen **24 canales × 2048 muestras**, dt=1 ms y t0=−100 ms. Son pulsos causales trasladados a velocidad Rayleigh analítica de un semiespacio Vs=250 m/s, ν=0.4; no proceden de campo ni representan un Green completo.

```powershell
.\.venv\Scripts\python.exe -m geoqc inspect examples/e1/synthetic_ieee.sgy
```

El generador está en `tools/create_io_demo.py`. Crea archivos nuevos y protege archivos existentes. Receptores y geometría son sintéticos exactos; calibración instrumental y aceptación de campo no se afirman. Este ejemplo permite revisar el lector y la CLI antes de recibir datos reales.
