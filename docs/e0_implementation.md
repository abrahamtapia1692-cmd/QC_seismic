# E0: contratos y referencias

El paquete `geoqc` implementa E0 del SDD v1.4. El runner [check_e0.py](../tools/check_e0.py) ejecuta pytest, ruff, comprobación de formato y mypy strict; deriva G0 desde sus resultados. El manifiesto del diseño conserva sus estados iniciales: el estado de ejecución se registra aparte en `evidence/e0/G0.json`. G1–G10 no se cierran por haber aprobado E0.

## Instalación y uso

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-win-py312.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe tools/check_e0.py
.\.venv\Scripts\python.exe -m geoqc validate-config --config configs/vs30_sitio.yaml
```

El lock registra las versiones del entorno validado en Windows/Python 3.12.3; no es un lock universal ni contiene hashes de wheels. Se requiere verificar otro entorno antes de atribuirle el mismo gate. En esta sesión NumPy/SciPy/Pydantic/pytest/YAML/setuptools provienen del entorno existente mediante system-site-packages; el runner registra las versiones efectivamente usadas. Las dependencias nuevas de desarrollo se instalaron dentro de `.venv`.

`geoqc plan --config configs/vs30_sitio.yaml --geometry geometria.json` requiere un Geometry JSON explícito: xr/yr/zr, xs/ys/zs en metros, incertidumbre por receptor, crs y provenance. No sintetiza una geometría de campo. `eligible_for_acceptance` siempre es false en E0. La CLI devuelve código 2 para configuración/contrato inválido.

## Decisiones de implementación

- Arrays float64 y booleanos copiados a memoria respaldada por bytes inmutables. Una muestra no finita debe estar excluida y tener motivo; en JSON se representa por null. La lectura de null reconstruye NaN solo bajo máscara. Los headers originales se conservan como JSON canónico, manteniendo su contenido; los archivos originales se identifican por SHA-256.
- dt/t0 pueden diferir por canal; elevación positiva hacia arriba y unidades SI. Metadatos instrumentales faltantes son null. No se infiere onda P desde el nombre del componente.
- Umbrales candidatos declaran direction, warn/fail, frontera inclusiva y estado de calibración. En higher_is_better, ≤fail es FAIL y ≤warn es WARN; en lower_is_better, ≥fail es FAIL y ≥warn es WARN. Esta clasificación diagnóstica no habilita aceptación.
- Hashes canónicos: claves textuales ordenadas, JSON UTF-8 sin NaN/Inf, arrays con dtype/forma/bytes y endian normalizado a little-endian. El hash es reproducible bajo esta versión, no una promesa de identidad entre cualquier representación matemática equivalente. Los hashes de archivos son SHA-256 sobre bytes sin normalizar.
- La profundidad calculada como λ_max/κ_z es un resumen nominal. `observed_band` recibe una máscara ya validada por el llamador; E5 implementará la validación de banda, continuidad, resolución y modalidad. Este resumen no prueba profundidad resoluble ni exactitud de Vs30.
- La planificación calcula ambas fronteras de banda y Nyquist del escenario homogéneo regular; compara efectos geométricos sin convertirlos en una puntuación universal de calidad. Los campos `_at_48m` conservan la contraprueba histórica; los resultados generales usan las fronteras de banda.
- Las funciones de Rayleigh resuelven la cúbica física por Brent. np.roots aporta un método numérico alternativo, y el residual radical comprueba la misma teoría; no se anuncia como teoría independiente. La referencia de semiespacio no implementa generación modal multicapa.

## Trazabilidad

Las pruebas se escribieron antes del paquete: la primera ejecución falló por `ModuleNotFoundError: geoqc`. Después se implementaron los contratos y se ampliaron las pruebas para fronteras y estados desconocidos. Cada caso lleva un ID V del plan; el plugin registra también setup/teardown y skips. Una colección fallida o herramienta fallida impide G0.

El [pyproject original](archive/pyproject_v0_0_1.toml) se archivó byte por byte antes de modificar el paquete. El plan y los cuatro archivos fuente originales de v1.3 siguen intactos; `validate_plan_v1_4.py` contrasta sus hashes históricos y el pyproject archivado. La auditoría histórica no se reescribe como evidencia de esta implementación.

Los [requisitos de E0](requirements_v1_4.md) definen sus IDs y datos necesarios. Los perfiles DRAFT conservan los supuestos no confirmados de [open_questions.md](open_questions.md). Los próximos gates autorizables por dependencias son G1 (lectura) y G3 (sintéticos básicos).
