# Pregunta 3 — De la voz al movimiento: paso a paso

Se monta **encima** de P1 y P2 sin tocarlas: `jetcobot_voz` solo antepone una etapa.

```
operador ─voz─▶ transcriptor_voz ──(texto)──▶ ClienteIntegrado (P2) ─srv─▶ interprete_ordenes (P1) ─HTTP─▶ LAYA
   │               │  └─ nube: Google AI Studio (plazo propio)                 │
   │               └─ sin internet/plazo vencido → MODO TEXTO por teclado       └─ goal move_arm ─▶ arm_broker (P2)
   └─ evidencia_voz/audio/<id>.wav|.txt  +  registro_voz.csv                          cola → cámara → IK → MoveIt2 → gripper
```
Lo que ya trae su P2 y evita trabajo: el goal `move_arm` **ya lleva `t_origen_epoch`** (fin de la voz) y el
broker **ya registra** `inicio_movimiento_epoch`, `t_espera_s`, `t_percepcion_s`, `t_ik_s`, `t_planificacion_s`
en `intentos.csv`. Por eso la Parte C no necesita instrumentar ningún nodo: se calcula uniendo
`registro_voz.csv` + `intentos.csv`.

Reglas que se siguen cumpliendo: solo el worker del broker publica al brazo (el transcriptor no publica nada
al brazo) y solo `interprete_ordenes` habla con LAYA.

---
## 1. Instalar (una vez, antes del examen)

```bash
# 1.1 Copiar gran_reto_p3/ al Jetson (junto a gran_reto_p1 y gran_reto_p2)
# 1.2 Dependencias
sudo apt install -y alsa-utils python3-numpy python3-matplotlib python3-requests
# 1.3 Micrófono USB: anota "plughw:X,Y" y ponlo en config/transcriptor_voz.yaml -> dispositivo_arecord
arecord -l
# 1.4 Compilar (P1 y P2 ya compilados)
source ~/gran_reto_p2/entorno_p2.sh
cd ~/gran_reto_p3 && colcon build --symlink-install
```
Editen en `entorno_p3.sh` el `ROS_DOMAIN_ID` y `LAYA` (los mismos de `entorno_p2.sh`).

## 2. Clave de Google AI Studio (en CADA terminal que lance el transcriptor)
```bash
source ~/gran_reto_p3/entorno_p3.sh
read -s -p "GOOGLE_API_KEY: " GOOGLE_API_KEY; export GOOGLE_API_KEY; echo
```
Antes de subir a GitHub: `git grep -n "AIza"` debe salir vacío.

## 3. Pruebas escalonadas (ensayo; cada una se hace UNA vez y se pasa a la siguiente)

**3.1 Solo la nube** (graba 4 s y transcribe; valida clave, modelo y red):
```bash
arecord -D plughw:1,0 -f S16_LE -r 16000 -c 1 -d 4 prueba.wav
python3 -m jetcobot_voz.gemini_stt prueba.wav          # debe imprimir el texto y los ms
```
Si falla: `sin_clave` (variable), `http_400/403` (clave o `modelo` no disponible: cámbienlo en el YAML),
`sin_internet`, `timeout`.

**3.2 Micrófono** (calcula `umbral_rms`, ponerlo en el YAML):
```bash
ros2 run jetcobot_voz calibrar_microfono --dispositivo plughw:1,0
```

**3.3 Cadena completa SIN brazo ni laboratorio** (simulados; **no es evidencia**):
```bash
# T1  LAYA simulado (en el Jetson)
python3 -m jetcobot_interprete.laya_simulado          # (ver --help por el puerto)
# T2  intérprete P1 apuntando al simulado
ros2 launch jetcobot_interprete interprete.launch.py laya_url:=http://127.0.0.1:8000
# T3  broker P2 simulado (MoveIt/cámara no hacen falta)
ros2 launch arm_broker p2.launch.py simulado:=true
# T4  transcriptor, leyendo un archivo en vez del micrófono
ros2 run jetcobot_voz transcriptor_voz --ros-args \
   --params-file ~/gran_reto_p3/src/jetcobot_voz/config/transcriptor_voz.yaml -p archivo_audio:=$HOME/prueba.wav
#   → Enter: se transcribe, entra a la cola y se ve "✔ aceptada ... ✅ TERMINADO" en la terminal
```
Verifiquen: aparece `evidencia_voz/registro_voz.csv`, `evidencia_voz/audio/<id>.wav` y su `.txt`.

