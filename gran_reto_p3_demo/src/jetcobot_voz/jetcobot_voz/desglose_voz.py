#!/usr/bin/env python3
"""Parte C: ¿donde se va el tiempo entre que el operador termina de hablar y el brazo se mueve?

Une dos CSV que YA genera el sistema (no hace falta instrumentar nada mas):
  * registro_voz.csv   (transcriptor_voz): t_origen_epoch, t_captura_ms, t_transcripcion_ms, t_ini_envio_epoch
  * intentos.csv       (broker de la P2):  t_envio_epoch, t_llegada_epoch, t_espera_s, t_preparacion_s,
                                           t_percepcion_s, t_ik_s, t_planificacion_s, inicio_movimiento_epoch
unidos por pedido_id. Todos los epoch salen del reloj del Jetson (corre transcriptor y broker ahi).

  ros2 run jetcobot_voz desglose_voz --registro evidencia_voz/registro_voz.csv \
        --intentos evidencia_p2/intentos.csv --salida evidencia_voz

Total = inicio_movimiento_epoch - t_origen_epoch   (t_origen = ultimo bloque con voz)
Etapas: captura | transcripcion | decision | cola | preparacion | percepcion | IK | planificacion | sin_atribuir
Genera desglose_voz.csv, desglose_voz.md y desglose_voz.png
"""
import argparse
import csv
import os
import statistics
import sys

ETAPAS = ['captura', 'transcripcion', 'decision', 'cola', 'preparacion',
          'percepcion', 'cinematica_inversa', 'planificacion']
ETIQ = {'captura': 'Captura de audio', 'transcripcion': 'Transcripcion (nube)',
        'decision': 'Decision del modelo', 'cola': 'Espera en la cola',
        'preparacion': 'Preparacion (volver a reposo)', 'percepcion': 'Percepcion (camara)',
        'cinematica_inversa': 'Cinematica inversa', 'planificacion': 'Planificacion (MoveIt2)',
        'sin_atribuir': 'Sin atribuir (envio, huecos)'}


def _f(v, d=None):
    try:
        x = float(v)
        return x
    except (TypeError, ValueError):
        return d


