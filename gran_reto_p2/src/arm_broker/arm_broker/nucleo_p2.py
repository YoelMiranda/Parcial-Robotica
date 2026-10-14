"""Lógica de la Pregunta 2 SIN ROS (se puede probar con python3 -m unittest).

* admitir_agarre(): la admisión barata del goal_callback. Rechaza ANTES de encolar
  (orden no permitida, objeto que no está en la mesa, color o zona desconocidos...).
* EjecutorAgarre: lo que hace el worker al desencolar un pedido:
  percepción -> IK -> planificación (MoveIt 2) -> movimiento con el gripper.
"""

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from . import fk, ik
from . import DestinacionColores as DC
from .brazo import ParadaSolicitada
from .planificador_moveit import ErrorPlanificacion, interpolar, submuestrear

ACCIONES_AGARRE = ('recoger', 'depositar')


class ErrorAgarre(Exception):
    """Fallo con causa legible: el intento se aborta y el brazo vuelve a reposo."""


@dataclass
class ConfigMesa:
    destinos: Dict[str, List[float]] = field(default_factory=lambda: {k: list(v) for k, v in DC.DESTINOS.items()})
    posiciones_pick: Dict[str, List[float]] = field(default_factory=lambda: {k: list(v) for k, v in DC.POSICIONES_PICK.items()})
    zonas_a_cuadro: Dict[str, str] = field(default_factory=lambda: dict(DC.ZONAS_A_CUADRO))
    z_agarre: float = DC.Z_AGARRE
    z_seguro: float = DC.Z_SEGURO
    z_soltar: float = DC.Z_SOLTAR
    destino_si_falta: str = 'mismo_color'      # o 'rechazar'
    objetos_en_mesa: List[str] = field(default_factory=lambda: ['cubo'])
    objeto_por_defecto: str = 'cubo'           # "agarra el rojo" (sin objeto) => cubo
    gripper_abierto: int = 100
    gripper_cerrado: int = 25
    t_pinza_s: float = 1.5
    modo_posicion: str = 'slot'                # slot | camara | fijo
    tolerancia_slot_mm: float = 45.0
    tol_llegada_deg: float = 2.0
    tol_intermedia_deg: float = 6.0
    timeout_segmento_s: float = 10.0
    puntos_max_segmento: int = 6
    exigir_moveit: bool = False


def describir(accion, objeto, color, destino):
    if accion == 'ir_home':
        return 'ir a reposo'
    return f'{objeto} {color} -> cuadro {destino}'


def admitir_agarre(g, mesa: ConfigMesa):
    """g: goal con accion, objeto, color, zona, permitido, causa, motivo_rechazo, priority.
    Devuelve (ok, motivo, destino, descripcion). Barata: no toca el brazo ni la cámara.
    """
    if not g.permitido:
        causa = g.causa or 'no_permitida'
        texto = g.motivo_rechazo or 'orden no permitida'
        return False, f'orden NO PERMITIDA por el modelo [{causa}]: {texto}', '', ''
    if not 1 <= int(g.priority) <= 5:
        return False, f'prioridad fuera de rango: {g.priority} (se espera 1..5)', '', ''
    accion = g.accion or 'ninguna'
    if accion == 'ir_home':
        return True, '', 'reposo', 'ir a reposo'
    if accion not in ACCIONES_AGARRE:
        return False, f'la frase no es una orden de agarre ejecutable (acción = {accion})', '', ''

    objeto = g.objeto or 'ninguno'
    color = g.color or 'ninguno'
    if objeto == 'ninguno':
        if color == 'ninguno':
            if accion == 'depositar':
                return False, 'depositar sin objeto: el brazo no sostiene nada entre pedidos', '', ''
            return False, 'la orden no nombra ningún objeto ni color', '', ''
        objeto = mesa.objeto_por_defecto
    if objeto not in mesa.objetos_en_mesa:
        return False, (f'el objeto "{objeto}" no está sobre la mesa '
                       f'(hay: {", ".join(mesa.objetos_en_mesa)})'), '', ''
    if color == 'ninguno':
        return False, ('no se reconoce el color del objeto '
                       f'(en la mesa hay: {", ".join(mesa.posiciones_pick)})'), '', ''
    if color not in mesa.posiciones_pick:
        return False, f'no hay ningún {objeto} {color} sobre la mesa', '', ''
    destino, motivo = DC.resolver_destino(color, g.zona or 'ninguna', mesa.zonas_a_cuadro,
                                          mesa.destino_si_falta)
    if not destino:
        return False, motivo, '', ''
    if destino not in mesa.destinos:
        return False, f'el cuadro {destino} no tiene coordenadas configuradas', '', ''
    return True, '', destino, describir(accion, objeto, color, destino)


