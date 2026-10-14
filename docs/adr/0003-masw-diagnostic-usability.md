# ADR 0003 — utilidad diagnóstica de dispersión separada de suficiencia

Fecha: 2026-10-13. Estado: implementación diagnóstica autorizada; no calibración G9.

El dosier 1.0 condicionaba toda calificación a evidencia de aceptación del objetivo.
Se introduce dosier 2.0: utilidad para extraer/revisar una **cresta aparente** por
frecuencia, independiente del estado de suficiencia Vs30. Campos nuevos separados;
los informes 1.0 se conservan como historia, sin reinterpretarlos como validación.

Se estiman atributos del registro, no SNR física ni probabilidad de identificación:
I en la cresta; mediana del fondo del espectro I(q) fuera del lóbulo principal;
contraste I_cresta−mediana; mayor máximo competidor fuera del lóbulo / I_cresta;
máximo cambio relativo de c entre variantes de procesamiento explícitas.

Para posiciones uniformes completas y pesos iguales, la primera nulidad del kernel
es |Δq|=1/(N dx). Excluir ese lóbulo evita tratar su hombro como modo separado.
Se evalúa todo q firmado en [-1/(2dx),1/(2dx)], con al menos 24 muestras por esa
escala de resolución. La dirección de la cresta y su lóbulo deben caber en el dominio;
q=0 indica falta de resolución direccional, no velocidad infinita calculable.
Picos competidores incluyen extremos de rejilla. Resolver frecuencias/velocidades
no garantiza resolución modal ni elimina aliases fuera del dominio principal.
Geometría irregular o huecos espectrales no heredan esta regla: revisión de kernel.

Política local DRAFT, fijada antes de probar Oysand: I≥0.60; contraste≥0.25;
competidor/cresta≤0.80; sensibilidad≤0.05; fronteras inclusivas. Son candidatos
diagnósticos sin tasas de error de campo calibradas; no se atribuyen a bibliografía.
Todas las magnitudes adimensionales. Piso relativo de amplitud 1e-6 respecto al
máximo espectral por canal EN LA BANDA analizada, para no normalizar ceros numéricos
y colas diminutas como fase útil. No es un umbral SNR ni amplitud física mínima.
Se conserva máscara por frecuencia y sensibilidad al piso en pruebas.

Variantes: Hann completo, rectangular completo, exclusión canal 1 conservando
posiciones, máximo por frecuencia sin penalización DP. Variabilidad de estos
resultados mide sensibilidad, no sigma; no se selecciona la variante más favorable.
SNR/ADC/modalidad/campo cercano permanecen visibles, pero no bloquean esta pregunta
diagnóstica limitada. Un campo de ondas coherente ajeno a la fuente puede pasar:
UTILIZABLE significa extraíble/estable bajo controles, no origen Rayleigh confirmado.

Fundamento: [Park et al. 1999](https://www.masw.com/files/PAR-99-04.pdf) distingue
contaminación, offsets y análisis multicanal; [Ólafsdóttir et al. 2018](https://doi.org/10.1016/j.soildyn.2018.05.025)
evalúa variabilidad entre curvas. Ninguna fuente valida estos cortes locales.

Pruebas prerregistradas: plano analítico de fase conocida, campo coherente sin
identificación de fuente, dos direcciones competidoras, fases iid (PCG64 20261013),
ceros, geometría incompleta, invariancia a fase/escala/permutación, límites de cada
criterio, variantes ausentes, y refinamiento de q 24→48 sin cambiar una clasificación
alejada de frontera. No entrenar cortes con Oysand. No certificar falsos PASS con
un conjunto pequeño de controles sintéticos. PDF/HTML deben mostrar utilidad y
suficiencia por separado; exportar política, métricas, motivos y hash.
