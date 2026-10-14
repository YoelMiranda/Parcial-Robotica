"""Cliente de la Pregunta 2. Cada integrante lo corre en SU máquina con su --id.

frase -> /interpretar_orden (P1) -> decisión tipada -> goal move_arm al broker.

* La PRIORIDAD del goal se copia de la decisión del modelo; este cliente no tiene
  ninguna opción para escribirla a mano.
* Si la orden no está permitida igual se envía: el BROKER la rechaza antes de encolar
  y deja la causa en su log, en rechazos.csv y en /arm/eventos (bag). Aquí se muestra.

Uso:
  ros2 run arm_broker cliente_integrado --id ana                       # modo interactivo
  ros2 run arm_broker cliente_integrado --id ana --frase "lleva el cubo rojo"
  ros2 run arm_broker cliente_integrado --id ana --frase "..." --frase "..."   # varias a la vez
"""

import argparse
import csv
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from arm_broker_interfaces.action import MoveArm
from jetcobot_interfaces.srv import InterpretarOrden

COLUMNAS = ['timestamp', 'client_id', 'pedido_id', 'frase', 'accion', 'objeto', 'color', 'zona',
            'prioridad', 'permitido', 'causa', 'fuente', 'degradado', 'latencia_decision_ms',
            't_origen_epoch', 't_envio_epoch', 'aceptado', 'motivo_rechazo_broker',
            'resultado', 'mensaje', 'espera_s', 'ejecucion_s', 'error_fk_mm', 'planificador',
            't_fin_epoch']


def _esperar(futuro, timeout):
    ev = threading.Event()
    futuro.add_done_callback(lambda _f: ev.set())
    if not ev.wait(timeout):
        return None
    return futuro.result()