def leer(ruta):
    with open(os.path.expanduser(ruta), newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def calcular(registro, intentos, avisar=print):
    """Devuelve una lista de dicts con cada etapa en SEGUNDOS (+ 'total' y 'sin_atribuir')."""
    por_pedido = {r['pedido_id']: r for r in intentos if r.get('pedido_id')}
    filas = []
    for r in registro:
        oid = r.get('orden_id', '?')
        if r.get('modo') != 'voz':
            avisar(f'[omitida] {oid}: no es una orden por voz (modo={r.get("modo") or "-"}).')
            continue
        it = por_pedido.get(r.get('pedido_id', ''))
        if it is None:
            avisar(f'[omitida] {oid}: sin intento en intentos.csv (rechazada o aun en curso).')
            continue
        v = {k: _f(it.get(k)) for k in ('t_envio_epoch', 't_espera_s', 't_preparacion_s', 't_percepcion_s',
                                       't_ik_s', 't_planificacion_s', 'inicio_movimiento_epoch')}
        t_origen, t_ini_envio = _f(r.get('t_origen_epoch')), _f(r.get('t_ini_envio_epoch'))
        cap, stt = _f(r.get('t_captura_ms')), _f(r.get('t_transcripcion_ms'))
        if None in v.values() or None in (t_origen, t_ini_envio, cap, stt) or not v['inicio_movimiento_epoch']:
            avisar(f'[omitida] {oid}: faltan tiempos (¿el agarre no llego a moverse?).')
            continue
        total = v['inicio_movimiento_epoch'] - t_origen
        fila = {'orden_id': oid, 'pedido_id': r['pedido_id'], 'frase': r.get('transcripcion', ''),
                'captura': cap / 1000, 'transcripcion': stt / 1000,
                'decision': v['t_envio_epoch'] - t_ini_envio, 'cola': v['t_espera_s'],
                'preparacion': v['t_preparacion_s'], 'percepcion': v['t_percepcion_s'],
                'cinematica_inversa': v['t_ik_s'], 'planificacion': v['t_planificacion_s'],
                'total': total}
        fila['sin_atribuir'] = total - sum(fila[e] for e in ETAPAS)
        if fila['sin_atribuir'] < -0.05:
            avisar(f'[aviso] {oid}: las etapas suman {-fila["sin_atribuir"]:.2f} s mas que el total; '
                   f'revisa que registro e intentos sean de la misma sesion/reloj.')
        filas.append(fila)
    return filas


def resumir(filas):
    cols = ETAPAS + ['sin_atribuir', 'total']
    return {c: statistics.median(f[c] for f in filas) for c in cols}


def analisis_texto(med):
    dom = max(ETAPAS, key=lambda c: med[c])
    meta = med['total'] / 2
    lineas = [f'Etapa dominante: {ETIQ[dom]} — {med[dom] * 1000:.0f} ms ({100 * med[dom] / med["total"]:.0f} % del total).',
              f'Reducir el total a la mitad exige ahorrar {meta * 1000:.0f} ms.',
              f'Aun llevando a cero la etapa dominante se ahorrarian {med[dom] * 1000:.0f} ms: '
              + ('ALCANZA sola.' if med[dom] >= meta else 'NO alcanza sola; hay que actuar sobre al menos dos etapas.')]
    orden = sorted(ETAPAS, key=lambda c: -med[c])
    lineas.append('Ahorro maximo teorico por etapa (mediana): '
                  + ', '.join(f'{c} {med[c] * 1000:.0f} ms' for c in orden[:4]) + '.')
    return lineas


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--registro', default='evidencia_voz/registro_voz.csv')
    ap.add_argument('--intentos', default='evidencia_p2/intentos.csv')
    ap.add_argument('--salida', default='evidencia_voz')
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    salida = os.path.expanduser(a.salida)
    os.makedirs(salida, exist_ok=True)

    filas = calcular(leer(a.registro), leer(a.intentos))
    if not filas:
        print('No hay ordenes completas por voz que desglosar.')
        return 1
    med = resumir(filas)
    cols = ETAPAS + ['sin_atribuir', 'total']

    with open(os.path.join(salida, 'desglose_voz.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['orden_id', 'pedido_id', 'frase'] + [c + '_ms' for c in cols])
        for fi in filas:
            w.writerow([fi['orden_id'], fi['pedido_id'], fi['frase']] + [f'{fi[c] * 1000:.0f}' for c in cols])
        w.writerow(['MEDIANA', '', ''] + [f'{med[c] * 1000:.0f}' for c in cols])

    md = [f'n = {len(filas)} ordenes por voz\n', '| Etapa | Mediana [ms] | % del total |', '|---|---:|---:|']
    for c in ETAPAS + ['sin_atribuir']:
        md.append(f'| {ETIQ[c]} | {med[c] * 1000:.0f} | {100 * med[c] / med["total"]:.1f} |')
    md.append(f'| **Total: fin de la voz -> inicio del movimiento** | **{med["total"] * 1000:.0f}** | 100 |')
    texto = '\n'.join(md) + '\n\n' + '\n'.join(analisis_texto(med)) + '\n'
    with open(os.path.join(salida, 'desglose_voz.md'), 'w', encoding='utf-8') as f:
        f.write(texto)
    print(texto)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    comp = ETAPAS + ['sin_atribuir']
    etiquetas = ['MEDIANA'] + [f['orden_id'][-3:] for f in filas]
    datos = np.array([[med[c] for c in comp]] + [[max(0.0, f[c]) for c in comp] for f in filas])
    fig, ax = plt.subplots(figsize=(10, 0.55 * len(etiquetas) + 2.8))
    izq = np.zeros(len(etiquetas))
    cmap = plt.get_cmap('tab10')
    for j, c in enumerate(comp):
        sa = c == 'sin_atribuir'
        ax.barh(etiquetas, datos[:, j], left=izq, label=ETIQ[c], color='#bbbbbb' if sa else cmap(j),
                hatch='//' if sa else None, edgecolor='white')
        izq += datos[:, j]
    ax.invert_yaxis()
    ax.set_xlabel('Tiempo desde que el operador termina de hablar [s]')
    ax.set_title('Voz -> inicio del movimiento del brazo')
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.18), ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(salida, 'desglose_voz.png'), dpi=200)
    print(f'Guardado en {salida}: desglose_voz.csv / .md / .png')
    return 0


if __name__ == '__main__':
    sys.exit(main())
