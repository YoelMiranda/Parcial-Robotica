"""Cinemática inversa del JetCobot construida SOBRE la FK del RB-2 (fk.py).

Por qué una IK propia y no la del firmware (send_coords):
  * Usa exactamente la misma tabla DH con la que luego se mide el error, así que
    el error reportado es el del robot real (servos, holguras), no una diferencia
    entre dos modelos cinemáticos distintos.
  * Devuelve ángulos articulares, que es lo que MoveIt 2 necesita como meta para
    planificar la trayectoria (meta articular: no depende del marco del URDF).

Método: mínimos cuadrados amortiguados (Levenberg-Marquardt) con jacobiano
numérico, sobre 6 restricciones:
  * posición (x, y, z) de la brida en mm, mismo marco que get_coords;
  * eje z de la herramienta apuntando hacia abajo (agarre vertical);
  * yaw de la pinza (ángulo del eje x de la herramienta en el plano de la mesa).
Para un cubo, girar la pinza 90° da el mismo agarre, así que se prueban los
4 yaw equivalentes y se elige la solución que menos mueve las articulaciones.
"""

import math

import numpy as np

from . import fk

Z_ABAJO = np.array([0.0, 0.0, -1.0])
PESO_ORIENTACION_MM = 100.0   # 1 rad de error de orientación "pesa" como 100 mm


def _t(alpha, a, d, theta):
    ca, sa = math.cos(alpha), math.sin(alpha)
    ct, st = math.cos(theta), math.sin(theta)
    return np.array([[ct, -st, 0.0, a],
                     [st * ca, ct * ca, -sa, -sa * d],
                     [st * sa, ct * sa, ca, ca * d],
                     [0.0, 0.0, 0.0, 1.0]])


def matriz(q):
    """Igual que fk.fk_matriz (misma tabla DH del RB-2), pero con numpy: ~20x más rápida."""
    T = np.eye(4)
    for (alpha, a, d, off), theta in zip(fk.DH, q):
        T = T @ _t(alpha, a, d, float(theta) + off)
    return T


def yaw_herramienta(q):
    """Ángulo [rad] del eje x de la herramienta proyectado en el plano XY."""
    T = matriz(q)
    return math.atan2(T[1, 0], T[0, 0])


def inclinacion_deg(q):
    """Ángulo [°] entre el eje z de la herramienta y la vertical hacia abajo."""
    T = matriz(q)
    c = float(np.clip(np.dot(T[:3, 2], Z_ABAJO), -1.0, 1.0))
    return math.degrees(math.acos(c))


def _rot_objetivo(yaw):
    x = np.array([math.cos(yaw), math.sin(yaw), 0.0])
    z = Z_ABAJO
    y = np.cross(z, x)
    return np.column_stack([x, y, z])


def _rotvec(R):
    """Vector eje*ángulo [rad] de una rotación (log de SO(3)), estable cerca de 0 y de pi."""
    c = float(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))
    ang = math.acos(c)
    if ang < 1e-9:
        return np.zeros(3)
    if ang < math.pi - 1e-4:
        w = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
        return w * ang / (2.0 * math.sin(ang))
    # cerca de 180°: eje desde la diagonal
    eje = np.sqrt(np.maximum((np.diag(R) + 1.0) / 2.0, 0.0))
    k = int(np.argmax(eje))
    if eje[k] > 1e-9:
        for j in range(3):
            if j != k:
                eje[j] = math.copysign(eje[j], R[k, j] + R[j, k])
    return eje / max(np.linalg.norm(eje), 1e-12) * ang


def _error(q, p_obj, R_obj):
    """Residuo 6D: posición (mm) y orientación (eje*ángulo, rad) hacia el objetivo."""
    T = matriz(q)
    e_p = p_obj - T[:3, 3]
    e_o = _rotvec(R_obj @ T[:3, :3].T)
    return np.concatenate([e_p, PESO_ORIENTACION_MM * e_o]), e_p, e_o


def _limitar(q):
    return np.array([min(max(v, lo), hi) for v, (lo, hi) in zip(q, fk.JOINT_LIMITS)])


