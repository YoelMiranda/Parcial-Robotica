"""arm_broker — RB-2 extendido para la Pregunta 2 (agarre autónomo bajo la cola).

Se conserva la arquitectura del RB-2 (admisión barata -> cola con política -> UN worker
con exclusión mutua) y se reemplaza el "movimiento simulado" por la cadena real:

  goal (decisión de /interpretar_orden)
    -> goal_callback: rechaza ANTES de encolar si la orden no está permitida (con causa)
    -> cola de prioridad (la prioridad la puso el modelo, no el cliente)
    -> worker: cámara -> IK (FK del RB-2) -> MoveIt 2 planifica -> el broker mueve el brazo

Regla del publicador único: este nodo es el ÚNICO que abre el puerto del brazo y el
ÚNICO que publica /joint_states. MoveIt solo calcula trayectorias.
"""

import json
import math
import threading
import time

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String

from arm_broker_interfaces.action import MoveArm
from arm_broker_interfaces.msg import QueueState

from arm_broker import fk, ik
from arm_broker import DestinacionColores as DC
from arm_broker import CamaraColoresReconocimiento as CAM
from arm_broker.brazo import BrazoReal, BrazoSimulado, ParadaSolicitada
from arm_broker.evidencia import Evidencia
from arm_broker.nucleo_p2 import ConfigMesa, EjecutorAgarre, ErrorAgarre, admitir_agarre
from arm_broker.planificador_moveit import ErrorPlanificacion, PlanificadorMoveIt
from arm_broker.politicas import POLITICAS, Pedido


def _lista(texto, n=None):
    """'170, 55' | '[170,55]' -> [170.0, 55.0]. Se usan strings para evitar el lío int/double de ROS."""
    t = str(texto).strip().strip('[]').replace(';', ',')
    if not t:
        return []
    vals = [float(v) for v in t.replace(',', ' ').split()]
    if n is not None and len(vals) != n:
        raise ValueError(f'se esperaban {n} números y llegaron {len(vals)}: "{texto}"')
    return vals


def _palabras(texto):
    return [p.strip() for p in str(texto).replace(';', ',').split(',') if p.strip()]


class _Parada:
    """Se activa con la orden 'detener' o si el cliente cancela el goal en ejecución."""

    def __init__(self, evento, goal_handle):
        self.evento, self.gh = evento, goal_handle

    def is_set(self):
        return self.evento.is_set() or self.gh.is_cancel_requested


