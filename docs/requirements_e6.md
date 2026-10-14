# Protocolo E6 — motor diagnóstico de requisitos

Fecha: 2026-10-13. Registrado antes de implementar/ejecutar las pruebas E6.
Alcance de esta entrega: agregación headless, selección y supersesión explícitas,
acciones condicionadas y bitácora humana separada. No habilita aceptación de campo.

- V-E6-1: tabla de calidad PASS/WARN/FAIL y ausencia de resultado; estados de
  aplicabilidad/validez; requisitos obligatorios y opcionales; NA justificado por
  perfil; unidad/soporte/técnica incompatibles; calibración sin verificar.
- V-E6-2: productos cartesianos de estados de dos requisitos; degradar un dato
  usado no mejora calidad ni completitud; opcionales no satisfacen obligatorios.
- V-E6-3: acciones con condición, unidad y supuestos. Reutilizar `required_stacks`:
  N=4 y SNR 6→12 dB requieren 16 bajo independencia y stack promedio; abstenerse
  sin estos supuestos. Aliasing recomienda reducir dx/limitar banda, sin afirmar
  suficiencia ni aumentar frecuencia a dx fijo.
- V-E6-4: FAIL crítico usado bloquea RED aunque resultados derivados sean PASS.
  Dependencias transitivas se incluyen en datos usados; referencias ausentes o
  ciclos se rechazan. Los resultados derivados conservan motivos del bloqueo.
- V-E6-5: JSON diagnóstico exportable con advertencias y faltantes. Una anotación
  ACCEPTED exige responsable, alcance y salvedades, ligada al digest científico;
  nunca modifica métricas, colores ni elegibilidad. No es aceptación científica.
- V-E6-6: reemplazo comparable, causa explícita y métricas resueltas PASS; historial
  conservado. Seleccionar otro disparo sin sustitución no satisface el requisito.
  Cambios de geometría/componente/configuración/soporte, cadenas cíclicas y causas
  aún fallidas impiden supersesión. Un derivado del original sigue dependiendo de él.

Los requisitos identifican registro, métrica, unidad, soporte, técnica y componente;
el perfil determina obligatoriedad y NA antes del cálculo. Un campo `mandatory`
editado en la métrica no elimina la obligación del perfil. Métricas obligatorias
adicionales y faltantes upstream se preservan y bloquean cuando corresponda.

Calibración empírica requerida queda UNCALIBRATED en esta entrega: una referencia
textual no autentica vigencia ni dominio. Solo controles teóricos/binarios declarados
sin calibración empírica pueden completar evidencia diagnóstica. Aun entonces,
elegibilidad=false por política de release diagnóstico y G9 pendiente. Un esquema
MASW anterior, revisión/hash incompatibles o faltantes upstream bloquean completitud.

E6 no introduce umbrales numéricos. Las pruebas de reglas son exactas, sin tolerancias
físicas nuevas ni aleatoriedad. La evidencia se guarda por ejecución, con fases reales
de pytest, hashes, entorno y cobertura. Pasar estos casos no cierra G6: faltan registro
operativo calibrado, integración completa E6/E8 de MASW-R1 y dependencias ampliadas.