class ClienteIntegrado(Node):

    def __init__(self, client_id, servicio='/interpretar_orden', carpeta='evidencia_clientes'):
        super().__init__(f'cliente_{"".join(c for c in client_id if c.isalnum()) or "x"}')
        self.client_id = client_id
        cg = ReentrantCallbackGroup()
        self.srv = self.create_client(InterpretarOrden, servicio, callback_group=cg)
        self.act = ActionClient(self, MoveArm, 'move_arm', callback_group=cg)
        self._rechazos = {}
        self._ev_rechazo = threading.Condition()
        self.create_subscription(String, '/arm/eventos', self._al_evento, 50, callback_group=cg)
        self._lock = threading.Lock()
        os.makedirs(carpeta, exist_ok=True)
        self.ruta_csv = os.path.join(carpeta, f'cliente_{client_id}.csv')
        self.pendientes = 0
        self._sin_pendientes = threading.Condition()

    # ------------------------------------------------------------------ salida
    def decir(self, texto):
        print(f'[{self.client_id} {datetime.now().strftime("%H:%M:%S")}] {texto}', flush=True)

    def _csv(self, fila):
        with self._lock:
            nuevo = not os.path.exists(self.ruta_csv)
            with open(self.ruta_csv, 'a', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction='ignore')
                if nuevo:
                    w.writeheader()
                w.writerow(fila)

    def _al_evento(self, msg):
        try:
            e = json.loads(msg.data)
        except ValueError:
            return
        if e.get('tipo') == 'rechazado' and e.get('pedido_id'):
            with self._ev_rechazo:
                self._rechazos[e['pedido_id']] = e.get('motivo', '')
                self._ev_rechazo.notify_all()

    def _motivo_broker(self, pedido_id, timeout=1.5):
        fin = time.time() + timeout
        with self._ev_rechazo:
            while pedido_id not in self._rechazos and time.time() < fin:
                self._ev_rechazo.wait(fin - time.time())
            return self._rechazos.pop(pedido_id, '')

    # ------------------------------------------------------------ esperar todo
    def _sumar(self, n):
        with self._sin_pendientes:
            self.pendientes += n
            self._sin_pendientes.notify_all()

    def esperar_todos(self):
        with self._sin_pendientes:
            while self.pendientes > 0:
                self._sin_pendientes.wait(0.5)

    # ---------------------------------------------------------------- pedido
    def interpretar(self, frase, timeout=6.0):
        if not self.srv.wait_for_service(timeout_sec=5.0):
            raise RuntimeError('no se encuentra /interpretar_orden: ¿corre interprete_ordenes '
                               'en el Jetson y estás en el mismo ROS_DOMAIN_ID?')
        req = InterpretarOrden.Request()
        req.frase = frase
        res = _esperar(self.srv.call_async(req), timeout)
        if res is None:
            raise RuntimeError('/interpretar_orden no respondió a tiempo')
        return res

    def enviar_frase(self, frase, t_origen_epoch=0.0, esperar_resultado=False, al_terminar=None):
        """Interpreta la frase y envía el goal. Devuelve la decisión (o None si falló)."""
        fila = {'timestamp': datetime.now().isoformat(timespec='milliseconds'),
                'client_id': self.client_id, 'frase': frase, 't_origen_epoch': t_origen_epoch}
        try:
            d = self.interpretar(frase)
        except RuntimeError as e:
            self.decir(f'❗ {e}')
            return None
        pedido_id = uuid.uuid4().hex[:8]
        fila.update(pedido_id=pedido_id, accion=d.accion, objeto=d.objeto, color=d.color, zona=d.zona,
                    prioridad=d.prioridad, permitido=d.permitido, causa=d.causa, fuente=d.fuente,
                    degradado=d.degradado, latencia_decision_ms=round(d.latencia_total_ms, 1))
        self.decir(f'"{frase}" -> {d.accion} {d.objeto} {d.color} {d.zona} · prioridad {d.prioridad} · '
                   f'permitido={d.permitido} · {d.fuente}{" (DEGRADADO)" if d.degradado else ""} · '
                   f'{d.latencia_total_ms:.0f} ms')

        goal = MoveArm.Goal()
        goal.client_id = self.client_id
        goal.priority = int(d.prioridad)          # <- la pone el MODELO, no el cliente
        goal.modo = 'home' if d.accion == 'ir_home' else 'agarre'
        goal.pedido_id = pedido_id
        goal.frase = frase
        goal.accion, goal.objeto, goal.color, goal.zona = d.accion, d.objeto, d.color, d.zona
        goal.permitido = bool(d.permitido)
        goal.causa = d.causa
        goal.motivo_rechazo = d.motivo_rechazo
        goal.degradado = bool(d.degradado)
        goal.fuente = d.fuente
        goal.latencia_decision_ms = float(d.latencia_total_ms)
        goal.t_origen_epoch = float(t_origen_epoch)
        goal.t_envio_epoch = time.time()
        fila['t_envio_epoch'] = goal.t_envio_epoch

        if not self.act.wait_for_server(timeout_sec=5.0):
            self.decir('❗ move_arm no está activo: ¿corre el broker en este ROS_DOMAIN_ID?')
            return d
        estado = {'pos': None, 'etapa': None}

        def feedback(msg):
            f = msg.feedback
            if f.queue_position != estado['pos'] or f.etapa != estado['etapa']:
                estado['pos'], estado['etapa'] = f.queue_position, f.etapa
                if f.state == 'QUEUED':
                    self.decir(f'   en cola: posición {f.queue_position} (esperando {f.elapsed_s:.1f} s)')
                else:
                    self.decir(f'   ejecutando: {f.etapa}')

        handle = _esperar(self.act.send_goal_async(goal, feedback_callback=feedback), 10.0)
        if handle is None:
            self.decir('❗ el broker no contestó la admisión')
            return d
        if not handle.accepted:
            motivo = self._motivo_broker(pedido_id) or d.motivo_rechazo or 'sin causa informada'
            self.decir(f'⛔ RECHAZADA por el broker (antes de encolar): {motivo}')
            fila.update(aceptado=False, motivo_rechazo_broker=motivo, resultado='rechazado')
            self._csv(fila)
            if al_terminar:
                al_terminar(fila)
            return d
        fila['aceptado'] = True
        self.decir(f'✔ aceptada en la cola con prioridad {d.prioridad} (pedido {pedido_id})')
        self._sumar(1)
        hecho = threading.Event()

        def al_resultado(fut):
            try:
                r = fut.result().result
                fila.update(resultado='ok' if r.success else 'fallo', mensaje=r.message,
                            espera_s=round(r.wait_time_s, 3), ejecucion_s=round(r.exec_time_s, 3),
                            error_fk_mm=round(r.error_fk_mm, 2), planificador=r.planificador,
                            t_fin_epoch=time.time())
                if r.success:
                    extra = f' · error FK {r.error_fk_mm:.1f} mm' if r.error_fk_mm >= 0 else ''
                    self.decir(f'✅ TERMINADO "{frase}" · destino {r.destino or "-"} · espera {r.wait_time_s:.1f} s · '
                               f'ejecución {r.exec_time_s:.1f} s · plan {r.planificador}{extra}')
                else:
                    self.decir(f'❌ NO COMPLETADO "{frase}": {r.message}')
                self._csv(fila)
                if al_terminar:
                    al_terminar(fila)
            finally:
                hecho.set()
                self._sumar(-1)

        handle.get_result_async().add_done_callback(al_resultado)
        if esperar_resultado:
            hecho.wait()
        return d


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description='Cliente integrado P2 (frase -> P1 -> broker)')
    ap.add_argument('--id', required=True, help='nombre del integrante (client_id)')
    ap.add_argument('--frase', action='append', help='frase a enviar (se puede repetir)')
    ap.add_argument('--servicio', default='/interpretar_orden')
    ap.add_argument('--evidencia', default='evidencia_clientes')
    args, ros_args = ap.parse_known_args(argv)

    rclpy.init(args=ros_args)
    nodo = ClienteIntegrado(args.id, args.servicio, args.evidencia)
    ex = MultiThreadedExecutor(num_threads=4)
    ex.add_node(nodo)
    hilo = threading.Thread(target=ex.spin, daemon=True)
    hilo.start()
    try:
        if args.frase:
            hilos = [threading.Thread(target=nodo.enviar_frase, args=(f,)) for f in args.frase]
            for h in hilos:
                h.start()
            for h in hilos:
                h.join()
            nodo.esperar_todos()
        else:
            nodo.decir('modo interactivo: escribe una orden y Enter (vacío o "salir" para terminar)')
            while True:
                try:
                    frase = input('> ').strip()
                except EOFError:
                    break
                if not frase or frase.lower() in ('salir', 'exit', 'q'):
                    break
                threading.Thread(target=nodo.enviar_frase, args=(frase,), daemon=True).start()
            nodo.decir('esperando los pedidos pendientes (Ctrl+C para salir ya)...')
            nodo.esperar_todos()
    except KeyboardInterrupt:
        pass
    finally:
        ex.shutdown()
        hilo.join(timeout=2.0)
        nodo.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
