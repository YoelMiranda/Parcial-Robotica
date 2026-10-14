#!/usr/bin/env python3
"""Nodo ROS 2 `interprete_ordenes` -> servicio /interpretar_orden.

Es el ÚNICO punto de contacto con el servidor LAYA (HTTP). Ningún otro nodo
del equipo habla con la computadora Windows.
"""
import json
import os

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rcl_interfaces.msg import SetParametersResult

from jetcobot_interfaces.srv import InterpretarOrden

from .cliente_laya import ClienteLaya
from .nucleo import Interprete


class InterpreteOrdenes(Node):
    def __init__(self):
        super().__init__("interprete_ordenes")
        # ---- parámetros ----
        self.declare_parameter("laya_url", "http://127.0.0.1:8000")   # IP:puerto que da el docente
        self.declare_parameter("laya_endpoint", "/v1/systemone")
        self.declare_parameter("timeout_s", 1.0)            # TIEMPO LÍMITE de LAYA (parámetro exigido)
        self.declare_parameter("modelo", "")                # campo `model` (checkpoint/preset del docente)
        self.declare_parameter("lang", "es")
        self.declare_parameter("extra_json", "")            # campos extra del cuerpo, p. ej. '{"task":"x"}'
        self.declare_parameter("api_key_env", "LAYA_API_KEY")  # NOMBRE de la variable de entorno (opcional)
        self.declare_parameter("umbral_peligro", 0.5)       # P(peligrosa) >= umbral => permitido=false
        self.declare_parameter("invertir_prioridad", False) # true si en el broker 1 = más urgente
        self.declare_parameter("log_csv", "")               # bitácora de cada consulta (evidencia)
        self.declare_parameter("modo_decision", "laya")     # laya | hibrido (LAYA + capa de verificación)
        self.declare_parameter("umbral_veto_laya", 0.9)     # hibrido: LAYA veta una orden clara solo si P >= esto
        self.declare_parameter("hilos", 8)

        g = self.get_parameter
        timeout_s = float(g("timeout_s").value)
        if timeout_s <= 0.0:
            raise ValueError("timeout_s debe ser > 0")
        extra = {}
        if g("extra_json").value:
            extra = json.loads(g("extra_json").value)
        # La clave (si el servidor la exige) se lee del entorno; nunca del código.
        api_key = os.environ.get(g("api_key_env").value, "")

        self.cliente = ClienteLaya(
            url=g("laya_url").value, endpoint=g("laya_endpoint").value, api_key=api_key,
            modelo=g("modelo").value, lang=g("lang").value, extra=extra)
        self.nucleo = Interprete(
            self.cliente, timeout_s=timeout_s, umbral_peligro=float(g("umbral_peligro").value),
            invertir_prioridad=bool(g("invertir_prioridad").value), log_csv=g("log_csv").value,
            modo_decision=str(g("modo_decision").value),
            umbral_veto_laya=float(g("umbral_veto_laya").value))

        self.add_on_set_parameters_callback(self._al_cambiar_parametros)
        self.srv = self.create_service(
            InterpretarOrden, "/interpretar_orden", self._atender,
            callback_group=ReentrantCallbackGroup())
        self.get_logger().info(
            "interprete_ordenes listo | LAYA=%s%s | timeout_s=%.3f | modo_decision=%s | servicio=/interpretar_orden"
            % (g("laya_url").value, g("laya_endpoint").value, timeout_s, g("modo_decision").value))

    # Permite ajustar el límite en caliente: ros2 param set /interprete_ordenes timeout_s 0.5
    def _al_cambiar_parametros(self, params):
        for p in params:
            if p.name == "timeout_s":
                if float(p.value) <= 0.0:
                    return SetParametersResult(successful=False, reason="timeout_s debe ser > 0")
                self.nucleo.timeout_s = float(p.value)
            elif p.name == "umbral_peligro":
                self.nucleo.umbral_peligro = float(p.value)
            elif p.name == "umbral_veto_laya":
                self.nucleo.umbral_veto_laya = float(p.value)
            elif p.name == "modo_decision":
                if str(p.value) not in ("laya", "hibrido"):
                    return SetParametersResult(successful=False, reason="modo_decision: laya | hibrido")
                self.nucleo.modo_decision = str(p.value)
        return SetParametersResult(successful=True)

    def _atender(self, request, response):
        d = self.nucleo.interpretar(request.frase)
        response.accion = d.accion
        response.objeto = d.objeto
        response.color = d.color
        response.zona = d.zona
        response.prioridad = int(d.prioridad)
        response.permitido = bool(d.permitido)
        response.causa = d.causa
        response.motivo_rechazo = d.motivo_rechazo
        response.degradado = bool(d.degradado)
        response.fuente = d.fuente
        response.detalle_error = d.detalle_error
        response.latencia_total_ms = float(d.latencia_total_ms)
        response.latencia_rtt_ms = float(d.latencia_rtt_ms)
        response.latencia_servidor_ms = float(d.latencia_servidor_ms)
        response.latencia_red_ms = float(d.latencia_red_ms)
        nivel = self.get_logger().warn if d.degradado else self.get_logger().info
        nivel("'%s' -> %s %s %s %s prio=%d permitido=%s [%s%s] %.1f ms"
              % (request.frase, d.accion, d.objeto, d.color, d.zona, d.prioridad, d.permitido,
                 d.fuente, " DEGRADADO: " + d.detalle_error if d.degradado else "",
                 d.latencia_total_ms))
        if d.correcciones:
            self.get_logger().info("   reglas corrigieron a LAYA: %s" % d.correcciones)
        return response


def main(args=None):
    rclpy.init(args=args)
    nodo = InterpreteOrdenes()
    ejecutor = MultiThreadedExecutor(num_threads=int(nodo.get_parameter("hilos").value))
    ejecutor.add_node(nodo)
    try:
        ejecutor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        nodo.cliente.cerrar()
        nodo.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
