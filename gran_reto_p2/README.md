# Gran Reto JetCobot — Pregunta 2: agarre autónomo bajo la cola del broker

Workspace ROS 2 (Humble) que se monta **encima** del de la Pregunta 1 (`gran_reto_p1`). Extiende el
broker del RB-2 (misma admisión, misma cola con política de prioridad y mismo worker con exclusión
mutua) con la cadena real: **decisión de la P1 → cola de prioridad → cámara → IK → MoveIt 2 → gripper**.

Paso a paso para ejecutarlo: [`../PASO_A_PASO_P2.md`](../PASO_A_PASO_P2.md).

```
Integrante 1..4 (su máquina)                     JETSON (ROS_DOMAIN_ID del equipo)                PC Windows del lab
cliente_integrado --id X ──srv /interpretar_orden──▶ interprete_ordenes (P1) ──HTTP──────────────▶ LAYA
        │   (copia la PRIORIDAD de la decisión)
        └──action move_arm (decisión completa)──────▶ arm_broker (RB-2 extendido)
                                                       goal_callback: ¿permitido? ¿objeto en mesa? ¿zona?
                                                         └─ NO → ⛔ rechazo antes de encolar (causa)
                                                       cola "prioridad" (prioridad + espera/τ)
                                                       worker → cámara → IK (FK RB-2) → MoveIt planifica
                                                              → el BROKER envía la trayectoria al brazo
                                                     move_group (MoveIt 2): SOLO planifica, no mueve nada
monitor_cola (video) ◀── /arm/queue_state, /arm/eventos           ros2 bag ◀── /joint_states, /arm/*, move_arm
```

## Contenido

```
src/
  arm_broker_interfaces/        MoveArm.action (campos RB-2 + decisión de la P1) y QueueState.msg
  arm_broker/
    arm_broker/
      broker.py                 nodo arm_broker (RB-2 extendido). ÚNICO que abre el puerto y publica /joint_states
      politicas.py              FIFO y prioridad con envejecimiento (RB-2, sin cambios en las políticas)
      fk.py                     FK del RB-2 (tabla DH calibrada, sin cambios)
      ik.py                     IK numérica sobre la FK del RB-2 (pinza vertical, simetría de 90° del cubo)
      planificador_moveit.py    cliente de /plan_kinematic_path (MoveIt 2 solo planifica)
      nucleo_p2.py              admisión de la P2 + ejecutor del agarre (sin ROS, con pruebas)
      DestinacionColores.py     mesa: cuadros B/G/R/Y, posiciones de los 4 cubos, alturas (Nivel 4 del notebook)
      CamaraColoresReconocimiento.py  visión HSV (Nivel 5 del notebook) + homografía píxel→mm
      brazo.py                  pymycobot (real) y brazo simulado
      evidencia.py              intentos.csv y rechazos.csv
      cliente_integrado.py      cliente de cada integrante (frase → P1 → broker)
      monitor_cola.py           pantalla de la cola para el video
      calibrar_camara.py        homografía con los 4 cubos en sus posiciones conocidas
      probar_decisiones.py      prueba /interpretar_orden con órdenes típicas (ajustar umbral_peligro)
      tabla_intentos.py         tabla de los 10 intentos, tasa de éxito, error FK, tiempos por etapa
      cliente.py                cliente original del RB-2 (modo articular, sigue funcionando)
    config/broker_p2.yaml       TODOS los valores de la mesa y del brazo (lo que se mide en el lab)
    config/broker_p2_simulado.yaml
    launch/p2.launch.py
    test/test_p2.py             19 pruebas sin ROS (IK, admisión, ejecutor simulado, evidencia)
herramientas/ensayo_4_clientes.sh
entorno_p2.sh                   las 3–4 líneas que van en cada terminal
PREDICCIONES_P2.md              predicciones (commit ANTES de medir)
informe_P2.md                   plantilla del informe con las tablas por llenar
```

