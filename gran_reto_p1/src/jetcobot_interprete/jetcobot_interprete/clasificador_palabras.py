"""Clasificador PROPIO por palabras clave (respaldo cuando LAYA no responde).

Sin red, sin dependencias, determinista y de microsegundos. Es deliberadamente
simple: reglas sobre texto normalizado (minúsculas, sin tildes). No entiende
negaciones, sinónimos fuera de la lista ni frases telegráficas: esas son sus
fallas esperadas y se analizan en el informe.
"""
import re
import unicodedata
from typing import Dict, List, Tuple

# ---------------------------------------------------------------- utilidades
def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9ñ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tiene(texto: str, patrones: List[str]) -> bool:
    """True si algún patrón aparece como palabra/frase completa."""
    return any(re.search(r"\b" + p + r"\b", texto) for p in patrones)


# ------------------------------------------------------------------ reglas
# Se evalúan en este orden: detener > ir_home > recoger > depositar.
ACCION_REGLAS: List[Tuple[str, List[str]]] = [
    ("detener", [r"detente", r"detener", r"detenga", r"para", r"parar", r"alto",
                 r"stop", r"frena", r"frenar", r"no te muevas", r"emergencia"]),
    ("ir_home", [r"home", r"posicion inicial", r"posicion de reposo", r"reposo",
                 r"origen", r"vuelve a casa", r"posicion de descanso", r"descanso"]),
    ("recoger", [r"recoge", r"recoger", r"agarra", r"agarrar", r"toma", r"tomar",
                 r"coge", r"coger", r"levanta", r"levantar", r"trae", r"traer",
                 r"lleva", r"llevar", r"llevalo", r"mueve", r"mover", r"traslada",
                 r"transporta", r"pasa", r"pasame", r"dame", r"alza"]),
    ("depositar", [r"suelta", r"soltar", r"deposita", r"depositar", r"deja",
                   r"dejar", r"coloca", r"colocar", r"pon", r"poner", r"ubica"]),
]
OBJETO_REGLAS = [
    ("cubo", [r"cubo", r"cubos", r"caja", r"bloque", r"dado"]),
    ("esfera", [r"esfera", r"bola", r"pelota", r"balon"]),
    ("cilindro", [r"cilindro", r"lata", r"tubo"]),
]
COLOR_REGLAS = [
    ("rojo", [r"rojo", r"roja"]),
    ("azul", [r"azul"]),
    ("verde", [r"verde"]),
    ("amarillo", [r"amarillo", r"amarilla"]),
]
ZONA_REGLAS = [
    ("zona_a", [r"zona a", r"zona 1", r"zona uno"]),
    ("zona_b", [r"zona b", r"zona 2", r"zona dos"]),
    ("zona_c", [r"zona c", r"zona 3", r"zona tres"]),
]
# Orden prohibida -> causa (se toma la primera que coincida)
PROHIBIDAS: List[Tuple[str, List[str]]] = [
    ("desactiva_seguridad", [r"desactiva", r"desactivar", r"apaga el paro", r"ignora", r"quita el limite"]),
    ("riesgo_personas", [r"cara", r"cabeza", r"persona", r"gente", r"companero", r"companera",
                         r"alguien", r"humano", r"dedos", r"ojos"]),
    ("fuera_de_zona_de_trabajo", [r"maxima velocidad", r"a toda velocidad", r"fuera de la mesa",
                                  r"pared", r"sin parar"]),
    ("dano_a_objetos_o_robot", [r"golpea", r"golpear", r"tira", r"tirar", r"lanza", r"lanzar",
                                r"arroja", r"rompe", r"romper", r"destruye", r"aplasta",
                                r"aprieta", r"choca", r"chocar", r"estrella", r"al suelo", r"con fuerza"]),
]
# Prioridad: se toma la primera regla que coincide; por defecto 3.
PRIORIDAD_REGLAS: List[Tuple[int, List[str]]] = [
    (5, [r"urgente", r"urgentemente", r"ya", r"ahora mismo", r"inmediatamente",
         r"de inmediato", r"rapido", r"emergencia", r"cuanto antes", r"lo antes posible"]),
    (4, [r"pronto", r"con prioridad", r"prioritario", r"prioritaria"]),
    (1, [r"al final", r"cuando termines", r"lo ultimo", r"cuando no haya nada mas"]),
    (2, [r"cuando puedas", r"sin prisa", r"no hay prisa", r"con calma", r"tranquilamente",
         r"luego", r"mas tarde"]),
]
PRIORIDAD_DEFECTO = 3


def _primero(texto: str, reglas, defecto: str) -> str:
    for etiqueta, pats in reglas:
        if _tiene(texto, pats):
            return etiqueta
    return defecto


def clasificar(frase: str) -> Dict[str, object]:
    """Devuelve la decisión tipada como dict (mismas claves que el servicio)."""
    t = normalizar(frase or "")
    accion = _primero(t, ACCION_REGLAS, "ninguna")
    objeto = _primero(t, OBJETO_REGLAS, "ninguno")
    color = _primero(t, COLOR_REGLAS, "ninguno")
    zona = _primero(t, ZONA_REGLAS, "ninguna")

    # "Pon la esfera verde en la zona B": nombra objeto => es recoger+llevar
    if accion == "depositar" and (objeto != "ninguno" or color != "ninguno"):
        accion = "recoger"

    causa = _primero(t, PROHIBIDAS, "ninguna")
    permitido = causa == "ninguna"
    if not permitido:
        # una orden prohibida no es una acción que el robot ejecute
        # (se conserva si hay verbo reconocido; el broker la rechaza igualmente)
        if accion not in ("recoger", "depositar"):
            accion = "ninguna"

    prioridad = PRIORIDAD_DEFECTO
    for valor, pats in PRIORIDAD_REGLAS:
        if _tiene(t, pats):
            prioridad = valor
            break
    if accion == "detener":
        prioridad = 5

    return {"accion": accion, "objeto": objeto, "color": color, "zona": zona,
            "prioridad": prioridad, "permitido": permitido, "causa": causa}
