"""Capa de verificación de la decisión de LAYA con las reglas del clasificador propio.

Solo actúa en modo_decision = "hibrido" (el modo por defecto, "laya", no la usa).

Motivo: en las mediciones del equipo, LAYA acertó la acción en 20/50 frases y "permitido" en
27/50, y ACEPTÓ 3 órdenes prohibidas. El clasificador por palabras clave acertó 45/50 y 50/50.
Esta capa combina ambos con dos principios:

1. Seguridad conservadora: si las reglas detectan una orden peligrosa, se RECHAZA aunque LAYA
   la permita. LAYA solo puede rechazar una orden que las reglas ven normal y clara si está muy
   segura (P(peligrosa) >= umbral_veto_laya).
2. Lo explícito manda: si la frase nombra literalmente un verbo, UN color, UN objeto, una zona
   o una marca de urgencia de la lista, ese valor corrige al de LAYA. Si la frase es ambigua
   (dos colores, ningún verbo conocido), se respeta a LAYA.

Cada corrección queda escrita ("accion: detener->recoger") en `correcciones` para el informe.
"""
from typing import Dict, List, Optional, Tuple

from . import vocabulario as V
from .clasificador_palabras import (COLOR_REGLAS, OBJETO_REGLAS, PRIORIDAD_DEFECTO, _tiene,
                                    clasificar, normalizar)

ORDENES_CLARAS = ("recoger", "depositar", "ir_home", "detener")


def _coincidencias(texto: str, reglas) -> List[str]:
    return [etq for etq, pats in reglas if _tiene(texto, pats)]


def aplicar_reglas(d: Dict[str, object], frase: str, p_peligro: Optional[float] = None,
                   prioridad_laya: Optional[int] = None,
                   umbral_veto_laya: float = 0.9) -> Tuple[Dict[str, object], List[str]]:
    """Corrige la decisión `d` (claves: accion, objeto, color, zona, prioridad, permitido, causa).

    p_peligro:      P(peligrosa) que dio LAYA (None = desconocida: no se puede sostener su veto).
    prioridad_laya: prioridad que sale del PUNTAJE de LAYA, antes de forzar 5 por 'detener'.
    Devuelve (decisión corregida, lista de correcciones).
    """
    d = dict(d)
    corr: List[str] = []
    k = clasificar(frase)
    t = normalizar(frase or "")

    def poner(campo, valor, porque=""):
        if d[campo] != valor:
            corr.append("%s: %s->%s%s" % (campo, d[campo], valor, (" (" + porque + ")") if porque else ""))
            d[campo] = valor

    # ---- 1. seguridad ----
    if not k["permitido"]:
        poner("permitido", False, "reglas: " + k["causa"])
        if d.get("causa", "ninguna") in ("ninguna", ""):
            d["causa"] = k["causa"]
    elif not d["permitido"] and k["accion"] in ORDENES_CLARAS:
        if p_peligro is None or p_peligro < umbral_veto_laya:
            detalle = "orden clara sin palabras de peligro"
            if p_peligro is not None:
                detalle += ", P(peligro)=%.2f < %.2f" % (p_peligro, umbral_veto_laya)
            poner("permitido", True, detalle)
            d["causa"] = "ninguna"

    # ---- 2. acción ----
    if k["accion"] != "ninguna":
        poner("accion", k["accion"], "verbo explícito")
    if not d["permitido"] and d["accion"] not in ("recoger", "depositar"):
        d["accion"] = "ninguna"

    # ---- 3. objeto y color: solo si la frase nombra exactamente uno ----
    for campo, reglas, vacio in (("objeto", OBJETO_REGLAS, "ninguno"), ("color", COLOR_REGLAS, "ninguno")):
        nombrados = _coincidencias(t, reglas)
        if len(nombrados) == 1:
            poner(campo, nombrados[0], "nombrado en la frase")
        elif not nombrados:
            poner(campo, vacio, "la frase no nombra ninguno conocido")

    # ---- 4. zona ----
    if k["zona"] != "ninguna":
        poner("zona", k["zona"], "nombrada en la frase")

    # ---- 5. prioridad: la del puntaje de LAYA, salvo marca explícita de urgencia ----
    if d["accion"] == "detener":
        nueva = V.PRIORIDAD_MAX
    elif k["prioridad"] != PRIORIDAD_DEFECTO:
        nueva = k["prioridad"]
    elif prioridad_laya is not None:
        nueva = prioridad_laya
    else:
        nueva = d["prioridad"]
    if int(nueva) != int(d["prioridad"]):
        poner("prioridad", int(nueva), "marca de urgencia" if k["prioridad"] != PRIORIDAD_DEFECTO
              else "puntaje de LAYA sin el 5 forzado")
    if d["permitido"]:
        d["causa"] = "ninguna"
    return d, corr
