#!/usr/bin/env bash
# Ensayo de pedidos SIMULTÁNEOS: 4 clientes envían a la vez órdenes con urgencias distintas.
# (En la demostración real cada integrante lanza su cliente desde su máquina.)
#   bash ~/gran_reto_p2/herramientas/ensayo_4_clientes.sh
set -u
ros2 run arm_broker cliente_integrado --id ana   --frase "cuando puedas, lleva el cubo rojo a su lugar" &
ros2 run arm_broker cliente_integrado --id beto  --frase "toma el cubo verde" &
ros2 run arm_broker cliente_integrado --id caro  --frase "urgente: mueve el cubo amarillo ya" &
ros2 run arm_broker cliente_integrado --id dani  --frase "lanza el cubo azul contra la pared" &
wait
echo "--- listo: revisen evidencia_p2/intentos.csv y evidencia_p2/rechazos.csv"
