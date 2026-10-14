# Gran Reto JetCobot — Pregunta 1: servicio de interpretación de órdenes

Nodo ROS 2 **`interprete_ordenes`** que expone el servicio **`/interpretar_orden`**: recibe una frase en español y
devuelve una **decisión tipada** (acción, objeto, color, zona, prioridad, permitido, causa…). Consulta al servidor LAYA
por HTTP; si no responde dentro de `timeout_s`, decide con un clasificador propio por palabras clave y marca
`degradado = true`.

```
src/
  jetcobot_interfaces/     srv/InterpretarOrden.srv   (ament_cmake)
  jetcobot_interprete/     (ament_python)
    jetcobot_interprete/
      interprete_ordenes.py     nodo ROS 2 (único contacto con LAYA)
      nucleo.py                 lógica: LAYA con plazo + respaldo, validación, bitácora
      cliente_laya.py           cliente HTTP (plazo duro, rtt, tiempo del servidor)
      clasificador_palabras.py  respaldo por palabras clave
      vocabulario.py            conjuntos cerrados de etiquetas  <-- editar si cambia la mesa
      medir_latencia.py         mide /interpretar_orden (calma / carga) y compara
      evaluar_exactitud.py      exactitud LAYA vs palabras clave + fallos por tipo
      laya_simulado.py          SIMULADOR de LAYA, solo para desarrollo (no es evidencia)
    datos/frases_ejemplo.csv    50 frases de EJEMPLO (reemplazar por las del docente)
    config/, launch/, test/
informe_P1.md              plantilla del informe (justificación ya redactada, tablas por llenar)
```

## Compilar (Jetson, ROS 2 Humble)

```bash
cd gran_reto_p1
colcon build --symlink-install
source install/setup.bash
export ROS_DOMAIN_ID=<el de su equipo>
```

## Ejecutar

```bash
# Solo si el servidor exige clave (la entrega el docente). NUNCA en el código ni en el repo:
export LAYA_API_KEY=...

ros2 run jetcobot_interprete interprete_ordenes --ros-args \
  -p laya_url:=http://<IP>:<PUERTO> -p timeout_s:=1.0 -p log_csv:=salida/bitacora_servicio.csv
# o:  ros2 launch jetcobot_interprete interprete.launch.py laya_url:=http://<IP>:<PUERTO>

ros2 service call /interpretar_orden jetcobot_interfaces/srv/InterpretarOrden "{frase: 'recoge el cubo rojo y ponlo en la zona A'}"
```

| Parámetro | Defecto | Significado |
|---|---|---|
| `laya_url` | `http://127.0.0.1:8000` | IP:puerto que entrega el docente |
| `timeout_s` | `1.0` | **Tiempo límite** de LAYA. Al vencer → respaldo y `degradado=true`. Editable en caliente: `ros2 param set /interprete_ordenes timeout_s 0.5` |
| `modelo` | `""` | Campo `model` de la petición (el *preset*/checkpoint que indique el docente). Vacío = el servidor elige |
| `extra_json` | `""` | Campos extra del cuerpo, p. ej. `'{"task":"..."}'`, si el docente pide otros |
| `umbral_peligro` | `0.5` | P(orden peligrosa) ≥ umbral ⇒ `permitido=false` |
| `invertir_prioridad` | `false` | `true` si en el broker del RB-2 la prioridad 1 es la más urgente |
| `log_csv` | `""` | Bitácora de cada consulta (evidencia) |

## Medir (flujo del examen)

1. **Escriban primero lo que esperan medir** (mediana y P95): el script lo exige.
2. En calma:
   ```bash
   ros2 run jetcobot_interprete medir_latencia --frases frases_docente.csv --escenario calma \
     --prediccion-mediana-ms 60 --prediccion-p95-ms 120 --laya-url http://<IP>:<PUERTO> --salida salida
   ```
3. Bajo carga, **todos los equipos a la vez** (acuerden la hora): añadan `--escenario carga --inicio HH:MM:SS`.
   (`--hilos N` agrega carga sintética propia si hace falta.)
4. `ros2 run jetcobot_interprete medir_latencia --comparar salida/resumen_calma.json salida/resumen_carga.json`
5. `ros2 run jetcobot_interprete evaluar_exactitud salida/decisiones_calma.csv`

Genera `decisiones_<escenario>.csv` (50 frases × decisión de LAYA y de palabras clave × latencias),
`resumen_*.json`, `tabla_latencia_*.md`, `tabla_exactitud.md`, `fallos_laya.csv`, `fallos_kw.csv`.
El CSV de frases necesita la columna `frase` y, para la exactitud, las columnas de verdad
(`accion,objeto,color,zona,prioridad,permitido`). Si el docente usa otro formato, renombren columnas o ajusten `CAMPOS`.

Para probar sin el servidor del laboratorio: `python3 -m jetcobot_interprete.laya_simulado` (**no usar como evidencia**).
Pruebas sin ROS: `cd src/jetcobot_interprete && python3 -m unittest discover -s test -v`.

## Cumplimiento de los requisitos

| Requisito | Dónde |
|---|---|
| Nodo `interprete_ordenes`, servicio `/interpretar_orden`, campos acción/objeto/color/prioridad(int)/permitido | `interprete_ordenes.py`, `InterpretarOrden.srv` |
| 1. Salida tipada, sin texto generado; justificación | 7 preguntas `choice/score/noul` en una sola pasada (`cliente_laya.construir_preguntas`); etiquetas validadas contra `vocabulario.py`; justificación en `informe_P1.md §2` |
| 2. Límite como parámetro + respaldo + `degradado` | `timeout_s`; plazo duro en `ClienteLaya.consultar`; `nucleo.Interprete` |
| 3. Mediana y P95; red vs cálculo | `medir_latencia.py`: `rtt_ms`, `servidor_ms` (cabecera `X-Inference-Time-Ms`), `red_ms`, línea base `GET /health` |
| 4. Calma vs carga | `--escenario`, `--inicio`, `--comparar` |
| 5. Exactitud LAYA vs palabras clave | `evaluar_exactitud.py` |
| Clave fuera del repo | solo `os.environ`; `.gitignore` |

## Supuestos a confirmar con el docente

* **Preset:** el protocolo HTTP de LAYA no tiene un campo `preset`; lo mapeé a `modelo` (campo `model`).
  Si el docente lo usa distinto, `extra_json`.
* **Vocabulario:** objetos (cubo/esfera/cilindro), colores (rojo/azul/verde/amarillo) y zonas (A/B/C) son
  supuestos razonables; deben coincidir con la mesa real (`vocabulario.py` + `clasificador_palabras.py`).
* **Formato de respuesta de LAYA:** `answers[id].choice | .score | .noul` y cabecera `X-Inference-Time-Ms`,
  según la documentación oficial; el servidor del laboratorio podría diferir.
