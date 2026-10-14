"""Cinemática directa del JetCobot (MyCobot 280) — ítem 1."""

import math

JOINT_NAMES = ['1_Joint', '2_Joint', '3_Joint', '4_Joint', '5_Joint', '6_Joint']

# ============================== IMPLEMENTAR · ítem 1 ==============================
# Tabla DH del JetCobot (MyCobot 280). OJO: _t() implementa la convención DH
# MODIFICADA (Craig): T_i = Rx(alpha_{i-1}) Tx(a_{i-1}) Rz(theta_i) Tz(d_i).
# Por eso cada fila trae (alpha_{i-1}, a_{i-1}, d_i, theta_offset_i).
# Equivale a la tabla DH estándar: d1=131.22, a2=-110.4, a3=-96, d4=63.4,
# d5=75.05, d6=53.7 (45.6 de hoja de datos + ~8 mm de referencia del firmware); alpha = [pi/2, 0, 0, pi/2, -pi/2, 0];
# offsets = [0, -pi/2, 0, -pi/2, pi/2, 0]. Calibrada y verificada contra el robot: error <= 7.1 mm en 5 poses.
DH = [
    (0.0,          0.0,    131.22,  0.0),
    (math.pi / 2,  0.0,    0.0,    -math.pi / 2),
    (0.0,         -110.4,  0.0,     0.0),
    (0.0,         -96.0,   63.4,   -math.pi / 2),
    (math.pi / 2,  0.0,    75.05,   math.pi / 2),
    (-math.pi / 2, 0.0,    53.7,    0.0),   # d6: 45.6 (hoja de datos) + ~8.1 mm calibrados
]

JOINT_LIMITS = [
    (-2.93, 2.93),
    (-2.36, 2.36),
    (-2.53, 2.53),
    (-2.58, 2.58),
    (-2.93, 2.93),
    (-3.14, 3.14),
]

ALCANCE_MIN_MM = 80.0
ALCANCE_MAX_MM = 480.0


def _t(alpha, a, d, theta):
    ca, sa = math.cos(alpha), math.sin(alpha)
    ct, st = math.cos(theta), math.sin(theta)
    return [
        [ct,      -st,      0.0,   a],
        [st * ca,  ct * ca, -sa,  -sa * d],
        [st * sa,  ct * sa,  ca,   ca * d],
        [0.0,      0.0,      0.0,  1.0],
    ]


def _mul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def fk_matriz(q):
    """Matriz homogénea 4x4 de la base al efector final."""
    T = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    for (alpha, a, d, off), theta in zip(DH, q):
        T = _mul(T, _t(alpha, a, d, theta + off))
    return T


def fk(q):
    """Posición (x, y, z) del efector final, en milímetros desde la base.

    Con la tabla DH llena, fk_matriz(q) ya devuelve la matriz homogénea: la
    posición son sus tres primeros elementos de la última columna.
    """
    T = fk_matriz(q)
    return (T[0][3], T[1][3], T[2][3])
# =================================================================================


def dentro_de_limites(q):
    if len(q) != 6:
        return False, f'se esperaban 6 ángulos, llegaron {len(q)}'
    for i, (valor, (lo, hi)) in enumerate(zip(q, JOINT_LIMITS)):
        if not lo <= valor <= hi:
            return False, f'{JOINT_NAMES[i]} fuera de rango: {valor:.3f} rad, límite [{lo}, {hi}]'
    return True, ''


def dentro_del_workspace(q):
    x, y, z = fk(q)
    r = math.sqrt(x * x + y * y + z * z)
    if r > ALCANCE_MAX_MM:
        return False, f'efector a {r:.0f} mm de la base, máximo {ALCANCE_MAX_MM:.0f}'
    if r < ALCANCE_MIN_MM:
        return False, f'efector a {r:.0f} mm de la base, demasiado cerca'
    if z < 0.0:
        return False, f'z = {z:.0f} mm: el efector quedaría bajo la base'
    return True, ''


def paso_articular(q_desde, q_hasta):
    return max(abs(b - a) for a, b in zip(q_desde, q_hasta))
