# Predicciones de la Pregunta 2 (escribir ANTES de los 10 intentos y hacer commit)

Fecha y hora del commit: ____________

| Magnitud | Valor predicho | Justificación (1–2 líneas) |
|---|---:|---|
| Tasa de éxito en 10 intentos [%] | | p. ej. calibración de la cámara, holgura del gripper |
| Error FK medio en el punto de entrega [mm] | | p. ej. la FK del RB-2 dio ≤ 7 mm en 5 poses + error de seguimiento de los servos |
| Error FK máximo [mm] | | |
| Espera máxima en la cola con 4 pedidos simultáneos [s] | | ≈ 3 × duración de un agarre |
| Duración de un agarre completo [s] | | |
| Órdenes rechazadas antes de encolar en la demo | | la(s) prohibida(s) del docente |

Después de medir: `ros2 run arm_broker tabla_intentos evidencia_p2/intentos.csv --prediccion-exito X --prediccion-error Y`
