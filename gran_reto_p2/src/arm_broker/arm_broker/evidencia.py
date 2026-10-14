"""Evidencia de la Pregunta 2: intentos.csv (una fila por pedido ejecutado) y rechazos.csv.

Carpeta: parámetro `carpeta_evidencia` del broker (por defecto ./evidencia_p2).
La columna `exito_manual` se llena a mano (si/no) mirando la mesa o el video:
    ros2 run arm_broker tabla_intentos evidencia_p2/intentos.csv --marcar 3 si
"""

import csv
import os
import threading
from datetime import datetime

COLUMNAS_INTENTOS = [
    'intento', 'timestamp', 'simulado', 'client_id', 'pedido_id', 'frase', 'modo',
    'accion', 'objeto', 'color', 'zona', 'destino', 'prioridad',
    'fuente_decision', 'degradado', 'latencia_decision_ms',
    't_origen_epoch', 't_envio_epoch', 't_llegada_epoch',
    't_espera_s', 't_preparacion_s', 't_percepcion_s', 't_ik_s', 't_planificacion_s',
    't_movimiento_s', 't_reposo_s', 'inicio_movimiento_epoch', 'fin_epoch',
    'planificador', 'metodo_posicion', 'pick_mm', 'error_fk_pick_mm',
    'pos_solicitada_mm', 'pos_fk_mm', 'error_fk_mm', 'pos_get_coords_mm', 'error_get_coords_mm',
    'q_entrega_deg', 'resultado', 'causa', 'imagen', 'exito_manual',
]
COLUMNAS_RECHAZOS = ['hora', 'client_id', 'pedido_id', 'priority', 'frase', 'accion', 'objeto',
                     'color', 'zona', 'permitido', 'causa_modelo', 'motivo', 'joint_positions']


def _fmt(v):
    if isinstance(v, float):
        return f'{v:.4f}'
    if isinstance(v, (list, tuple)):
        return ' '.join(f'{x:.1f}' if isinstance(x, float) else str(x) for x in v)
    if v is None:
        return ''
    return v


class Evidencia:
    def __init__(self, carpeta):
        self.carpeta = os.path.abspath(carpeta)
        os.makedirs(os.path.join(self.carpeta, 'img'), exist_ok=True)
        self.ruta_intentos = os.path.join(self.carpeta, 'intentos.csv')
        self.ruta_rechazos = os.environ.get('ARM_BROKER_RECHAZOS',
                                            os.path.join(self.carpeta, 'rechazos.csv'))
        self._lock = threading.Lock()
        self.n_intento = self._contar(self.ruta_intentos)

    @staticmethod
    def _contar(ruta):
        if not os.path.exists(ruta):
            return 0
        with open(ruta, newline='', encoding='utf-8') as f:
            return max(0, sum(1 for _ in f) - 1)

    def ruta_imagen(self, pedido_id, color):
        hora = datetime.now().strftime('%H%M%S')
        return os.path.join(self.carpeta, 'img', f'{hora}_{pedido_id}_{color}.jpg')

    def _escribir(self, ruta, columnas, fila):
        with self._lock:
            nuevo = not os.path.exists(ruta)
            with open(ruta, 'a', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=columnas, extrasaction='ignore')
                if nuevo:
                    w.writeheader()
                w.writerow({k: _fmt(fila.get(k, '')) for k in columnas})

    def intento(self, fila):
        with self._lock:
            self.n_intento += 1
            fila['intento'] = self.n_intento
        fila.setdefault('timestamp', datetime.now().isoformat(timespec='milliseconds'))
        fila.setdefault('exito_manual', '')
        self._escribir(self.ruta_intentos, COLUMNAS_INTENTOS, fila)
        return fila['intento']

    def rechazo(self, fila):
        fila.setdefault('hora', datetime.now().isoformat(timespec='milliseconds'))
        self._escribir(self.ruta_rechazos, COLUMNAS_RECHAZOS, fila)
