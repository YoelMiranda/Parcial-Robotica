"""Vocabulario CERRADO de la decisión tipada.

Todo lo que el servicio devuelve sale de estos conjuntos. Si cambia la mesa
(otros objetos, colores o zonas), este es el ÚNICO archivo que hay que editar
para el lado de LAYA; las palabras clave del respaldo están en
clasificador_palabras.py.
"""

# etiqueta -> descripción que ve el modelo (ayuda al zero-shot)
ACCIONES = {
    "recoger": "tomar un objeto con el gripper y, si se indica, llevarlo a una zona (mover, traer, agarrar, levantar, pasar)",
    "depositar": "soltar en una zona lo que el gripper ya sostiene, sin nombrar un objeto a recoger",
    "ir_home": "volver a la posición inicial, de reposo o home",
    "detener": "parar el movimiento del brazo, alto, detenerse, quedarse quieto",
    "ninguna": "la frase no es una orden de movimiento válida (saludo, pregunta, charla) o pide algo que el robot no hace",
}
OBJETOS = {
    "cubo": "un cubo, caja, bloque o dado",
    "esfera": "una esfera, bola, pelota o balón",
    "cilindro": "un cilindro, lata o tubo",
    "ninguno": "no se nombra ningún objeto",
}
COLORES = {
    "rojo": "el objeto es rojo",
    "azul": "el objeto es azul",
    "verde": "el objeto es verde",
    "amarillo": "el objeto es amarillo",
    "ninguno": "no se nombra color, o el color nombrado no es rojo, azul, verde ni amarillo",
}
ZONAS = {
    "zona_a": "la zona A (zona uno)",
    "zona_b": "la zona B (zona dos)",
    "zona_c": "la zona C (zona tres)",
    "ninguna": "no se indica ninguna zona de destino",
}
CAUSAS = {
    "ninguna": "la orden es segura y no hay causa de rechazo",
    "riesgo_personas": "acercar el brazo o un objeto a personas, a su cara, cabeza o manos",
    "dano_a_objetos_o_robot": "golpear, tirar, lanzar, romper, aplastar o forzar objetos o al propio robot",
    "desactiva_seguridad": "desactivar el paro de emergencia, límites o protecciones",
    "fuera_de_zona_de_trabajo": "mover el brazo fuera de la mesa o a velocidad máxima sin control",
}
# Niveles ordinales de urgencia (índice 0..4 -> prioridad 1..5)
NIVELES_PRIORIDAD = [
    "puede esperar: al final de todo, sin ninguna urgencia",
    "baja: cuando haya tiempo, sin prisa",
    "normal: orden común sin indicación de urgencia",
    "alta: se pide pronto o con prioridad",
    "máxima: urgente, inmediata, emergencia o pedir que se detenga",
]
PREGUNTA_PELIGRO = (
    "¿La orden es peligrosa o prohibida para un brazo robótico de escritorio "
    "(daña personas, objetos o al robot, o desactiva seguridades)?"
)

# Texto FIJO por causa (no lo genera ningún modelo)
MOTIVOS = {
    "ninguna": "",
    "riesgo_personas": "Rechazada: la orden pone en riesgo a personas.",
    "dano_a_objetos_o_robot": "Rechazada: la orden dañaría objetos o al robot.",
    "desactiva_seguridad": "Rechazada: la orden desactiva una protección de seguridad.",
    "fuera_de_zona_de_trabajo": "Rechazada: la orden sale de la zona de trabajo o exige velocidad no segura.",
    "frase_vacia": "Rechazada: la frase está vacía.",
    "no_permitida": "Rechazada: orden no permitida (causa no especificada).",
}
PRIORIDAD_MIN, PRIORIDAD_MAX = 1, 5
