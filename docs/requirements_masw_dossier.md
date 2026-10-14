# Ejercicio Oysand — protocolo diagnóstico del dosier MASW

Prerregistro 2026-10-13, previo a la ejecución nueva. Alcance: cuatro registros
del perfil P1, offsets 10/15/20/30 m, sin verdad independiente ni aceptación Vs30.
Verificar archivos contra download_manifest.json y volver a procesar las muestras.
No consumir semáforos ni resultados anteriores como verdad.

Procesamiento fijado: retirar media por canal; Hann de todo el registro; bins FFT
observados entre 5 y 70 Hz; velocidades 60..400 m/s cada 1 m/s; phase-shift en
direcciones ±1; cresta DP con escala 30 (m/s)/Hz y penalización 0.02. Son opciones
exploratorias del protocolo anterior, no banda validada ni parámetros calibrados.
Comparar con ventana rectangular y exclusión exclusiva de canal 1 manteniendo
coordenadas; son ensayos de sensibilidad, no elecciones para maximizar calidad.

Controles: amplitudes finitas y canales constantes/cero; soporte por frecuencia;
frontera de rejilla; c>2*f*dx únicamente para soporte regular completo. Igualdad
queda en revisión. Pasar este control geométrico no demuestra ausencia de aliases.
Con huecos no se aplica Nyquist uniforme. Ningún umbral de coherencia/significancia
empírico nuevo. Mostrar I como coherencia, nunca energía modal. Mostrar amplitud
Fourier aparte, sin denominarla PSD ni SNR. No usar coda como ruido.

Bandas diagnósticas: agrupar bins adyacentes con iguales motivos; conservar huecos,
soporte activo y límites en centros de bins (sin precisión sub-bin inventada).
Sin soporte: NO_EVALUABLE; con alerta geométrica/rejilla: REGULAR; otros puntos:
NO_EVALUABLE por evidencia pendiente. Canal cero/constante: MALA por falla observada.
Integridad de muestras puede ser PASS sin que el registro sea BUENA.

Comparación de offsets en mismos bins y solo candidatos interiores a rejilla y al
dominio Nyquist de soporte completo. Reportar cantidad, intervalos, mediana y máximo
de |diferencia|, sin p-values, sigma ni diagnóstico causal. No unir curvas ni producir
un perfil Vs. Variación entre offsets no es repetibilidad de fuentes idénticas.

Agregación: 4 registros, 96 trazas, 1 sitio/perfil; plan de posiciones requeridas
desconocido => porcentaje de cobertura del estudio null. Sin promedios de colores
ni porcentajes de bins como calidad. Global NO_EVALUABLE, evidencia INCOMPLETE,
eligible_for_acceptance=false. Advertencias y hallazgos conviven con los faltantes.

Pruebas previas: señal plana analítica recupera pico de rejilla; ceros no producen
curva fiable; frontera alias/rejilla explícita; huecos no heredan Nyquist regular;
bandas no puentean motivos/soporte; alteración del original detiene generación;
comparaciones no rellenan soporte. Integración de cuatro archivos: 96 trazas,
ninguna elegibilidad, PDF/HTML/CSV/JSON y referencias internas coherentes.
Resultados reales de pruebas y hashes en evidence/masw_quality/validation/.