**3.4 Con audios YA grabados** (ensayo, o respaldo si el micrófono falla). `archivo_audio` acepta un archivo,
varios separados por coma, una carpeta o un patrón; cada Enter consume el **siguiente** y al acabar vuelve al micrófono.
También puedes escribir la ruta de un audio en el prompt `[Enter = hablar | ruta de audio | q]`.
```bash
ros2 run jetcobot_voz transcriptor_voz --ros-args --params-file ~/gran_reto_p3/src/jetcobot_voz/config/transcriptor_voz.yaml \
   -p archivo_audio:=$HOME/audios_orden/        # o  "a.wav,b.wav"  o  "$HOME/audios/*.wav"
```
Formatos: wav, mp3, ogg/opus, flac, aac/m4a, aiff; otros (webm, mp4) o archivos > 12 MB se convierten solos con `ffmpeg`
(`sudo apt install ffmpeg`). `registro_voz.csv` marca `fuente_audio=archivo`. **Ojo:** con archivo la etapa "captura" ≈ 0 y no
mide una captura real. En la demo, el docente dicta en vivo: usen micrófono; reporten cualquier orden por archivo como tal.

## 4. Predicciones (ANTES de medir) — `PREDICCIONES_P3.md`, con commit.

## 5. Demostración real (el docente dicta 5 órdenes)

Terminales, todas con `source ~/gran_reto_p3/entorno_p3.sh` (misma carpeta `~/demo_p3`):

| T | Comando | Nota |
|---|---|---|
| 1 | `move_group` de MoveIt 2 | exactamente como lo lanzaron en la P2 |
| 2 | `ros2 launch arm_broker p2.launch.py` | broker real. Antes: `sudo fuser -v /dev/ttyTHS1` vacío |
| 3 | `ros2 launch jetcobot_interprete interprete.launch.py laya_url:=$LAYA log_csv:=evidencia_voz/bitacora_interprete.csv` | único contacto con LAYA |
| 4 | `ros2 run arm_broker monitor_cola` | para el video |
| 5 | `ros2 bag record -o bag_p3 /arm/eventos /arm/queue_state /estado_voz /joint_states` | evidencia |
| 6 | `ros2 run jetcobot_voz transcriptor_voz --ros-args --params-file ~/gran_reto_p3/src/jetcobot_voz/config/transcriptor_voz.yaml` | micrófono (`archivo_audio` vacío) |

Por cada orden: **Enter → hablar el docente (o el operador) → esperar el resultado**. Mientras tanto
anoten en papel lo que se dijo. Después de cada orden:
```bash
ros2 run jetcobot_voz tabla_ordenes evidencia_voz/registro_voz.csv --marcar N \
   --dicho "lo que dijo el docente" --esperado "ejecutar rojo→cuadro rojo | rechazar: objeto ausente | rechazar: no permitida" --correcta si|no
```
(`N` = número de fila; una orden es correcta solo si el resultado final es el esperado, **incluido el rechazo**).

Qué esperar con su P2:
* **Objeto que no está en la mesa** (p. ej. "esfera", porque `objetos_en_mesa: cubo`): el broker lo **rechaza antes de encolar**, con causa.
  Si piden un color que no hay, el intento se **aborta después de desencolar** ("la cámara no encontró…") y el brazo vuelve a reposo. Ambos son resultados correctos si lo esperado es no ejecutar.
* **Orden no permitida**: LAYA devuelve `permitido=false` → rechazo antes de encolar. Si LAYA no la marca, ajusten `umbral_peligro` ahora con `ros2 run arm_broker probar_decisiones` (no durante la demo).
* `detener`: no se encola; para el movimiento en curso.
* Se puede dictar la siguiente orden mientras el brazo trabaja: el nodo no espera al brazo (verán la cola en `monitor_cola`).

Tabla final de la Parte B: `ros2 run jetcobot_voz tabla_ordenes evidencia_voz/registro_voz.csv` (últimas 5).

## 6. Parte C — dónde se va el tiempo

Medición limpia: **≥ 5 órdenes por voz con micrófono, una por vez**, esperando el "✅ TERMINADO" antes de
dictar la siguiente (así la cola está vacía y la etapa "cola" no contamina; si quieren ver la cola, hagan
aparte una tanda con pedidos simultáneos y repórtenla por separado). El transcriptor y el broker corren en
el mismo Jetson → mismo reloj (si el transcriptor corriera en otra máquina, sincronicen con `chrony`).
```bash
ros2 run jetcobot_voz desglose_voz --registro evidencia_voz/registro_voz.csv \
     --intentos evidencia_p2/intentos.csv --salida evidencia_voz
```
Entrega `desglose_voz.md` (tabla), `desglose_voz.png` (figura), `desglose_voz.csv` (por orden) y el análisis
(etapa dominante y si anularla alcanza para reducir a la mitad).

