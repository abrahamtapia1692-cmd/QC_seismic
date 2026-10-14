# Ejemplo diagnóstico E6

`input.json` se genera desde el fixture sintético E2 y su QC común. Contiene
requisitos por traza, métricas y faltantes heredados. `report.json` conserva
la entrada y agrega calidad, completitud, motivos y digest.

```powershell
.\.venv\Scripts\python.exe tools/create_decision_demo.py
.\.venv\Scripts\python.exe -m geoqc decision --input examples/e6/input.json
```

La calibración empírica y el QC específico del objetivo están pendientes.
Esta entrada no es un perfil completo de suficiencia Vs30. La salida siempre
es diagnóstica y `eligible_for_acceptance=false`.