def _resolver_un_yaw(p_obj, yaw, semilla, iter_max=80, tol_mm=0.5):
    R_obj = _rot_objetivo(yaw)
    q = _limitar(np.array(semilla, dtype=float))
    lam = 1.0
    e, _, _ = _error(q, p_obj, R_obj)
    costo = float(e @ e)
    h = 1e-6
    for _ in range(iter_max):
        J = np.zeros((6, 6))
        for j in range(6):
            dq = np.zeros(6)
            dq[j] = h
            e2, _, _ = _error(q + dq, p_obj, R_obj)
            J[:, j] = -(e2 - e) / h
        A = J.T @ J + lam * np.eye(6)
        paso = np.linalg.solve(A, J.T @ e)
        q_nuevo = _limitar(q + paso)
        e_nuevo, _, _ = _error(q_nuevo, p_obj, R_obj)
        c_nuevo = float(e_nuevo @ e_nuevo)
        if c_nuevo < costo:
            q, e, costo = q_nuevo, e_nuevo, c_nuevo
            lam = max(lam / 3.0, 1e-6)
            if math.sqrt(costo) < tol_mm:
                break
        else:
            lam *= 4.0
            if lam > 1e8:
                break
    _, e_p, e_o = _error(q, p_obj, R_obj)
    return q, float(np.linalg.norm(e_p)), math.degrees(float(np.linalg.norm(e_o)))


def semilla_natural(p_mm, j6=0.0):
    """Configuración típica de agarre vertical del MyCobot 280 (j5 = 0, j2+j3+j4 = -90°)
    girada hacia el objetivo. Sirve de semilla para quedarse en la rama "natural"."""
    x, y = float(p_mm[0]), float(p_mm[1])
    r = max(1e-6, math.hypot(x, y))
    desfase = math.asin(max(-1.0, min(1.0, 63.4 / r)))   # brazo lateral d4 = 63.4 mm
    j1 = math.atan2(y, x) + desfase
    return [j1, math.radians(-20), math.radians(-80), math.radians(10), 0.0, j6]


def resolver(p_mm, yaw_ref, semillas, tol_pos_mm=2.0, tol_ori_deg=3.0, simetria_deg=90.0):
    """IK para una pose de agarre vertical.

    p_mm:     (x, y, z) objetivo de la brida, mm (mismo marco que get_coords).
    yaw_ref:  yaw [rad] de referencia de la pinza (alineado con los cubos).
    semillas: lista de configuraciones iniciales (la primera = la actual).
    Devuelve dict con q (rad), error_pos_mm, error_ori_deg, yaw, ok y motivo.
    """
    p_obj = np.array(p_mm, dtype=float)
    q_ref = np.array(semillas[0], dtype=float)
    semillas = [semilla_natural(p_mm, float(q_ref[5]))] + list(semillas)
    n_yaw = max(1, int(round(360.0 / simetria_deg))) if simetria_deg > 0 else 1
    candidatos = []
    for k in range(n_yaw):
        yaw = yaw_ref + math.radians(simetria_deg) * k
        for s in semillas:   # la primera semilla que converge basta para este yaw
            q, ep, eo = _resolver_un_yaw(p_obj, yaw, s)
            ok_lim, _ = fk.dentro_de_limites(list(q))
            if ep <= tol_pos_mm and eo <= tol_ori_deg and ok_lim:
                # costo: lo que más se mueve una articulación + castigo a muñeca "doblada" (j5)
                costo = float(np.max(np.abs(q - q_ref))) + 0.5 * abs(float(q[4]))
                candidatos.append((costo, q, ep, eo, yaw))
                break
    if not candidatos:
        return {'ok': False, 'q': None, 'error_pos_mm': None, 'error_ori_deg': None,
                'yaw': None,
                'motivo': f'sin solución de IK para {tuple(round(v, 1) for v in p_mm)} mm '
                          f'con la pinza vertical (¿fuera de alcance?)'}
    candidatos.sort(key=lambda c: c[0])
    _, q, ep, eo, yaw = candidatos[0]
    return {'ok': True, 'q': [float(v) for v in q], 'error_pos_mm': ep, 'error_ori_deg': eo,
            'yaw': yaw, 'motivo': ''}
