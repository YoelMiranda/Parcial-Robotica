"""Estadística mínima sin dependencias (mediana, percentil 95)."""
import math
from typing import Dict, Iterable, List


def percentil(valores: Iterable[float], p: float) -> float:
    """Percentil p (0-100) con interpolación lineal (igual que numpy.percentile)."""
    v: List[float] = sorted(valores)
    if not v:
        return float("nan")
    if len(v) == 1:
        return v[0]
    k = (len(v) - 1) * (p / 100.0)
    f, c = math.floor(k), math.ceil(k)
    return v[int(k)] if f == c else v[f] + (v[c] - v[f]) * (k - f)


def resumen(valores: Iterable[float]) -> Dict[str, float]:
    v = [x for x in valores if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not v:
        return {"n": 0, "mediana": float("nan"), "p95": float("nan"),
                "media": float("nan"), "min": float("nan"), "max": float("nan")}
    return {"n": len(v), "mediana": percentil(v, 50), "p95": percentil(v, 95),
            "media": sum(v) / len(v), "min": min(v), "max": max(v)}
