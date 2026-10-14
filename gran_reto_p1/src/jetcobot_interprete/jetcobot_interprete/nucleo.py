"""Lógica de decisión (sin ROS): LAYA con plazo + respaldo por palabras clave."""
import csv
import os
import threading
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, Optional

from . import vocabulario as V
from .clasificador_palabras import clasificar
from .cliente_laya import ClienteLaya, ErrorLaya, RespuestaLaya
from .verificacion import aplicar_reglas

MODOS_DECISION = ("laya", "hibrido")

NO_DISPONIBLE = -1.0


@dataclass
class Decision:
    accion: str = "ninguna"
    objeto: str = "ninguno"
    color: str = "ninguno"
    zona: str = "ninguna"
    prioridad: int = 3
    permitido: bool = True
    causa: str = "ninguna"
    motivo_rechazo: str = ""
    degradado: bool = False
    fuente: str = "laya"
    detalle_error: str = ""
    latencia_total_ms: float = NO_DISPONIBLE
    latencia_rtt_ms: float = NO_DISPONIBLE
    latencia_servidor_ms: float = NO_DISPONIBLE
    latencia_red_ms: float = NO_DISPONIBLE
    # ---- solo bitácora/log (no van en el .srv) ----
    p_peligro: float = NO_DISPONIBLE         # P(peligrosa) que dio LAYA
    correcciones: str = ""                   # modo hibrido: qué corrigieron las reglas y por qué


def _motivo(permitido: bool, causa: str) -> str:
    if permitido:
        return ""
    return V.MOTIVOS.get(causa) or V.MOTIVOS["no_permitida"]


def _etiqueta(answers: Dict[str, Any], qid: str, validas) -> str:
    try:
        valor = answers[qid]["choice"]
    except (KeyError, TypeError):
        raise ErrorLaya("falta la respuesta '%s'" % qid)
    if valor not in validas:
        # Defensa: una etiqueta fuera del conjunto cerrado jamás llega al robot.
        raise ErrorLaya("etiqueta fuera del vocabulario en '%s': %r" % (qid, valor))
    return valor


def _numero(answers: Dict[str, Any], qid: str, clave: str) -> float:
    try:
        return float(answers[qid][clave])
    except (KeyError, TypeError, ValueError):
        raise ErrorLaya("falta o es inválido '%s.%s'" % (qid, clave))


def decision_desde_laya(resp: RespuestaLaya, umbral_peligro: float,
                        invertir_prioridad: bool) -> Decision:
    a = resp.answers
    d = Decision(fuente="laya")
    d.accion = _etiqueta(a, "accion", V.ACCIONES)
    d.objeto = _etiqueta(a, "objeto", V.OBJETOS)
    d.color = _etiqueta(a, "color", V.COLORES)
    d.zona = _etiqueta(a, "zona", V.ZONAS)
    causa = _etiqueta(a, "causa", V.CAUSAS)
    nivel = _numero(a, "prioridad", "score")            # 0.0 .. 4.0
    p_peligro = _numero(a, "peligro", "noul")           # P(true)
    d.prioridad = max(V.PRIORIDAD_MIN, min(V.PRIORIDAD_MAX, 1 + int(round(nivel))))
    if d.accion == "detener":
        d.prioridad = V.PRIORIDAD_MAX
    d.p_peligro = p_peligro
    d.permitido = p_peligro < umbral_peligro
    d.causa = causa if not d.permitido else "ninguna"
    if invertir_prioridad:
        d.prioridad = V.PRIORIDAD_MAX + V.PRIORIDAD_MIN - d.prioridad
    d.motivo_rechazo = _motivo(d.permitido, d.causa)
    d.latencia_rtt_ms = resp.rtt_ms
    if resp.servidor_ms is not None:
        d.latencia_servidor_ms = resp.servidor_ms
        d.latencia_red_ms = max(0.0, resp.rtt_ms - resp.servidor_ms)
    return d