def _dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class EjecutorAgarre:
    """Ejecuta UN pedido. Lo invoca el broker desde la ejecución que dispara el worker."""

    def __init__(self, brazo, mesa: ConfigMesa, q_reposo, yaw_ref,
                 planificar: Callable, localizar: Callable,
                 publicar_q: Callable = lambda q: None, parada=None, log=print):
        self.brazo = brazo
        self.mesa = mesa
        self.q_reposo = list(q_reposo)
        self.yaw_ref = yaw_ref
        self._planificar = planificar      # (q0, q1) -> lista [(q, t)]  (lanza ErrorPlanificacion)
        self._localizar = localizar        # color -> dict de la cámara
        self.publicar_q = publicar_q
        self.parada = parada
        self.log = log

    # ------------------------------------------------------------- utilidades
    def q_actual(self):
        q = self.brazo.leer_angulos()
        if q is None:
            raise ErrorAgarre('no pude leer los ángulos del brazo')
        self.publicar_q(q)
        return q

    def planificar(self, q0, q1):
        """Devuelve (puntos, 'moveit' | 'interpolacion', aviso)."""
        try:
            return self._planificar(q0, q1), 'moveit', ''
        except ErrorPlanificacion as e:
            if self.mesa.exigir_moveit:
                raise ErrorAgarre(f'MoveIt falló y exigir_moveit=true: {e}')
            return interpolar(q0, q1), 'interpolacion', str(e)

    def ejecutar_trayectoria(self, puntos):
        pts = submuestrear(puntos, self.mesa.puntos_max_segmento)
        for i, (q, _t) in enumerate(pts):
            ultimo = i == len(pts) - 1
            ok, _ = fk.dentro_de_limites(q)
            if not ok:
                raise ErrorAgarre('la trayectoria sale de los límites articulares')
            self.brazo.enviar_angulos(q)
            tol = self.mesa.tol_llegada_deg if ultimo else self.mesa.tol_intermedia_deg
            llego, _ = self.brazo.esperar_llegada(q, tol_deg=tol,
                                                  timeout=self.mesa.timeout_segmento_s,
                                                  al_leer=self.publicar_q, parada=self.parada)
            if not llego and ultimo:
                self.log(f'aviso: no se alcanzó la tolerancia de {tol}° al final del segmento')

    def pinza(self, valor):
        self.brazo.pinza(valor)
        t0 = time.time()
        while time.time() - t0 < self.mesa.t_pinza_s:
            if self.parada is not None and self.parada.is_set():
                raise ParadaSolicitada('parada solicitada')
            time.sleep(0.05)

    def esta_en_reposo(self, q):
        return max(abs(a - b) for a, b in zip(q, self.q_reposo)) <= math.radians(3.0)

    def ir_a(self, q_obj):
        q0 = self.q_actual()
        puntos, plan, _ = self.planificar(q0, q_obj)
        self.ejecutar_trayectoria(puntos)
        return plan

    # ------------------------------------------------------------ posición
    def posicion_pick(self, color, loc):
        m = self.mesa
        if loc.get('xy_mm') is None or m.modo_posicion == 'fijo':
            metodo = 'posicion_conocida' + ('' if loc.get('xy_mm') is None else '(fijo)')
            return list(m.posiciones_pick[color]), metodo + '+camara_confirma'
        xy = list(loc['xy_mm'])
        if m.modo_posicion == 'camara':
            return xy, 'camara_homografia'
        nombre, slot = min(m.posiciones_pick.items(), key=lambda kv: _dist(kv[1], xy))
        d = _dist(slot, xy)
        if d > m.tolerancia_slot_mm:
            raise ErrorAgarre(f'la cámara ubica el {color} en ({xy[0]:.0f}, {xy[1]:.0f}) mm, '
                              f'a {d:.0f} mm de la posición conocida más cercana (máx {m.tolerancia_slot_mm:.0f})')
        return list(slot), f'slot_{nombre}(camara_d={d:.0f}mm)'

    # ------------------------------------------------------------- pedidos
    def ejecutar_home(self, al_etapa=lambda e: None):
        r = self._resultado_vacio()
        al_etapa('movimiento')
        t = time.time()
        r['inicio_movimiento_epoch'] = t
        r['planificador'] = self.ir_a(self.q_reposo)
        r['t_movimiento_s'] = time.time() - t
        return r

    def ejecutar_articular(self, q_obj, al_etapa=lambda e: None):
        r = self._resultado_vacio()
        al_etapa('planificacion')
        t = time.time()
        q0 = self.q_actual()
        puntos, r['planificador'], _ = self.planificar(q0, q_obj)
        r['t_planificacion_s'] = time.time() - t
        al_etapa('movimiento')
        t = time.time()
        r['inicio_movimiento_epoch'] = t
        self.ejecutar_trayectoria(puntos)
        r['t_movimiento_s'] = time.time() - t
        return r

    def ejecutar_agarre(self, color, destino, al_etapa=lambda e: None, guardar_imagen=None):
        m = self.mesa
        r = self._resultado_vacio()
        r['destino'] = destino

        # 1) preparación: la cámara solo sirve desde la pose de observación
        al_etapa('preparacion')
        t = time.time()
        q = self.q_actual()
        if not self.esta_en_reposo(q):
            self.ir_a(self.q_reposo)
        r['t_preparacion_s'] = time.time() - t

        # 2) percepción
        al_etapa('percepcion')
        t = time.time()
        loc = self._localizar(color, guardar_imagen)
        r['t_percepcion_s'] = time.time() - t
        r['imagen'] = loc.get('imagen', '')
        if not loc.get('encontrado'):
            raise ErrorAgarre(loc.get('motivo') or f'la cámara no encontró el objeto {color}')
        pick_xy, r['metodo_posicion'] = self.posicion_pick(color, loc)
        dest_xy = m.destinos[destino]
        r['pick_mm'] = [pick_xy[0], pick_xy[1], m.z_agarre]
        r['pos_solicitada_mm'] = [dest_xy[0], dest_xy[1], m.z_soltar]

        # 3) cinemática inversa (sobre la FK del RB-2)
        al_etapa('ik')
        t = time.time()
        objetivos = [
            ('sobre_objeto', (pick_xy[0], pick_xy[1], m.z_seguro)),
            ('agarre',       (pick_xy[0], pick_xy[1], m.z_agarre)),
            ('levantar',     (pick_xy[0], pick_xy[1], m.z_seguro)),
            ('sobre_destino', (dest_xy[0], dest_xy[1], m.z_seguro)),
            ('soltar',       (dest_xy[0], dest_xy[1], m.z_soltar)),
            ('salir',        (dest_xy[0], dest_xy[1], m.z_seguro)),
        ]
        qs = {}
        previo = q
        for nombre, p in objetivos:
            sol = ik.resolver(p, self.yaw_ref, [previo, self.q_reposo])
            if not sol['ok']:
                raise ErrorAgarre(f'{nombre}: {sol["motivo"]}')
            qs[nombre] = sol['q']
            previo = sol['q']
        r['t_ik_s'] = time.time() - t

        # 4) planificación de TODOS los tramos antes de mover (MoveIt 2)
        al_etapa('planificacion')
        t = time.time()
        cadena = [q, qs['sobre_objeto'], qs['agarre'], qs['levantar'], qs['sobre_destino'],
                  qs['soltar'], qs['salir'], self.q_reposo]
        tramos, planes = [], []
        for a, b in zip(cadena[:-1], cadena[1:]):
            puntos, plan, aviso = self.planificar(a, b)
            if aviso and aviso != 'MoveIt no disponible':   # (sin MoveIt ya se avisó al arrancar)
                self.log(f'MoveIt no planificó un tramo ({aviso}); uso interpolación')
            tramos.append(puntos)
            planes.append(plan)
        r['t_planificacion_s'] = time.time() - t
        r['planificador'] = planes[0] if len(set(planes)) == 1 else 'mixto(' + ','.join(planes) + ')'

        # 5) movimiento + gripper
        al_etapa('movimiento')
        t = time.time()
        r['inicio_movimiento_epoch'] = t
        self.brazo.pinza(m.gripper_abierto)
        self.ejecutar_trayectoria(tramos[0])        # sobre el objeto (la pinza abre en paralelo)
        self.ejecutar_trayectoria(tramos[1])        # bajar
        q_ag = self.q_actual()
        r['error_fk_pick_mm'] = _dist(fk.fk(q_ag), r['pick_mm'])
        self.pinza(m.gripper_cerrado)
        for k in (2, 3, 4):                         # levantar, trasladar, bajar al cuadro
            self.ejecutar_trayectoria(tramos[k])
        # ---- medición del error en el punto de entrega, ANTES de soltar ----
        time.sleep(0.3)
        q_ent = self.q_actual()
        p_fk = fk.fk(q_ent)
        r['q_entrega_deg'] = [round(math.degrees(v), 2) for v in q_ent]
        r['pos_fk_mm'] = list(p_fk)
        r['error_fk_mm'] = _dist(p_fk, r['pos_solicitada_mm'])
        c = self.brazo.leer_coords()
        if c:
            r['pos_get_coords_mm'] = c[:3]
            r['error_get_coords_mm'] = _dist(c[:3], r['pos_solicitada_mm'])
        self.pinza(m.gripper_abierto)
        r['t_movimiento_s'] = time.time() - t

        # 6) reposo (pose de observación: la cámara queda lista para el siguiente pedido)
        al_etapa('reposo')
        t = time.time()
        self.ejecutar_trayectoria(tramos[5])
        self.ejecutar_trayectoria(tramos[6])
        r['t_reposo_s'] = time.time() - t
        return r

    @staticmethod
    def _resultado_vacio():
        return {'destino': '', 'planificador': '', 'metodo_posicion': '', 'imagen': '',
                't_preparacion_s': 0.0, 't_percepcion_s': 0.0, 't_ik_s': 0.0,
                't_planificacion_s': 0.0, 't_movimiento_s': 0.0, 't_reposo_s': 0.0,
                'inicio_movimiento_epoch': 0.0, 'pick_mm': None, 'pos_solicitada_mm': None,
                'pos_fk_mm': None, 'error_fk_mm': -1.0, 'pos_get_coords_mm': None,
                'error_get_coords_mm': -1.0, 'error_fk_pick_mm': -1.0, 'q_entrega_deg': None}