class ArmBroker(Node):

    def __init__(self):
        super().__init__('arm_broker')

        # ---------------- parámetros del RB-2 ----------------
        self.declare_parameter('politica', 'fifo')
        self.declare_parameter('tau_envejecimiento_s', 8.0)
        self.declare_parameter('cola_max', 20)
        self.declare_parameter('paso_max_rad', 1.2)
        self.declare_parameter('duracion_movimiento_s', 3.0)
        self.declare_parameter('pasos_interpolacion', 10)
        # ---------------- parámetros de la P2 ----------------
        P = self.declare_parameter
        P('simular', False)                       # true: sin brazo ni cámara (ensayo)
        P('puerto_brazo', '/dev/ttyTHS1')
        P('baudios', 1000000)
        P('velocidad', 40)                        # VELOCIDAD_SEGURA del notebook (0-100)
        P('usar_moveit', True)
        P('exigir_moveit', False)                 # true: sin MoveIt el intento se aborta
        P('moveit_grupo', 'arm_group')
        P('nombres_articulaciones', '')           # '' = autodetectar desde move_group
        P('moveit_tiempo_s', 2.0)
        P('moveit_escala_velocidad', 0.5)
        P('camara_indice', 0)
        P('calibracion_camara', 'calibracion_camara.json')
        P('modo_posicion', 'slot')                # slot | camara | fijo
        P('tolerancia_slot_mm', 45.0)
        P('pose_observacion_grados', '')          # 6 ángulos del notebook; '' = calcular con IK
        P('pose_observacion_mm', ', '.join(str(v) for v in DC.POS_OBSERVACION))
        P('yaw_pinza_extra_deg', 0.0)             # giro extra de la pinza respecto a la observación
        P('mover_a_reposo_al_iniciar', True)
        P('objetos_en_mesa', 'cubo')              # lo que REALMENTE hay sobre la mesa
        P('objeto_por_defecto', 'cubo')
        P('destino_si_falta', 'mismo_color')      # mismo_color | rechazar
        for z, cuadro in DC.ZONAS_A_CUADRO.items():
            P(z, cuadro)                          # zona_a / zona_b / zona_c -> cuadro de color
        for c in DC.COLORES:
            P(f'destino_{c}', ', '.join(str(v) for v in DC.DESTINOS[c]))
            P(f'pick_{c}', ', '.join(str(v) for v in DC.POSICIONES_PICK[c]))
        P('z_agarre', DC.Z_AGARRE)
        P('z_seguro', DC.Z_SEGURO)
        P('z_soltar', DC.Z_SOLTAR)
        P('gripper_abierto', 100)
        P('gripper_cerrado', 25)
        P('t_pinza_s', 1.5)
        P('carpeta_evidencia', 'evidencia_p2')
        P('colores_ausentes_sim', '')             # solo simulación: colores que la cámara "no ve"

        g = lambda n: self.get_parameter(n).value  # noqa: E731

        nombre = g('politica')
        if nombre not in POLITICAS:
            raise RuntimeError(f'política desconocida: {nombre}. Hay {list(POLITICAS)}')
        clase = POLITICAS[nombre]
        self.politica = clase(g('tau_envejecimiento_s')) if nombre == 'prioridad' else clase()

        self.cola_max = int(g('cola_max'))
        self.paso_max = float(g('paso_max_rad'))
        self.simular = bool(g('simular'))

        self.mesa = ConfigMesa(
            destinos={c: _lista(g(f'destino_{c}'), 2) for c in DC.COLORES},
            posiciones_pick={c: _lista(g(f'pick_{c}'), 2) for c in DC.COLORES},
            zonas_a_cuadro={z: str(g(z)).strip() for z in DC.ZONAS_A_CUADRO},
            z_agarre=float(g('z_agarre')), z_seguro=float(g('z_seguro')), z_soltar=float(g('z_soltar')),
            destino_si_falta=g('destino_si_falta'),
            objetos_en_mesa=_palabras(g('objetos_en_mesa')),
            objeto_por_defecto=g('objeto_por_defecto'),
            gripper_abierto=int(g('gripper_abierto')), gripper_cerrado=int(g('gripper_cerrado')),
            t_pinza_s=float(g('t_pinza_s')), modo_posicion=g('modo_posicion'),
            tolerancia_slot_mm=float(g('tolerancia_slot_mm')),
            exigir_moveit=bool(g('exigir_moveit')))

        self.grupo_entrada = ReentrantCallbackGroup()
        self.grupo_worker = MutuallyExclusiveCallbackGroup()

        self.lock = threading.Lock()
        self.pendientes = []
        self.por_goal_id = {}
        self.ejecutando = None
        self.q_actual = [0.0] * 6
        self.n_aceptados = 0
        self.n_rechazados = 0
        self.n_completados = 0
        self._parar = threading.Event()
        self._parada = threading.Event()
        self.evidencia = Evidencia(g('carpeta_evidencia'))

        self.pub_joint = self.create_publisher(JointState, '/joint_states', 10)
        self.pub_cola = self.create_publisher(QueueState, '/arm/queue_state', 10)
        self.pub_eventos = self.create_publisher(String, '/arm/eventos', 50)

        # ---------------- hardware (solo este nodo lo toca) ----------------
        if self.simular:
            self.brazo = BrazoSimulado(velocidad=int(g('velocidad')))
        else:
            self.brazo = BrazoReal(g('puerto_brazo'), int(g('baudios')), int(g('velocidad')))
        self._iniciar_camara(g)

        # ---------------- MoveIt 2 (solo planifica) ----------------
        self.nombres = list(fk.JOINT_NAMES)
        self.moveit = None
        if bool(g('usar_moveit')):
            self.moveit = PlanificadorMoveIt(
                self, grupo=g('moveit_grupo'), tiempo_planificacion=float(g('moveit_tiempo_s')),
                escala_velocidad=float(g('moveit_escala_velocidad')),
                escala_aceleracion=float(g('moveit_escala_velocidad')))
        # La conexión con MoveIt necesita el executor girando: se hace en el worker.

        # ---------------- pose de observación (= reposo) y yaw de la pinza ----------------
        q_obs_txt = str(g('pose_observacion_grados')).strip()
        if q_obs_txt:
            self.q_reposo = [math.radians(v) for v in _lista(q_obs_txt, 6)]
            origen = 'notebook (pose_observacion_grados)'
        else:
            p = _lista(g('pose_observacion_mm'), 3)
            semilla = ik.semilla_natural(p)
            sol = ik.resolver(p, ik.yaw_herramienta(semilla), [semilla], simetria_deg=0)
            if not sol['ok']:
                raise RuntimeError(f'pose de observación inalcanzable: {sol["motivo"]}')
            self.q_reposo = sol['q']
            origen = f'IK de {p} mm'
        self.yaw_ref = ik.yaw_herramienta(self.q_reposo) + math.radians(float(g('yaw_pinza_extra_deg')))
        incl = ik.inclinacion_deg(self.q_reposo)
        self.get_logger().info(
            f'pose de observación ({origen}): '
            f'{[round(math.degrees(v), 1) for v in self.q_reposo]}° · FK = '
            f'{tuple(round(v) for v in fk.fk(self.q_reposo))} mm · inclinación de la herramienta {incl:.0f}°')
        if incl > 15:
            self.get_logger().warn('la herramienta no apunta hacia abajo en la pose de observación '
                                   '(el agarre usa pinza vertical; revisen la pose)')

        self.ejecutor = EjecutorAgarre(
            self.brazo, self.mesa, self.q_reposo, self.yaw_ref,
            planificar=self._planificar, localizar=self._localizar,
            publicar_q=self.mover, parada=None, log=self.get_logger().warn)
        self._verificar_mesa()

        # ---------------- servidor de acción (RB-2) ----------------
        self.servidor = ActionServer(
            self, MoveArm, 'move_arm',
            goal_callback=self.goal_callback,
            handle_accepted_callback=self.handle_accepted_callback,
            cancel_callback=self.cancel_callback,
            execute_callback=self.execute_callback,
            callback_group=self.grupo_entrada)

        self.create_timer(0.2, self.publicar_estado_cola, callback_group=self.grupo_worker)

        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

        self.get_logger().info(
            f'arm_broker P2 listo · política={self.politica.nombre} · cola_max={self.cola_max} · '
            f'{"SIMULADO" if self.simular else "brazo " + g("puerto_brazo")} · '
            f'objetos en mesa={self.mesa.objetos_en_mesa} · zonas={self.mesa.zonas_a_cuadro} · '
            f'evidencia={self.evidencia.carpeta} · único publicador de /joint_states y del brazo')

    # ======================================================================
    # Arranque
    # ======================================================================
    def _iniciar_camara(self, g):
        self.calibracion = None
        if self.simular:
            ausentes = _palabras(g('colores_ausentes_sim'))
            self.camara = CAM.CamaraSimulada(self.mesa.posiciones_pick, ausentes)
            return
        try:
            self.camara = CAM.Camara(int(g('camara_indice')))
        except Exception as e:
            self.camara = None
            self.get_logger().error(f'CÁMARA no disponible: {e}. Los agarres se abortarán con la causa.')
        try:
            self.calibracion = CAM.cargar_calibracion(g('calibracion_camara'))
        except Exception as e:
            self.get_logger().error(f'calibración de cámara ilegible: {e}')
        if self.calibracion is None:
            self.get_logger().warn('sin calibracion_camara.json: la cámara solo confirma el color y '
                                   'se usa la posición conocida de cada color (pick_<color>)')

    def _verificar_mesa(self):
        """Comprueba al arrancar que todas las posiciones de la mesa tienen IK."""
        m = self.mesa
        malas = []
        for nombre, xy, z in ([(f'pick_{c}', xy, m.z_agarre) for c, xy in m.posiciones_pick.items()] +
                              [(f'destino_{c}', xy, m.z_soltar) for c, xy in m.destinos.items()]):
            for zz in (z, m.z_seguro):
                sol = ik.resolver((xy[0], xy[1], zz), self.yaw_ref, [self.q_reposo])
                if not sol['ok']:
                    malas.append(f'{nombre} z={zz:.0f}')
        if malas:
            self.get_logger().error(f'SIN IK (revisen coordenadas): {malas}')
        else:
            self.get_logger().info('IK verificada para las 4 posiciones de recojo y los 4 cuadros')

    def _autodiagnostico(self):
        q = self.brazo.leer_angulos()
        c = self.brazo.leer_coords()
        if q is None:
            self.get_logger().error('AUTODIAGNÓSTICO: no pude leer los ángulos del brazo')
            return
        self.mover(q)
        p = fk.fk(q)
        texto = (f'AUTODIAGNÓSTICO · ángulos {[round(math.degrees(v), 1) for v in q]}° · '
                 f'FK RB-2 = ({p[0]:.0f}, {p[1]:.0f}, {p[2]:.0f}) mm')
        if c:
            d = math.dist(p, c[:3])
            texto += f' · get_coords = ({c[0]:.0f}, {c[1]:.0f}, {c[2]:.0f}) mm · diferencia {d:.1f} mm'
            if d > 20:
                texto += '  <-- ¡más de 20 mm! revisen fk.py antes de medir errores'
        self.get_logger().info(texto)

    def _conectar_moveit(self):
        if self.moveit is None:
            self.get_logger().warn('usar_moveit=false: se planifica con interpolación articular')
            return
        ok, msg = self.moveit.conectar(timeout=5.0)
        if not ok:
            nivel = self.get_logger().error if self.mesa.exigir_moveit else self.get_logger().warn
            nivel(msg + ' -> se usará interpolación articular' if not self.mesa.exigir_moveit else msg)
            return
        txt = str(self.get_parameter('nombres_articulaciones').value).strip()
        if txt:
            self.moveit.nombres = _palabras(txt)
            info = f'nombres fijados por parámetro: {self.moveit.nombres}'
        else:
            _, info = self.moveit.resolver_nombres(fk.JOINT_NAMES)
        self.nombres = list(self.moveit.nombres)
        self.get_logger().info(f'{msg} · grupo={self.moveit.grupo} · {info}')

    # ======================================================================
    # Admisión (barata, inmediata): acepta o rechaza, nunca ejecuta
    # ======================================================================
    def _evento(self, tipo, **datos):
        datos.update(tipo=tipo, t=time.time())
        self.pub_eventos.publish(String(data=json.dumps(datos, ensure_ascii=False, default=str)))

    def _registrar_rechazo(self, goal_request, motivo):
        """Log de ROS + rechazos.csv + /arm/eventos (va al bag). El cliente muestra la causa."""
        g = goal_request
        self.get_logger().warn(
            f'⛔ RECHAZADO [{g.client_id}, prioridad {g.priority}] "{g.frase}": {motivo}')
        self.evidencia.rechazo({
            'client_id': g.client_id, 'pedido_id': g.pedido_id, 'priority': int(g.priority),
            'frase': g.frase, 'accion': g.accion, 'objeto': g.objeto, 'color': g.color,
            'zona': g.zona, 'permitido': g.permitido, 'causa_modelo': g.causa, 'motivo': motivo,
            'joint_positions': ' '.join(f'{v:.4f}' for v in g.joint_positions)})
        self._evento('rechazado', client_id=g.client_id, pedido_id=g.pedido_id, frase=g.frase,
                     prioridad=int(g.priority), causa=g.causa, motivo=motivo)

    @staticmethod
    def _modo(goal_request):
        m = (goal_request.modo or '').strip()
        if not m:
            m = 'articular' if len(goal_request.joint_positions) else 'agarre'
        if m == 'agarre' and goal_request.accion == 'ir_home':
            m = 'home'
        return m

    def _admitir_articular(self, goal_request):
        """Admisión original del RB-2 (modo articular)."""
        q = list(goal_request.joint_positions)
        ok, motivo = fk.dentro_de_limites(q)
        if ok:
            ok, motivo = fk.dentro_del_workspace(q)
            if not ok:
                motivo = f'fuera del workspace: {motivo}'
        else:
            motivo = f'fuera de límites articulares: {motivo}'
        if ok:
            with self.lock:
                q_desde = list(self.q_actual)
            paso = fk.paso_articular(q_desde, q)
            if paso > self.paso_max:
                ok = False
                j = max(range(6), key=lambda i: abs(q[i] - q_desde[i]))
                motivo = (f'paso articular excesivo: {paso:.2f} rad en {fk.JOINT_NAMES[j]} '
                          f'(máximo {self.paso_max:.2f} rad)')
        return ok, motivo, '', f'articular {[round(v, 2) for v in q]}'

    def _admitir(self, goal_request):
        modo = self._modo(goal_request)
        if modo == 'articular':
            return self._admitir_articular(goal_request)
        return admitir_agarre(goal_request, self.mesa)

    def goal_callback(self, goal_request):
        motivo = ''
        try:
            modo = self._modo(goal_request)
            if modo != 'articular' and goal_request.permitido and goal_request.accion == 'detener':
                # 'detener' no se encola: detiene el pedido en curso (lo ejecuta el propio worker)
                with self.lock:
                    activo = self.ejecutando
                if activo is not None:
                    self._parada.set()
                    motivo = f'orden de PARADA atendida fuera de la cola: se detiene {activo}'
                else:
                    motivo = 'orden de PARADA: no hay ningún pedido en ejecución'
                ok = False
            else:
                ok, motivo, _, _ = self._admitir(goal_request)
            if ok:
                with self.lock:
                    llena = len(self.pendientes) >= self.cola_max
                if llena:
                    ok = False
                    motivo = f'cola llena ({self.cola_max} pedidos en espera)'
        except Exception as e:  # una admisión que falla no debe tumbar al broker
            ok = False
            motivo = f'error interno de admisión: {e}'

        if not ok:
            with self.lock:
                self.n_rechazados += 1
            self._registrar_rechazo(goal_request, motivo)
            return GoalResponse.REJECT

        with self.lock:
            self.n_aceptados += 1
        return GoalResponse.ACCEPT

    def handle_accepted_callback(self, goal_handle):
        """Encolar. AQUÍ NO SE EJECUTA NADA, y no se publica en /joint_states."""
        req = goal_handle.request
        _, _, destino, descripcion = self._admitir(req)
        info = {'modo': self._modo(req), 'destino': destino, 'descripcion': descripcion,
                'frase': req.frase, 'pedido_id': req.pedido_id}
        pedido = Pedido(goal_handle, req.client_id, req.priority, req.joint_positions, info)
        with self.lock:
            self.pendientes.append(pedido)
            self.por_goal_id[pedido.goal_id] = pedido
            n = len(self.pendientes)
        self.get_logger().info(f'ENCOLADO {pedido} · en espera: {n}')
        self._evento('encolado', client_id=req.client_id, pedido_id=req.pedido_id,
                     goal_id=pedido.goal_id, prioridad=pedido.priority, descripcion=descripcion,
                     frase=req.frase, en_espera=n)

    # ======================================================================
    # Worker: el único que decide a quién le toca (y el único que usa el brazo)
    # ======================================================================
    def _worker(self):
        time.sleep(0.5)
        try:
            self._conectar_moveit()
            self._autodiagnostico()
            if self.get_parameter('mover_a_reposo_al_iniciar').value:
                self.get_logger().info('llevando el brazo a la pose de observación (reposo)...')
                self.ejecutor.parada = None
                self.ejecutor.ir_a(self.q_reposo)
                self.get_logger().info('brazo en reposo: listo para recibir pedidos')
        except Exception as e:
            self.get_logger().error(f'no pude llevar el brazo a reposo al iniciar: {e}')

        t_lectura = 0.0
        while not self._parar.is_set():
            pedido = None
            with self.lock:
                cancelados = [p for p in self.pendientes if p.goal_handle.is_cancel_requested]
                for p in cancelados:
                    self.pendientes.remove(p)
                    self.por_goal_id.pop(p.goal_id, None)
                if self.ejecutando is None and self.pendientes:
                    i = self.politica.siguiente(self.pendientes)
                    if i is not None:
                        pedido = self.pendientes.pop(i)
                        pedido.t_inicio_ejec = time.time()
                        self.ejecutando = pedido

            for p in cancelados:
                self.get_logger().info(f'CANCELADO en cola {p}')
                try:
                    p.goal_handle.canceled()
                except Exception as e:
                    self.get_logger().warn(f'No pude cerrar el goal cancelado {p}: {e}')
                p.fin.set()

            if pedido is None:
                # En reposo el worker lee el brazo y publica /joint_states (único publicador).
                if time.time() - t_lectura > 0.5:
                    t_lectura = time.time()
                    try:
                        q = self.brazo.leer_angulos()
                        if q is not None:
                            self.mover(q)
                    except Exception:
                        pass
                time.sleep(0.01)
                continue

            self.get_logger().info(f'EJECUTANDO {pedido} · esperó {pedido.espera_s:.2f} s')
            self._evento('inicio', client_id=pedido.client_id, pedido_id=pedido.info.get('pedido_id'),
                         goal_id=pedido.goal_id, prioridad=pedido.priority,
                         descripcion=pedido.info.get('descripcion'), espera_s=pedido.espera_s)
            try:
                pedido.goal_handle.execute()
            except Exception as e:
                self.get_logger().error(f'execute() falló para {pedido}: {e}')
                try:
                    pedido.goal_handle.abort()
                except Exception:
                    pass
                pedido.resultado = 'aborted'
                pedido.fin.set()

            # Exclusión mutua: hasta que no termine este, no se toca el siguiente.
            while not pedido.fin.wait(0.2):
                if self._parar.is_set():
                    break

            with self.lock:
                self.ejecutando = None
                self.por_goal_id.pop(pedido.goal_id, None)
                if pedido.resultado == 'succeeded':
                    self.n_completados += 1
            self.politica.atendido(pedido)

    # ----------------------------------------------------- percepción / plan
    def _localizar(self, color, guardar_imagen=None):
        if self.simular:
            return CAM.localizar_simulado(self.camara, color)
        if self.camara is None:
            return {'encontrado': False, 'motivo': 'la cámara no está disponible', 'imagen': ''}
        return CAM.localizar(self.camara, color, self.calibracion, guardar_en=guardar_imagen,
                             despues_de=time.time() + 0.3)   # espera a que el brazo esté quieto

    def _planificar(self, q0, q1):
        if self.moveit is None or not self.moveit.disponible:
            raise ErrorPlanificacion('MoveIt no disponible')
        return self.moveit.planificar(q0, q1)

    def execute_callback(self, goal_handle):
        """Ejecutar UN pedido. Lo dispara el worker (vía execute()), nunca handle_accepted."""
        resultado = MoveArm.Result()
        resultado.error_fk_mm = -1.0
        pedido = self.por_goal_id.get(bytes(goal_handle.goal_id.uuid).hex()[:12])
        if pedido is None:
            goal_handle.abort()
            resultado.success = False
            resultado.message = 'goal desconocido para el broker'
            return resultado

        req = goal_handle.request
        modo = pedido.info['modo']
        espera = (pedido.t_inicio_ejec or time.time()) - pedido.t_llegada
        self._parada.clear()
        self.ejecutor.parada = _Parada(self._parada, goal_handle)

        def al_etapa(etapa):
            pedido.etapa = etapa
            fb = MoveArm.Feedback()
            fb.state = 'EXECUTING'
            fb.queue_position = 0
            fb.elapsed_s = time.time() - pedido.t_inicio_ejec
            fb.etapa = etapa
            try:
                goal_handle.publish_feedback(fb)
            except Exception:
                pass
            self._evento('etapa', client_id=pedido.client_id, pedido_id=req.pedido_id,
                         goal_id=pedido.goal_id, etapa=etapa)

        r = EjecutorAgarre._resultado_vacio()
        estado, causa = 'aborted', ''
        try:
            if modo == 'agarre':
                img = self.evidencia.ruta_imagen(req.pedido_id or pedido.goal_id, req.color)
                r = self.ejecutor.ejecutar_agarre(req.color, pedido.info['destino'], al_etapa,
                                                  guardar_imagen=None if self.simular else img)
            elif modo == 'home':
                r = self.ejecutor.ejecutar_home(al_etapa)
            else:
                r = self.ejecutor.ejecutar_articular([float(v) for v in req.joint_positions], al_etapa)
            estado = 'succeeded'
        except ParadaSolicitada as e:
            causa = f'cancelado/detenido: {e}'
            estado = 'canceled' if goal_handle.is_cancel_requested else 'aborted'
        except (ErrorAgarre, ErrorPlanificacion) as e:
            causa = str(e)
        except Exception as e:
            causa = f'error al ejecutar: {e}'
            self.get_logger().error(causa)

        if estado != 'succeeded' and not self._parada.is_set():
            # El intento se aborta con su causa y el brazo vuelve a reposo.
            self.get_logger().warn(f'ABORTADO {pedido}: {causa} -> vuelvo a reposo')
            try:
                self.ejecutor.parada = None
                self.ejecutor.ir_a(self.q_reposo)
            except Exception as e:
                self.get_logger().error(f'no pude volver a reposo: {e}')

        fin = time.time()
        try:
            if estado == 'succeeded':
                goal_handle.succeed()
            elif estado == 'canceled':
                goal_handle.canceled()
            else:
                goal_handle.abort()
        except Exception as e:
            self.get_logger().warn(f'no pude cerrar el goal: {e}')
        pedido.resultado = estado

        resultado.success = estado == 'succeeded'
        resultado.message = 'ok' if resultado.success else causa
        resultado.wait_time_s = espera
        resultado.exec_time_s = fin - pedido.t_inicio_ejec
        resultado.destino = r.get('destino') or ''
        resultado.planificador = '+'.join(x for x in ('simulado' if self.simular else '',
                                                      r.get('planificador') or '') if x)
        resultado.error_fk_mm = float(r.get('error_fk_mm', -1.0))
        for k in ('t_percepcion_s', 't_ik_s', 't_planificacion_s', 't_movimiento_s',
                  'inicio_movimiento_epoch'):
            setattr(resultado, k, float(r.get(k) or 0.0))

        if modo != 'articular':
            fila = dict(r)
            fila.update({
                'simulado': self.simular, 'client_id': pedido.client_id, 'pedido_id': req.pedido_id,
                'frase': req.frase, 'modo': modo, 'accion': req.accion, 'objeto': req.objeto,
                'color': req.color, 'zona': req.zona, 'destino': pedido.info.get('destino'),
                'prioridad': pedido.priority, 'fuente_decision': req.fuente, 'degradado': req.degradado,
                'latencia_decision_ms': req.latencia_decision_ms, 't_origen_epoch': req.t_origen_epoch,
                't_envio_epoch': req.t_envio_epoch, 't_llegada_epoch': pedido.t_llegada,
                't_espera_s': espera, 'fin_epoch': fin, 'resultado': estado, 'causa': causa,
                'planificador': resultado.planificador})
            n = self.evidencia.intento(fila)
            self.get_logger().info(
                f'{"✅" if resultado.success else "❌"} intento #{n} {pedido} · {estado} · '
                f'error FK {resultado.error_fk_mm:.1f} mm · plan={resultado.planificador} · '
                f'espera {espera:.1f}s percep {resultado.t_percepcion_s:.2f}s ik {resultado.t_ik_s:.2f}s '
                f'plan {resultado.t_planificacion_s:.2f}s mov {resultado.t_movimiento_s:.1f}s'
                + (f' · causa: {causa}' if causa else ''))
        self._evento('fin', client_id=pedido.client_id, pedido_id=req.pedido_id, goal_id=pedido.goal_id,
                     resultado=estado, causa=causa, error_fk_mm=resultado.error_fk_mm,
                     planificador=resultado.planificador)
        pedido.fin.set()  # sin esto el worker esperaría para siempre
        return resultado

    def cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    # ----------------------------------------------------------- publicar
    def mover(self, q):
        """Publica el estado REAL del brazo en /joint_states (único publicador)."""
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'base_link'
        msg.name = list(self.nombres)
        msg.position = [float(v) for v in q]
        self.pub_joint.publish(msg)
        with self.lock:
            self.q_actual = list(q)

    def publicar_estado_cola(self):
        msg = QueueState()
        msg.stamp = self.get_clock().now().to_msg()
        puntaje = getattr(self.politica, 'puntaje', lambda p: float(p.priority))
        with self.lock:
            ej = self.ejecutando
            msg.executing_client = ej.client_id if ej else ''
            msg.executing_goal_id = ej.goal_id if ej else ''
            msg.executing_elapsed_s = (time.time() - ej.t_inicio_ejec) if ej and ej.t_inicio_ejec else 0.0
            msg.executing_descripcion = ej.info.get('descripcion', '') if ej else ''
            msg.executing_etapa = ej.etapa if ej else ''
            msg.queue_length = len(self.pendientes)
            msg.queued_goal_ids = [p.goal_id for p in self.pendientes]
            msg.queued_clients = [p.client_id for p in self.pendientes]
            msg.queued_priorities = [min(255, max(0, p.priority)) for p in self.pendientes]
            msg.queued_wait_s = [p.espera_s for p in self.pendientes]
            msg.queued_descripciones = [p.info.get('descripcion', '') for p in self.pendientes]
            msg.queued_puntajes = [float(puntaje(p)) for p in self.pendientes]
            msg.total_accepted = self.n_aceptados
            msg.total_rejected = self.n_rechazados
            msg.total_completed = self.n_completados
            msg.politica = self.politica.nombre
            cola = list(self.pendientes)
        self.pub_cola.publish(msg)

        # Posición en la cola según el ORDEN DE ATENCIÓN de la política
        orden = sorted(cola, key=lambda p: (-puntaje(p), p.t_llegada)) if self.politica.nombre == 'prioridad' \
            else sorted(cola, key=lambda p: p.t_llegada)
        for posicion, p in enumerate(orden, start=1):
            try:
                fb = MoveArm.Feedback()
                fb.state = 'QUEUED'
                fb.queue_position = posicion
                fb.elapsed_s = p.espera_s
                p.goal_handle.publish_feedback(fb)
            except Exception:
                pass

    def destroy_node(self):
        self._parar.set()
        try:
            if self.camara is not None:
                self.camara.cerrar()
        except Exception:
            pass
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    nodo = ArmBroker()
    executor = MultiThreadedExecutor(num_threads=8)
    executor.add_node(nodo)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        nodo.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