## Cumplimiento de los requisitos

| Requisito del examen | Cómo se cumple | Evidencia |
|---|---|---|
| La decisión de la P1 entra a la cola del broker del RB-2 | `cliente_integrado` llama a `/interpretar_orden` y envía la decisión completa en el goal `move_arm`; el broker es el del RB-2 extendido (misma admisión → cola → worker) | log del broker, `/arm/eventos` |
| La prioridad viene del modelo | `goal.priority = decision.prioridad`; el cliente **no tiene** opción para escribirla | `cliente_integrado.py`, columna `prioridad` y `fuente_decision` de `intentos.csv` |
| Cámara localiza el objeto al desencolar | `CamaraColoresReconocimiento.localizar()` en la pose de observación; homografía píxel→mm y elección de la posición conocida | `evidencia_p2/img/*.jpg`, columna `metodo_posicion` |
| Se resuelve la IK | `ik.py`, sobre la **misma** tabla DH del RB-2 | columna `t_ik_s` |
| MoveIt 2 planifica la trayectoria | `/plan_kinematic_path` por tramo (7 tramos por agarre), todos antes de mover | columna `planificador = moveit`, `t_planificacion_s` |
| El gripper agarra y traslada | `set_gripper_value` abrir/cerrar en el worker | video |
| Regla del publicador único | Solo `arm_broker` abre el puerto serie y publica `/joint_states`; MoveIt no ejecuta | `ros2 topic info /joint_states -v` (1 publicador), bag |
| 4 integrantes en paralelo | `MultiThreadedExecutor` + admisión reentrante; un solo worker ejecuta | video + `monitor_cola` |
| Orden no permitida rechazada **antes** de encolar, con causa | `goal_callback` → `GoalResponse.REJECT`; causa en log, `rechazos.csv`, `/arm/eventos` (bag) y pantalla del cliente | `rechazos.csv`, bag |
| 10 intentos con tasa de éxito | `intentos.csv` + `exito_manual` (si/no) → `tabla_intentos` | `tabla_intentos.md` |
| Error solicitado vs alcanzado con la FK del RB-2 | ángulos leídos en el punto de entrega **antes de soltar** → `fk.fk()` → distancia al punto pedido | columnas `pos_fk_mm`, `error_fk_mm` (+ `error_get_coords_mm` de referencia) |

## Decisiones de diseño (para el informe)

* **Destino.** La P1 se dejó intacta (zonas A/B/C). Si la orden no nombra zona, el cubo va al cuadro de
  **su mismo color** (B/G/R/Y del tapete). `zona_b` → cuadro **B** (azul); `zona_a` y `zona_c` no existen
  en esta mesa y se rechazan con causa (se pueden asignar con `-p zona_a:=verde`).
* **Objeto que no está en la mesa** (Pregunta 3): se rechaza antes de encolar si su tipo no está en
  `objetos_en_mesa`; si el color no aparece en la cámara, el intento se aborta tras desencolar, con causa.
* **`detener`** no se encola (esperaría detrás de los demás): activa una bandera que el propio worker
  revisa entre lecturas y detiene el movimiento en curso. Nadie más toca el brazo.
* **IK propia + MoveIt para la trayectoria.** La IK usa la FK del RB-2, así que el error reportado es el
  del robot real y no una diferencia entre dos modelos. La meta de MoveIt es **articular**, por lo que no
  depende del marco cartesiano del URDF. Si `move_group` no está, el broker interpola (como el RB-2) y lo
  anota en la columna `planificador`; con `-p exigir_moveit:=true` el intento se aborta.
* **Cubo con simetría de 90°.** La IK prueba los 4 giros equivalentes de la pinza y elige el que menos
  mueve las articulaciones, partiendo de la rama "natural" (j5 ≈ 0).

## Pruebas sin ROS

```bash
cd ~/gran_reto_p2/src/arm_broker && python3 -m unittest discover -s test -v
```
