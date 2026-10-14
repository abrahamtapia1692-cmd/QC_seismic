# Ejemplo E2

Generar con `python tools/create_qc_demo.py`. `common_qc.sgy` y su sidecar contienen
seis trazas sintéticas, ruido blanco PCG64/20261005, gains conocidos exp(-r/30).
r4 tiene amplitud multiplicada por 0.2 y r5 es cero. No son datos de campo.

```powershell
.\.venv\Scripts\python.exe -m geoqc qc examples/e2/common_qc.sgy --config configs/vs30_sitio.yaml --protocol examples/e2/protocol.json
```

El informe publicado `report.json` identifica r4 como anomalía de amplitud sin causa
exclusiva y r5 como muerto. Rails conocidos permiten informar phi=0; SNR del canal
muerto queda censurado. Los perfiles no incluyen umbrales calibrados: la calidad
puede quedar sin clasificación. La aceptación siempre permanece deshabilitada.
Las ventanas/reglas de `protocol.json` sirven únicamente para este generador.
