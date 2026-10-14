"""Pantalla de la cola del broker para el video de la P2.

  ros2 run arm_broker monitor_cola

Muestra el pedido en ejecución (con su etapa), la cola en el ORDEN en que se atenderá
(prioridad + envejecimiento) y los últimos eventos: encolados, rechazos con su causa y fines.
"""

import json
import threading
import time
from collections import deque
from datetime import datetime

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from arm_broker_interfaces.msg import QueueState

COLOR = {'rechazado': '\033[91m', 'fin': '\033[92m', 'encolado': '\033[96m', 'inicio': '\033[93m'}
FIN = '\033[0m'
NEGRITA = '\033[1m'


class Monitor(Node):
    def __init__(self):
        super().__init__('monitor_cola')
        self.estado = None
        self.eventos = deque(maxlen=12)
        self.lock = threading.Lock()
        self.create_subscription(QueueState, '/arm/queue_state', self._cola, 10)
        self.create_subscription(String, '/arm/eventos', self._evento, 50)

    def _cola(self, msg):
        with self.lock:
            self.estado = msg

    def _evento(self, msg):
        try:
            e = json.loads(msg.data)
        except ValueError:
            return
        if e.get('tipo') == 'etapa':
            return
        hora = datetime.fromtimestamp(e.get('t', time.time())).strftime('%H:%M:%S')
        t = e.get('tipo')
        if t == 'encolado':
            txt = f'ENCOLADO   {e.get("client_id")} p{e.get("prioridad")} {e.get("descripcion")}'
        elif t == 'rechazado':
            txt = f'⛔ RECHAZO {e.get("client_id")} "{e.get("frase")}" -> {e.get("motivo")}'
        elif t == 'inicio':
            txt = f'INICIO     {e.get("client_id")} p{e.get("prioridad")} {e.get("descripcion")} (esperó {e.get("espera_s", 0):.1f} s)'
        elif t == 'fin':
            ok = e.get('resultado') == 'succeeded'
            err = e.get('error_fk_mm', -1)
            txt = (f'{"✅ FIN" if ok else "❌ FIN"}      {e.get("client_id")} {e.get("resultado")}'
                   + (f' · error FK {err:.1f} mm' if ok and err is not None and err >= 0 else '')
                   + (f' · {e.get("causa")}' if e.get('causa') else ''))
        else:
            txt = json.dumps(e, ensure_ascii=False)
        with self.lock:
            self.eventos.appendleft(f'{COLOR.get(t, "")}{hora}  {txt}{FIN}')

    def dibujar(self):
        with self.lock:
            s = self.estado
            ev = list(self.eventos)
        out = ['\033[2J\033[H', f'{NEGRITA}COLA DEL BROKER · {datetime.now().strftime("%H:%M:%S")}{FIN}']
        if s is None:
            out.append('esperando /arm/queue_state ... (¿corre el broker en este ROS_DOMAIN_ID?)')
        else:
            out.append(f'política: {s.politica or "?"} · aceptados {s.total_accepted} · '
                       f'rechazados {s.total_rejected} · completados {s.total_completed}')
            out.append('')
            if s.executing_client:
                out.append(f'{NEGRITA}EJECUTANDO{FIN}  {s.executing_client:<10} {s.executing_descripcion:<34} '
                           f'etapa: {s.executing_etapa:<13} {s.executing_elapsed_s:5.1f} s')
            else:
                out.append('EJECUTANDO  (nada: brazo en reposo)')
            out.append('')
            out.append(f'{NEGRITA}EN COLA ({s.queue_length}) — orden de atención{FIN}')
            filas = list(zip(s.queued_clients, s.queued_priorities, s.queued_wait_s,
                             s.queued_descripciones or [''] * s.queue_length,
                             s.queued_puntajes or [float(p) for p in s.queued_priorities]))
            if s.politica == 'prioridad':
                filas.sort(key=lambda f: -f[4])
            out.append(f'  {"#":>2}  {"cliente":<10} {"prio":>4} {"puntaje":>7} {"espera":>7}  pedido')
            for i, (c, p, w, d, pt) in enumerate(filas, 1):
                out.append(f'  {i:>2}  {c:<10} {p:>4} {pt:7.2f} {w:6.1f}s  {d}')
            if not filas:
                out.append('  (vacía)')
        out.append('')
        out.append(f'{NEGRITA}EVENTOS{FIN}')
        out.extend(ev or ['  (ninguno aún)'])
        print('\n'.join(out), flush=True)


def main(args=None):
    rclpy.init(args=args)
    nodo = Monitor()
    from rclpy.executors import SingleThreadedExecutor
    ex = SingleThreadedExecutor()
    ex.add_node(nodo)
    hilo = threading.Thread(target=ex.spin, daemon=True)
    hilo.start()
    try:
        while rclpy.ok():
            nodo.dibujar()
            time.sleep(0.25)
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
