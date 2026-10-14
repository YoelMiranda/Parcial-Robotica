"""Tabla de los 10 intentos de la Pregunta 2 (tasa de éxito y error FK).

  ros2 run arm_broker tabla_intentos evidencia_p2/intentos.csv              # tabla markdown
  ros2 run arm_broker tabla_intentos evidencia_p2/intentos.csv --marcar 3 si  # anotar resultado
  ros2 run arm_broker tabla_intentos evidencia_p2/intentos.csv --prediccion-exito 80 --prediccion-error 10

Un intento es EXITOSO si el objeto correcto quedó en la zona correcta: eso lo decide el
equipo mirando la mesa o el video (columna exito_manual = si/no). El error se calcula con
la FK del RB-2 sobre los ángulos leídos en el punto de entrega, antes de soltar.
Se ignoran las filas simuladas y los pedidos 'home'.
"""

import argparse
import csv
import statistics
import sys


def leer(ruta):
    with open(ruta, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def escribir(ruta, filas):
    with open(ruta, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)


def _f(v, d=-1.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--marcar', nargs=2, metavar=('INTENTO', 'si|no'))
    ap.add_argument('--incluir-simulados', action='store_true')
    ap.add_argument('--ultimos', type=int, default=10, help='cuántos intentos reales tomar (0 = todos)')
    ap.add_argument('--prediccion-exito', type=float, help='tasa de éxito predicha [%%]')
    ap.add_argument('--prediccion-error', type=float, help='error FK medio predicho [mm]')
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    filas = leer(a.csv)
    if a.marcar:
        n, v = a.marcar
        v = v.lower()
        if v not in ('si', 'no'):
            print('usa si o no')
            return 1
        for fila in filas:
            if fila['intento'] == n:
                fila['exito_manual'] = v
                escribir(a.csv, filas)
                print(f'intento {n} marcado como {v}')
                return 0
        print(f'no existe el intento {n}')
        return 1

    sel = [f for f in filas if f.get('modo', 'agarre') == 'agarre'
           and (a.incluir_simulados or f.get('simulado', 'False') not in ('True', 'true', '1'))]
    if a.ultimos:
        sel = sel[-a.ultimos:]
    if not sel:
        print('No hay intentos reales en el CSV (las filas del ensayo simulado se ignoran).')
        return 0

    print('| # | Cliente | Orden | Prioridad | Destino | Plan | Resultado broker | Éxito (manual) '
          '| Error FK [mm] | Error get_coords [mm] | Causa |')
    print('|---|---|---|---:|---|---|---|---|---:|---:|---|')
    exitos, errores, errores_gc, pendientes = 0, [], [], 0
    for f in sel:
        ex = (f.get('exito_manual') or '').strip().lower()
        if ex == 'si':
            exitos += 1
            if _f(f['error_fk_mm']) >= 0:
                errores.append(_f(f['error_fk_mm']))
            if _f(f.get('error_get_coords_mm')) >= 0:
                errores_gc.append(_f(f['error_get_coords_mm']))
        elif ex != 'no':
            pendientes += 1
        e = _f(f['error_fk_mm'])
        eg = _f(f.get('error_get_coords_mm'))
        print(f'| {f["intento"]} | {f["client_id"]} | {f["frase"]} | {f["prioridad"]} | {f["destino"]} | '
              f'{f["planificador"]} | {f["resultado"]} | {ex or "PENDIENTE"} | '
              f'{e:.1f} | {eg:.1f} | {f.get("causa", "")} |'.replace('-1.0', '—'))
    n = len(sel)
    print()
    print(f'**Intentos:** {n} · **Éxitos:** {exitos} · **Tasa de éxito:** {100.0 * exitos / n:.0f} %'
          + (f' · ⚠ {pendientes} sin marcar (exito_manual)' if pendientes else ''))
    if errores:
        print(f'**Error FK en intentos exitosos:** media {statistics.mean(errores):.1f} mm · '
              f'mediana {statistics.median(errores):.1f} mm · máx {max(errores):.1f} mm · '
              f'desv. est. {statistics.pstdev(errores):.1f} mm (n = {len(errores)})')
    if errores_gc:
        print(f'**Referencia get_coords:** media {statistics.mean(errores_gc):.1f} mm')
    if a.prediccion_exito is not None or a.prediccion_error is not None:
        print()
        print('| Magnitud | Predicho | Medido | Diferencia |')
        print('|---|---:|---:|---:|')
        if a.prediccion_exito is not None:
            m = 100.0 * exitos / n
            print(f'| Tasa de éxito [%] | {a.prediccion_exito:.0f} | {m:.0f} | {m - a.prediccion_exito:+.0f} |')
        if a.prediccion_error is not None and errores:
            m = statistics.mean(errores)
            print(f'| Error FK medio [mm] | {a.prediccion_error:.1f} | {m:.1f} | {m - a.prediccion_error:+.1f} |')
    t = [f for f in sel if f['resultado'] == 'succeeded']
    if t:
        print()
        print('**Tiempos medios por etapa (s)** — sirven para la Pregunta 3:')
        for k in ('t_espera_s', 't_preparacion_s', 't_percepcion_s', 't_ik_s', 't_planificacion_s',
                  't_movimiento_s'):
            vals = [_f(f.get(k), 0.0) for f in t]
            print(f'- {k}: {statistics.mean(vals):.2f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
