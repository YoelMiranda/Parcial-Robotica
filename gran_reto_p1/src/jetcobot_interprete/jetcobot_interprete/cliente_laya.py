"""Cliente HTTP mínimo (solo biblioteca estándar) del servidor LAYA.

* POST /v1/systemone con 7 preguntas tipadas en UNA sola petición (una pasada).
* Plazo DURO: la llamada se ejecuta en un hilo y el llamador espera como
  máximo `timeout_s`, incluso si el DNS o el socket se cuelgan.
* Mide el ida y vuelta (rtt) y lee el tiempo de cálculo que informa el servidor
  (cabecera X-Inference-Time-Ms o Server-Timing: inference;dur=<ms>).
"""
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import vocabulario as V


class ErrorLaya(Exception):
    """Cualquier fallo al consultar LAYA (timeout, red, HTTP, formato)."""


@dataclass
class RespuestaLaya:
    answers: Dict[str, Dict[str, Any]]
    rtt_ms: float
    servidor_ms: Optional[float]
    modelo: str


def construir_preguntas() -> Dict[str, Dict[str, Any]]:
    """Las 7 preguntas tipadas. Nunca se pide generar texto."""
    return {
        "accion": {"type": "choice", "instructions": "¿Qué acción pide el operador al brazo?",
                   "criteria": dict(V.ACCIONES)},
        "objeto": {"type": "choice", "instructions": "¿Qué tipo de objeto nombra la frase?",
                   "criteria": dict(V.OBJETOS)},
        "color": {"type": "choice", "instructions": "¿De qué color es el objeto nombrado?",
                  "criteria": dict(V.COLORES)},
        "zona": {"type": "choice", "instructions": "¿A qué zona de destino se refiere la frase?",
                 "criteria": dict(V.ZONAS)},
        "causa": {"type": "choice", "instructions": "Si la orden fuera peligrosa, ¿cuál sería la causa?",
                  "criteria": dict(V.CAUSAS)},
        "prioridad": {"type": "score", "instructions": "¿Qué tan urgente es la orden?",
                      "criteria": list(V.NIVELES_PRIORIDAD)},
        "peligro": {"type": "noul", "instructions": V.PREGUNTA_PELIGRO},
    }


def _parse_servidor_ms(headers) -> Optional[float]:
    v = headers.get("X-Inference-Time-Ms")
    if v is not None:
        try:
            return float(v)
        except ValueError:
            pass
    st = headers.get("Server-Timing")
    if st:
        m = re.search(r"inference;\s*dur=([0-9.]+)", st)
        if m:
            return float(m.group(1))
    return None


class ClienteLaya:
    def __init__(self, url: str, endpoint: str = "/v1/systemone", api_key: str = "",
                 modelo: str = "", lang: str = "es", extra: Optional[Dict[str, Any]] = None,
                 max_hilos: int = 32):
        self.url = url.rstrip("/")
        self.endpoint = endpoint if endpoint.startswith("/") else "/" + endpoint
        self.api_key = api_key
        self.modelo = modelo
        self.lang = lang
        self.extra = dict(extra or {})
        self._preguntas = construir_preguntas()
        self._pool = ThreadPoolExecutor(max_workers=max_hilos, thread_name_prefix="laya")

    # ---------------------------------------------------------------- HTTP
    def _post(self, frase: str, timeout_s: float) -> RespuestaLaya:
        cuerpo: Dict[str, Any] = {"state": frase, "questions": self._preguntas}
        if self.modelo:
            cuerpo["model"] = self.modelo
        if self.lang:
            cuerpo["lang"] = self.lang
        cuerpo.update(self.extra)
        datos = json.dumps(cuerpo).encode("utf-8")
        cab = {"Content-Type": "application/json"}
        if self.api_key:
            cab["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(self.url + self.endpoint, data=datos, headers=cab, method="POST")
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                crudo = r.read()
                servidor_ms = _parse_servidor_ms(r.headers)
        except urllib.error.HTTPError as e:
            raise ErrorLaya("HTTP %d: %s" % (e.code, e.reason))
        except (urllib.error.URLError, OSError) as e:
            raise ErrorLaya("red: %s" % (getattr(e, "reason", e),))
        rtt_ms = (time.perf_counter() - t0) * 1000.0
        try:
            js = json.loads(crudo)
            answers = js.get("answers", js)
            return RespuestaLaya(answers=answers, rtt_ms=rtt_ms,
                                 servidor_ms=servidor_ms, modelo=str(js.get("model", "")))
        except (ValueError, AttributeError) as e:
            raise ErrorLaya("respuesta no es JSON válido: %s" % e)

    def consultar(self, frase: str, timeout_s: float) -> RespuestaLaya:
        """Consulta con plazo duro `timeout_s` (segundos). Lanza ErrorLaya."""
        fut = self._pool.submit(self._post, frase, timeout_s)
        try:
            return fut.result(timeout=timeout_s)
        except FutureTimeout:
            fut.cancel()
            raise ErrorLaya("timeout: LAYA no respondió en %.3f s" % timeout_s)
        except ErrorLaya:
            raise
        except Exception as e:  # cualquier otra cosa también degrada
            raise ErrorLaya("error inesperado: %r" % (e,))

    def ping_ms(self, timeout_s: float = 2.0) -> float:
        """RTT de GET /health: línea base de red sin cálculo del modelo."""
        t0 = time.perf_counter()
        with urllib.request.urlopen(self.url + "/health", timeout=timeout_s) as r:
            r.read()
        return (time.perf_counter() - t0) * 1000.0

    def cerrar(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
