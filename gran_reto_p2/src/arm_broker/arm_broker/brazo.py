"""Acceso al JetCobot. SOLO lo usa el broker (regla del publicador único del RB-2).

BrazoReal envuelve pymycobot (puerto serie). BrazoSimulado permite ensayar todo el
flujo sin hardware. Ambos trabajan en RADIANES hacia el broker; la conversión a grados
del firmware se hace aquí. Todas las llamadas pasan por un candado: el puerto serie
nunca se usa desde dos hilos a la vez.
"""

import math
import threading
import time

from . import fk


class ParadaSolicitada(Exception):
    """Se pidió detener el brazo (orden 'detener')."""


class _Base:
    def __init__(self):
        self.lock = threading.RLock()

    def esperar_llegada(self, q_obj, tol_deg=2.0, timeout=8.0, al_leer=None, parada=None):
        """Espera hasta que todas las articulaciones estén a menos de tol_deg del objetivo."""
        t0 = time.time()
        q = None
        while time.time() - t0 < timeout:
            if parada is not None and parada.is_set():
                self.detener()
                raise ParadaSolicitada('parada solicitada durante el movimiento')
            q = self.leer_angulos()
            if q is not None:
                if al_leer:
                    al_leer(q)
                if max(abs(a - b) for a, b in zip(q, q_obj)) <= math.radians(tol_deg):
                    return True, q
            time.sleep(0.05)
        return False, q


class BrazoReal(_Base):
    def __init__(self, puerto='/dev/ttyTHS1', baudios=1000000, velocidad=40):
        super().__init__()
        try:
            from pymycobot import MyCobot280 as _MC
        except ImportError:
            from pymycobot.mycobot import MyCobot as _MC
        self.mc = _MC(puerto, baudios)
        self.velocidad = int(velocidad)
        time.sleep(0.5)
        with self.lock:
            try:
                self.mc.power_on()
            except Exception:
                pass
        if self.leer_angulos() is None:
            raise RuntimeError(f'el brazo no responde en {puerto} (¿otro proceso tiene el puerto?)')

    def _reintentar(self, f, n=4):
        for _ in range(n):
            with self.lock:
                try:
                    v = f()
                except Exception:
                    v = None
            if isinstance(v, (list, tuple)) and len(v) >= 6:
                return [float(x) for x in v[:6]]
            time.sleep(0.03)
        return None

    def leer_angulos(self):
        g = self._reintentar(self.mc.get_angles)
        return [math.radians(v) for v in g] if g else None

    def leer_coords(self):
        return self._reintentar(self.mc.get_coords)   # [x, y, z, rx, ry, rz] mm / grados

    def enviar_angulos(self, q, velocidad=None):
        grados = [round(math.degrees(v), 2) for v in q]
        with self.lock:
            self.mc.send_angles(grados, int(velocidad or self.velocidad))

    def pinza(self, valor, velocidad=None):
        with self.lock:
            self.mc.set_gripper_value(int(valor), int(velocidad or self.velocidad))

    def detener(self):
        with self.lock:
            try:
                self.mc.stop()
            except Exception:
                pass


class BrazoSimulado(_Base):
    """Integra el movimiento a velocidad constante. Las coords salen de la FK del RB-2."""

    def __init__(self, q_inicial=None, velocidad=40, ruido_deg=0.3):
        super().__init__()
        self.q = list(q_inicial or [0.0] * 6)
        self.q_obj = list(self.q)
        self.vel_rad_s = math.radians(20 + 1.6 * velocidad)   # aprox. a velocidad 40: ~84 °/s
        self.velocidad = velocidad
        self.ruido = math.radians(ruido_deg)
        self._t = time.time()

    def _avanzar(self):
        ahora = time.time()
        dt, self._t = ahora - self._t, ahora
        paso = self.vel_rad_s * dt
        self.q = [a + max(-paso, min(paso, b - a)) for a, b in zip(self.q, self.q_obj)]

    def leer_angulos(self):
        with self.lock:
            self._avanzar()
            return list(self.q)

    def leer_coords(self):
        x, y, z = fk.fk(self.leer_angulos())
        return [x, y, z, 180.0, 0.0, 0.0]

    def enviar_angulos(self, q, velocidad=None):
        with self.lock:
            self._avanzar()
            # el servo real nunca llega exacto: se simula un pequeño error de seguimiento
            import random
            self.q_obj = [v + random.uniform(-self.ruido, self.ruido) for v in q]

    def esperar_llegada(self, q_obj, tol_deg=2.0, timeout=8.0, al_leer=None, parada=None):
        return super().esperar_llegada(q_obj, max(tol_deg, math.degrees(self.ruido) + 0.5),
                                       timeout, al_leer, parada)

    def pinza(self, valor, velocidad=None):
        time.sleep(0.05)

    def detener(self):
        with self.lock:
            self._avanzar()
            self.q_obj = list(self.q)
