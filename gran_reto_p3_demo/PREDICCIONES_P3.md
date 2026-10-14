# Predicciones de la Pregunta 3 (escribir ANTES de la demostración y hacer commit)

Fecha y hora del commit: ____________

| Magnitud | Valor predicho | Justificación (1–2 líneas) |
|---|---:|---|
| Transcripción: órdenes del docente transcritas sin error [de 5] | | acento, ruido del laboratorio, vocabulario |
| Órdenes finales correctas (incluido el rechazo) [de 5] | | |
| Tiempo de captura [ms] | | ≈ `silencio_s` + duración del último bloque |
| Tiempo de transcripción en la nube [ms] | | tamaño del audio, red, modelo |
| Tiempo de decisión [ms] | | mediana de la P1 con carga del laboratorio |
| Espera en cola con la cola vacía [ms] | | |
| Percepción + IK + planificación [ms] | | tomar de `tabla_intentos` de la P2 |
| **Total: fin de la voz → inicio del movimiento [s]** | | suma de lo anterior |
| Etapa dominante | | |
| ¿Se activa el modo texto sin internet en menos de ___ s? | | `timeout_transcripcion_s` + margen |

Después de medir: `ros2 run jetcobot_voz desglose_voz ...` y comparar columna por columna (predicho vs medido).
