# Informe — Pregunta 2: agarre autónomo bajo la cola del broker

**Equipo N.º:** ____  **Integrantes:** ____________________  **ROS_DOMAIN_ID:** ____  **Brazo:** arm-__
**Fecha:** ___/___/2026  **Servidor LAYA:** ____________  **umbral_peligro usado:** ____

> Todo número de este informe sale de `evidencia_p2/intentos.csv`, `rechazos.csv` o del bag.

## 1. Cadena implementada

Frase → `/interpretar_orden` (P1, LAYA con respaldo) → goal `move_arm` con la decisión completa →
`goal_callback` del broker del RB-2 (rechazo con causa antes de encolar) → cola con política
`prioridad` (prioridad del modelo + espera/τ, τ = 8 s) → worker único → cámara (pose de observación)
→ IK sobre la FK del RB-2 → MoveIt 2 planifica 7 tramos → el worker envía la trayectoria al brazo →
gripper. Diagrama y tabla de cumplimiento: `README.md`.

## 2. Regla del publicador único

* Solo `arm_broker` abre el puerto del brazo y publica `/joint_states`. MoveIt (`move_group`) solo
  responde `/plan_kinematic_path`; no se lanzó `demo.launch.py` ni controladores.
* Evidencia: salida de `ros2 topic info /joint_states -v` durante la demo: ____________________
* `sudo fuser -v /dev/ttyTHS1` antes de lanzar el broker (vacío): ____________________

## 3. Pedidos simultáneos y prioridad

Video (enlace): ____________________ (3 min: `monitor_cola` + brazo).
Describan un momento del video en que la cola se reordena (minuto, quién entró, con qué prioridad y
quién pasó adelante): ____________________

## 4. Órdenes rechazadas antes de encolar

<!-- Pegar las filas de evidencia_p2/rechazos.csv (incluida la orden prohibida que dictó el docente) -->

| Hora | Cliente | Frase | Decisión del modelo | Causa del rechazo |
|---|---|---|---|---|

## 5. Predicción

<!-- Copiar PREDICCIONES_P2.md (hecho ANTES de los intentos; indicar el commit) -->

## 6. Diez intentos

<!-- Pegar la salida de: ros2 run arm_broker tabla_intentos evidencia_p2/intentos.csv --prediccion-exito X --prediccion-error Y -->

Error: distancia entre el punto solicitado (`DESTINOS` + `z_soltar`) y la FK del RB-2 evaluada en los
ángulos leídos con `get_angles()` en el punto de entrega, antes de abrir la pinza. Como referencia
cruzada se reporta también la posición que informa el firmware (`get_coords`).

## 7. Análisis

* ¿Por qué fallaron los intentos fallidos (percepción, agarre, IK, posición del cubo)? ____________
* Predicho vs medido (éxito y error) y por qué se equivocó la predicción: ____________
* ¿Cuántos intentos usaron MoveIt y cuántos interpolación (columna `planificador`)? ____________
* Tiempos por etapa (la tabla los imprime): ¿qué domina la duración de un pedido? ____________

## 8. Evidencia entregada

| Archivo | Contenido |
|---|---|
| `evidencia/bag_p2_demo/` (enlace) | bag de la demostración |
| `evidencia/evidencia_p2/intentos.csv` | una fila por pedido ejecutado, con tiempos y error |
| `evidencia/evidencia_p2/rechazos.csv` | rechazos antes de encolar, con causa |
| `evidencia/evidencia_p2/img/` | imagen de la cámara de cada intento |
| `evidencia/tabla_intentos.md` | tabla de los 10 intentos |
| `evidencia/evidencia_clientes/` | lo que vio cada integrante |
| video (enlace) | 3 minutos, cola + brazo |
