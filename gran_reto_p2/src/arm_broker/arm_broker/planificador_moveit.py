"""MoveIt 2 como PLANIFICADOR (no como ejecutor).

El broker le pide a move_group una trayectoria articular con el servicio
/plan_kinematic_path (moveit_msgs/srv/GetMotionPlan): estado inicial = ángulos
reales leídos del brazo, meta = solución de la IK (restricciones articulares).
MoveIt devuelve la trayectoria (puntos + tiempos) y NO mueve nada: quien la envía
al brazo es el worker del broker. Así se respeta la regla del publicador único.

Si move_group no está corriendo, el broker usa interpolación articular (como el
RB-2) y lo anota en la columna `planificador` del CSV.
"""

import threading

try:
    from moveit_msgs.msg import Constraints, JointConstraint, PlanningSceneComponents
    from moveit_msgs.srv import GetMotionPlan, GetPlanningScene
    HAY_MOVEIT_MSGS = True
except ImportError:  # moveit_msgs no instalado: el broker cae a interpolación
    HAY_MOVEIT_MSGS = False

PALABRAS_PINZA = ('grip', 'finger', 'hand', 'claw', 'pinza', 'gripper')


class ErrorPlanificacion(Exception):
    pass


def _esperar(futuro, timeout):
    evento = threading.Event()
    futuro.add_done_callback(lambda _f: evento.set())
    if not evento.wait(timeout):
        futuro.cancel()
        return None
    return futuro.result()


class PlanificadorMoveIt:

    def __init__(self, nodo, grupo='arm_group', nombres=None, tiempo_planificacion=2.0,
                 escala_velocidad=0.5, escala_aceleracion=0.5, intentos=3,
                 servicio_plan='/plan_kinematic_path', servicio_escena='/get_planning_scene'):
        self.nodo = nodo
        self.grupo = grupo
        self.nombres = list(nombres) if nombres else None
        self.tiempo = float(tiempo_planificacion)
        self.vel = float(escala_velocidad)
        self.acc = float(escala_aceleracion)
        self.intentos = int(intentos)
        self.disponible = False
        if not HAY_MOVEIT_MSGS:
            return
        from rclpy.callback_groups import ReentrantCallbackGroup
        cg = ReentrantCallbackGroup()
        self.cli_plan = nodo.create_client(GetMotionPlan, servicio_plan, callback_group=cg)
        self.cli_escena = nodo.create_client(GetPlanningScene, servicio_escena, callback_group=cg)

    # ------------------------------------------------------------------ arranque
    def conectar(self, timeout=3.0):
        if not HAY_MOVEIT_MSGS:
            return False, 'moveit_msgs no está instalado (sudo apt install ros-humble-moveit-msgs)'
        if not self.cli_plan.wait_for_service(timeout_sec=timeout):
            return False, 'MoveIt 2 NO responde (/plan_kinematic_path): ¿se lanzó move_group en este ROS_DOMAIN_ID?'
        self.disponible = True
        return True, 'MoveIt 2 disponible'

    def nombres_del_robot(self, timeout=3.0):
        """Nombres de articulaciones que conoce move_group (para casar con el URDF)."""
        if not self.cli_escena.wait_for_service(timeout_sec=timeout):
            return []
        req = GetPlanningScene.Request()
        req.components.components = PlanningSceneComponents.ROBOT_STATE
        res = _esperar(self.cli_escena.call_async(req), timeout)
        if res is None:
            return []
        return list(res.scene.robot_state.joint_state.name)

    def resolver_nombres(self, preferidos):
        """Elige los 6 nombres de articulación del brazo tal como los llama el URDF de MoveIt."""
        todos = self.nombres_del_robot()
        if not todos:
            self.nombres = list(preferidos)
            return self.nombres, 'no pude leer los nombres de MoveIt; uso los del RB-2'
        if all(n in todos for n in preferidos):
            self.nombres = list(preferidos)
            return self.nombres, f'nombres del RB-2 presentes en MoveIt: {self.nombres}'
        brazo = [n for n in todos if not any(p in n.lower() for p in PALABRAS_PINZA)]
        if len(brazo) >= 6:
            self.nombres = brazo[:6]
            return self.nombres, (f'MoveIt usa otros nombres; tomé {self.nombres} de {todos}. '
                                  'Si el orden no es base->muñeca, fíjenlo con nombres_articulaciones')
        self.nombres = list(preferidos)
        return self.nombres, f'no pude casar nombres; MoveIt tiene {todos}'

    # ---------------------------------------------------------------- planificar
    def planificar(self, q_inicio, q_fin, timeout=None):
        """Trayectoria de q_inicio a q_fin. Devuelve [(q[6] rad, t_s), ...] en el orden de self.nombres."""
        if not self.disponible:
            raise ErrorPlanificacion('MoveIt no disponible')
        req = GetMotionPlan.Request()
        m = req.motion_plan_request
        m.group_name = self.grupo
        m.num_planning_attempts = self.intentos
        m.allowed_planning_time = self.tiempo
        m.max_velocity_scaling_factor = self.vel
        m.max_acceleration_scaling_factor = self.acc
        m.start_state.joint_state.name = list(self.nombres)
        m.start_state.joint_state.position = [float(v) for v in q_inicio]
        m.start_state.is_diff = False
        c = Constraints()
        for n, v in zip(self.nombres, q_fin):
            jc = JointConstraint()
            jc.joint_name = n
            jc.position = float(v)
            jc.tolerance_above = 0.005
            jc.tolerance_below = 0.005
            jc.weight = 1.0
            c.joint_constraints.append(jc)
        m.goal_constraints = [c]
        res = _esperar(self.cli_plan.call_async(req), timeout or (self.tiempo * self.intentos + 3.0))
        if res is None:
            raise ErrorPlanificacion('MoveIt no respondió a tiempo')
        r = res.motion_plan_response
        if r.error_code.val != 1:
            raise ErrorPlanificacion(f'MoveIt no encontró trayectoria (error_code {r.error_code.val})')
        jt = r.trajectory.joint_trajectory
        try:
            idx = [list(jt.joint_names).index(n) for n in self.nombres]
        except ValueError:
            raise ErrorPlanificacion(f'MoveIt devolvió {list(jt.joint_names)} y esperaba {self.nombres}: '
                                     'ajusten el parámetro nombres_articulaciones')
        puntos = []
        for p in jt.points:
            t = p.time_from_start.sec + p.time_from_start.nanosec * 1e-9
            puntos.append(([float(p.positions[i]) for i in idx], t))
        if not puntos:
            raise ErrorPlanificacion('MoveIt devolvió una trayectoria vacía')
        return puntos


def interpolar(q_inicio, q_fin, pasos=10, vel_rad_s=0.8):
    """Respaldo sin MoveIt: interpolación articular lineal (como el RB-2)."""
    salto = max(abs(b - a) for a, b in zip(q_inicio, q_fin))
    duracion = max(0.5, salto / vel_rad_s)
    pasos = max(1, pasos)
    return [([a + (b - a) * k / pasos for a, b in zip(q_inicio, q_fin)], duracion * k / pasos)
            for k in range(1, pasos + 1)]


def submuestrear(puntos, n_max=6):
    """Pocos puntos intermedios: el firmware suaviza entre ellos; muchos saturan el puerto serie."""
    if len(puntos) <= n_max:
        return list(puntos)
    paso = (len(puntos) - 1) / float(n_max - 1)
    idx = sorted({int(round(i * paso)) for i in range(n_max)} | {len(puntos) - 1})
    return [puntos[i] for i in idx]