Cómo se define cada etapa (pónganlo en el informe):

| Etapa | Desde → hasta | Fuente |
|---|---|---|
| Captura | último bloque con voz → WAV listo (incluye `silencio_s`) | `t_captura_ms` |
| Transcripción | envío a Google → texto recibido | `t_transcripcion_ms` |
| Decisión | inicio de `enviar_frase` → goal enviado (servicio P1 + DDS) | `t_envio_epoch − t_ini_envio_epoch` |
| Cola | llegada al broker → empieza a ejecutar | `t_espera_s` |
| Preparación | volver a reposo si no estaba (el brazo puede moverse aquí) | `t_preparacion_s` |
| Percepción / IK / Planificación | cámara / `ik.py` / 7 tramos MoveIt2 | `t_percepcion_s`, `t_ik_s`, `t_planificacion_s` |
| Sin atribuir | envío del goal y huecos | total − suma |

*Total = `inicio_movimiento_epoch` − `t_origen_epoch`* (`inicio_movimiento_epoch` es el instante del primer
comando del agarre al brazo, tal como lo registra su broker). Si `preparación` > 0, el brazo ya se movió antes (para volver a reposo): dígalo.

**Para responder "¿qué etapa y a cambio de qué?"** usen SUS números; guía de palancas:

| Si domina… | Palanca | Lo que se pierde |
|---|---|---|
| Transcripción | modelo más ligero / audio más corto (menos bytes) / transcripción local | exactitud del texto (y por tanto de la decisión); local: memoria y precisión en el Jetson |
| Captura | menor `silencio_s` o pulsador de fin de frase | cortar frases con pausas |
| Decisión | menor `timeout_s` del intérprete (P1) | más órdenes degradadas (exactitud del respaldo por palabras clave) |
| Cola | política o `tau` | equidad / posibles inanición |
| Percepción / IK / Plan. | menos tramos, `modo_posicion: slot`, tiempo de MoveIt | seguridad / error de agarre |

## 7. Demostración sin internet (Parte A + entregable)

1. `bash ~/gran_reto_p3/herramientas/sin_internet.sh cortar` (o desconectar el cable de salida del router).
   `... estado` debe mostrar **"NO hay internet"** y **LAYA responde**. Grabar esto en video (`ping 8.8.8.8` fallando).
2. En el transcriptor: Enter → hablar. Verán `MODO TEXTO (motivo: sin_internet|timeout)`; escriban la orden.
   El texto sigue el mismo camino (P1 → cola → brazo) y el brazo la ejecuta.
3. Mostrar la fila en `registro_voz.csv` con `modo=texto` y `estado_stt=texto_teclado(...)`.
4. `bash .../sin_internet.sh restaurar`.
Para forzar el plazo propio sin desconectar: `-p timeout_transcripcion_s:=0.2`.

## 8. Entrega

Repositorio (sin claves) con: `src/jetcobot_voz/`, `evidencia_voz/` (audios + `.txt` + `registro_voz.csv` + tabla de 5 órdenes
+ `desglose_voz.*`), `evidencia_p2/intentos.csv` de la sesión, bag, video del modo texto sin internet, `PREDICCIONES_P3.md` e `informe_P3.md`.

## 9. Si algo falla

| Síntoma | Causa probable |
|---|---|
| `no se detectó voz` | `umbral_rms` alto / micrófono mal elegido (`arecord -l`) → `calibrar_microfono` |
| Graba ruido o corta frases | `umbral_rms` bajo/alto; `silencio_s` |
| `http_400/403/404` | clave inválida o `modelo` no disponible para su cuenta (ej. `gemini-1.5-*` ya no existe: usar `gemini-2.5-flash`) |
| Siempre modo texto | clave no exportada en ESA terminal; sin internet; `timeout_transcripcion_s` muy corto |
| `no se encuentra /interpretar_orden` | otro `ROS_DOMAIN_ID` o `interprete_ordenes` no corre |
| `move_arm no está activo` | broker no lanzado o dominio distinto |
| Fila sin `pedido_id` ni `resultado` final | el pedido sigue en curso o no llegó al broker |
| `desglose_voz`: "omitida: sin intento" | orden rechazada o aún ejecutándose; usen `intentos.csv` de la **misma** carpeta `~/demo_p3` |
