"""Mesa del examen: dónde están los objetos y a dónde se llevan (antes: Nivel 4 del notebook).

Todas las coordenadas están en mm, en el MISMO marco que mc.get_coords() / send_coords()
(origen en la base del robot). Son los valores del notebook del equipo; los de las
posiciones de recojo son ESTIMADOS y deben medirse en la mesa real (ver PASO_A_PASO_P2.md,
paso 6). Cada valor se puede sobrescribir con un parámetro ROS (config/broker_p2.yaml), así
que en el laboratorio no hace falta tocar este archivo.
"""

COLORES = ('azul', 'verde', 'rojo', 'amarillo')

# --- Cuadros de destino B / G / R / Y (fila superior del tapete) — valores del notebook ---
DESTINOS = {
    'azul':     [-60.0, 240.0],   # cuadro B
    'verde':    [0.0,   240.0],   # cuadro G
    'rojo':     [80.0,  240.0],   # cuadro R (confirmado en el notebook)
    'amarillo': [130.0, 240.0],   # cuadro Y
}

# --- Posiciones CONOCIDAS de los 4 objetos (esquinas del cuadrado central) ---
# Centro del cuadrado = POS_PICK del notebook [220, 5]. Las esquinas son ESTIMADAS (±45 mm).
# Ojo con el alcance: con la pinza vertical el JetCobot llega a ~279 mm de radio a z = 140.
# La cámara decide en cuál de estas posiciones está el color pedido (con la calibración).
POSICIONES_PICK = {
    'rojo':     [175.0,  50.0],
    'azul':     [265.0,  50.0],
    'verde':    [175.0, -40.0],
    'amarillo': [265.0, -40.0],
}

# --- Alturas de la brida (z de get_coords) ---
Z_AGARRE = 110.0      # notebook: POS_PICK z = 110
Z_SEGURO = 140.0      # notebook: ALTURA_INTERMEDIA_Z = 140 (aproximación y traslado)
Z_SOLTAR = 115.0      # notebook: destino z = 110 (+5 mm para no arrastrar el cubo)

# --- Pose de observación (cámara mirando el cuadrado central) ---
# Si tienen los ángulos del notebook, pónganlos en el parámetro pose_observacion_grados.
# Si no, el broker calcula la pose con la IK a partir de este punto.
POS_OBSERVACION = [210.0, 5.0, 240.0]

# --- Zonas de la P1 (zona_a/b/c) -> cuadro de color. '' = esa zona no existe en la mesa ---
ZONAS_A_CUADRO = {
    'zona_a': '',
    'zona_b': 'azul',     # el cuadro B del tapete
    'zona_c': '',
}


def resolver_destino(color, zona, zonas_a_cuadro, destino_si_falta='mismo_color'):
    """Devuelve (cuadro, motivo). cuadro = '' si no se puede resolver.

    * Si la orden nombra una zona, se usa el mapa zonas_a_cuadro.
    * Si no nombra zona: el objeto va al cuadro de SU MISMO COLOR (tapete B/G/R/Y),
      salvo que destino_si_falta = 'rechazar'.
    """
    if zona and zona != 'ninguna':
        cuadro = zonas_a_cuadro.get(zona, '')
        if not cuadro:
            return '', f'la {zona.replace("_", " ").upper()} no existe en esta mesa'
        if cuadro not in COLORES:
            return '', f'el mapa de zonas apunta a un cuadro desconocido: {cuadro}'
        return cuadro, ''
    if destino_si_falta == 'rechazar':
        return '', 'la orden no indica la zona de destino'
    if color in COLORES:
        return color, ''
    return '', 'no se puede elegir el cuadro: falta el color del objeto'
