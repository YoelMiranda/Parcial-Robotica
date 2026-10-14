"""Políticas de cola — ítems 2 y 3 del RB-2 (sin cambios en las políticas).

P2: Pedido guarda además la decisión de la P1 (info) y la etapa en curso.
"""

import threading
import time


class Pedido:
    def __init__(self, goal_handle, client_id, priority, joint_positions, info=None):
        self.goal_handle = goal_handle
        self.goal_id = bytes(goal_handle.goal_id.uuid).hex()[:12]
        self.client_id = client_id
        self.priority = int(priority)
        self.joint_positions = list(joint_positions)
        self.t_llegada = time.time()
        self.t_inicio_ejec = None
        self.fin = threading.Event()
        self.resultado = None
        self.info = dict(info or {})      # P2: modo, frase, color, destino, descripcion...
        self.etapa = ''

    @property
    def espera_s(self):
        fin = self.t_inicio_ejec if self.t_inicio_ejec else time.time()
        return fin - self.t_llegada

    def __repr__(self):
        desc = self.info.get('descripcion', '')
        return f'<{self.client_id} p{self.priority} {self.goal_id}{" " + desc if desc else ""}>'


class Politica:
    nombre = 'base'

    def siguiente(self, pendientes):
        raise NotImplementedError

    def atendido(self, pedido):
        pass


# ============================== IMPLEMENTAR · ítems 2 y 3 =========================
# FIFO es obligatoria. La segunda la eligen ustedes y la justifican en el README:
# prioridad estática, prioridad con envejecimiento, o round-robin entre clientes.
#
# siguiente(pendientes) devuelve el ÍNDICE del pedido a atender, o None.
# Cada Pedido trae: client_id, priority, t_llegada y espera_s.

class FIFO(Politica):
    """Primero en llegar, primero en ser atendido. Ignora la prioridad."""
    nombre = 'fifo'

    def siguiente(self, pendientes):
        if not pendientes:
            return None
        return min(range(len(pendientes)), key=lambda i: pendientes[i].t_llegada)


class SegundaPolitica(Politica):
    """Prioridad con envejecimiento.

    Puntaje = prioridad + espera_s / tau. Gana el mayor (mayor número = más urgente).
    Cada tau segundos de espera equivalen a subir un nivel de prioridad, así que un
    pedido poco urgente termina alcanzando a uno urgente y no espera para siempre
    (evita la inanición de la prioridad más baja). Si dos empatan, el que llegó antes.

    tau grande  -> se comporta como prioridad estática.
    tau pequeño -> se comporta como FIFO.
    """
    nombre = 'prioridad'

    def __init__(self, tau=8.0):
        self.tau = max(1e-6, float(tau))

    def puntaje(self, pedido):
        return pedido.priority + pedido.espera_s / self.tau

    def siguiente(self, pendientes):
        if not pendientes:
            return None
        return max(range(len(pendientes)),
                   key=lambda i: (self.puntaje(pendientes[i]), -pendientes[i].t_llegada))

# =================================================================================


POLITICAS = {
    'fifo': FIFO,
    'prioridad': SegundaPolitica,
}