def decision_desde_palabras(frase: str, invertir_prioridad: bool) -> Decision:
    c = clasificar(frase)
    d = Decision(accion=c["accion"], objeto=c["objeto"], color=c["color"], zona=c["zona"],
                 prioridad=c["prioridad"], permitido=c["permitido"], causa=c["causa"],
                 fuente="palabras_clave")
    if invertir_prioridad:
        d.prioridad = V.PRIORIDAD_MAX + V.PRIORIDAD_MIN - d.prioridad
    d.motivo_rechazo = _motivo(d.permitido, d.causa)
    return d


class Interprete:
    """Resuelve una frase. NUNCA espera más de `timeout_s` por LAYA."""

    def __init__(self, cliente: Optional[ClienteLaya], timeout_s: float = 1.0,
                 umbral_peligro: float = 0.5, invertir_prioridad: bool = False,
                 log_csv: str = "", modo_decision: str = "laya", umbral_veto_laya: float = 0.9):
        if modo_decision not in MODOS_DECISION:
            raise ValueError("modo_decision debe ser uno de %s" % (MODOS_DECISION,))
        self.modo_decision = modo_decision
        self.umbral_veto_laya = umbral_veto_laya
        self.cliente = cliente
        self.timeout_s = timeout_s
        self.umbral_peligro = umbral_peligro
        self.invertir_prioridad = invertir_prioridad
        self._log_csv = log_csv
        self._lock = threading.Lock()

    def interpretar(self, frase: str) -> Decision:
        t0 = time.perf_counter()
        frase = (frase or "").strip()
        if not frase:
            d = Decision(accion="ninguna", permitido=False, causa="frase_vacia",
                         fuente="validacion", motivo_rechazo=V.MOTIVOS["frase_vacia"])
        else:
            try:
                if self.cliente is None:
                    raise ErrorLaya("sin cliente LAYA configurado")
                resp = self.cliente.consultar(frase, self.timeout_s)
                if self.modo_decision == "hibrido":
                    d = self._hibrido(frase, resp)
                else:
                    d = decision_desde_laya(resp, self.umbral_peligro, self.invertir_prioridad)
            except ErrorLaya as e:
                d = decision_desde_palabras(frase, self.invertir_prioridad)
                d.degradado = True
                d.detalle_error = str(e)
        d.latencia_total_ms = (time.perf_counter() - t0) * 1000.0
        self._registrar(frase, d)
        return d

    def _hibrido(self, frase: str, resp: RespuestaLaya) -> Decision:
        """LAYA decide; la capa de verificación (verificacion.py) corrige lo explícito y veta lo peligroso."""
        d = decision_desde_laya(resp, self.umbral_peligro, invertir_prioridad=False)
        nivel = _numero(resp.answers, "prioridad", "score")
        prio_laya = max(V.PRIORIDAD_MIN, min(V.PRIORIDAD_MAX, 1 + int(round(nivel))))
        campos = {c: getattr(d, c) for c in ("accion", "objeto", "color", "zona", "prioridad",
                                              "permitido", "causa")}
        nuevo, corr = aplicar_reglas(campos, frase, p_peligro=d.p_peligro, prioridad_laya=prio_laya,
                                     umbral_veto_laya=self.umbral_veto_laya)
        for c, v in nuevo.items():
            setattr(d, c, v)
        if self.invertir_prioridad:
            d.prioridad = V.PRIORIDAD_MAX + V.PRIORIDAD_MIN - d.prioridad
        d.motivo_rechazo = _motivo(d.permitido, d.causa)
        if corr:
            d.fuente = "laya+reglas"
            d.correcciones = "; ".join(corr)
        return d

    # ---- bitácora CSV opcional: evidencia de cada consulta ----
    def _registrar(self, frase: str, d: Decision):
        if not self._log_csv:
            return
        fila = {"timestamp": datetime.now().isoformat(timespec="milliseconds"), "frase": frase}
        fila.update(asdict(d))
        if self.modo_decision == "laya":          # mismo formato de bitácora que en la P1
            fila.pop("p_peligro", None)
            fila.pop("correcciones", None)
        with self._lock:
            nuevo = not os.path.exists(self._log_csv)
            with open(self._log_csv, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(fila.keys()))
                if nuevo:
                    w.writeheader()
                w.writerow(fila)
