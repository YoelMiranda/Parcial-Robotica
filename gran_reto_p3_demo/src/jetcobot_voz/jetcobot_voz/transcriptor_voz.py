#!/usr/bin/env python3
"""Nodo transcriptor_voz  (Pregunta 3 - Parte A, y datos para Partes B y C)

Cadena completa, SIN construir nada nuevo aguas abajo:

  voz -> [Google AI Studio, con plazo propio] -> texto
      -> ClienteIntegrado (P2) -> /interpretar_orden (P1) -> goal move_arm -> broker (P2)

Si la transcripcion no llega a tiempo o no hay internet, pasa a MODO TEXTO por teclado y lo
informa: el brazo nunca queda esperando. Este nodo NUNCA publica al brazo (solo el worker del
broker lo hace) y NUNCA habla con LAYA (solo interprete_ordenes).

Uso (en el Jetson, terminal con entorno_p3.sh):
    ros2 run jetcobot_voz transcriptor_voz --ros-args --params-file <config>/transcriptor_voz.yaml
    -> pulsa Enter y habla.   (o, con interactivo:=false:  ros2 service call /escuchar std_srvs/srv/Trigger)

Evidencia (carpeta directorio_registro, por defecto ./evidencia_voz):
    audio/<id>.wav|.txt     audio original + su transcripcion
    registro_voz.csv        una fila por orden: transcripcion, decision, resultado del brazo, tiempos
"""
import csv
import glob
import os
import shutil
import subprocess
import threading
import time
import wave
from datetime import datetime

import numpy as np
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger

from arm_broker.cliente_integrado import ClienteIntegrado
from jetcobot_voz import gemini_stt
from jetcobot_voz.gemini_stt import ErrorTranscripcion

CAMPOS = [
    'orden_id', 'fecha', 'modo', 'fuente_audio', 'audio', 'transcripcion', 'estado_stt',
    # decision del modelo (P1)
    'accion', 'objeto', 'color', 'zona', 'prioridad', 'permitido', 'causa', 'degradado', 'fuente',
    # lo que hizo el sistema
    'pedido_id', 'resultado', 'detalle_brazo',
    # tiempos (Parte C): epoch del Jetson y duraciones
    't_origen_epoch', 't_captura_ms', 't_transcripcion_ms', 't_ini_envio_epoch',
    # a llenar a mano en la demostracion (Parte B): ver tabla_ordenes --marcar
    'dicho_real', 'resultado_esperado', 'correcta',
]


class TranscriptorVoz(Node):

    def __init__(self):
        super().__init__('transcriptor_voz')
        p = self.declare_parameter
        # --- Google AI Studio (la clave NUNCA es parametro: solo se nombra la variable) ---
        self.var_clave = p('api_key_env', 'GOOGLE_API_KEY').value
        self.modelo = p('modelo', 'gemini-2.5-flash').value
        self.t_limite_stt = float(p('timeout_transcripcion_s', 8.0).value)
        self.pista = p('pista_vocabulario', 'cubo, rojo, azul, verde, amarillo, zona A, zona B, '
                       'zona C, recoge, lleva, toma, mueve, pasa, home, detente').value
        # --- cadena aguas abajo (P1 + P2) ---
        self.client_id = p('client_id', 'voz').value
        self.nombre_srv = p('nombre_servicio', '/interpretar_orden').value
        self.carpeta_clientes = os.path.abspath(
            os.path.expanduser(p('carpeta_clientes', 'evidencia_clientes').value))
        # --- entrada de audio ---
        # vacio => microfono | un archivo | varios separados por coma | carpeta | patron (*.wav).
        # Cada orden consume el SIGUIENTE archivo; cuando se acaban vuelve al microfono.
        self.archivos = self._expandir_archivos(p('archivo_audio', '').value)
        self.dispositivo = p('dispositivo_arecord', 'default').value
        self.sr = int(p('sample_rate', 16000).value)
        self.silencio_s = float(p('silencio_s', 1.0).value)        # silencio que cierra la frase
        self.umbral_rms = float(p('umbral_rms', 500.0).value)      # sobre int16
        self.espera_voz_s = float(p('espera_voz_s', 8.0).value)
        self.max_grab_s = float(p('max_grabacion_s', 10.0).value)
        # --- modo / registro ---
        self.forzar_texto = bool(p('forzar_texto', False).value)
        self.interactivo = bool(p('interactivo', True).value)
        self.dir_reg = os.path.abspath(os.path.expanduser(p('directorio_registro', 'evidencia_voz').value))
        os.makedirs(os.path.join(self.dir_reg, 'audio'), exist_ok=True)
        self.csv_ruta = os.path.join(self.dir_reg, 'registro_voz.csv')

        self.cliente = ClienteIntegrado(self.client_id, self.nombre_srv, self.carpeta_clientes)
        self.pub_estado = self.create_publisher(String, '/estado_voz', 10)
        self.create_service(Trigger, 'escuchar', self.on_escuchar)

        self.ocupado = threading.Lock()
        self.lock_filas = threading.Lock()
        self.filas = {}
        self._cargar_previas()
        self.contador = len(self.filas)
        self.get_logger().info(
            f'transcriptor_voz listo | modelo={self.modelo} | plazo STT={self.t_limite_stt}s | '
            f'fuente={f"{len(self.archivos)} archivo(s)" if self.archivos else "microfono"} | '
            f'registro={self.csv_ruta}')

    # ------------------------------------------------------------------ disparo
    def on_escuchar(self, _req, resp):
        if self.ocupado.locked():
            resp.success, resp.message = False, 'ya hay una orden en curso'
            return resp
        threading.Thread(target=self.procesar_una, daemon=True).start()
        resp.success, resp.message = True, 'escuchando'
        return resp

    @staticmethod
    def _expandir_archivos(valor):
        res = []
        for item in str(valor or '').split(','):
            item = os.path.expanduser(item.strip())
            if not item:
                continue
            if os.path.isdir(item):
                exts = tuple(gemini_stt.MIMES) + ('.webm', '.mp4')
                res += sorted(os.path.join(item, n) for n in os.listdir(item)
                              if n.lower().endswith(exts))
            elif any(c in item for c in '*?['):
                res += sorted(glob.glob(item))
            else:
                res.append(item)
        return res

    def procesar_una(self, archivo=None):
        """Una orden de punta a punta, hasta que el goal queda ENVIADO al broker.
        (No espera a que el brazo termine: el operador puede dictar la siguiente.)
        archivo: ruta de audio explicita; si no, el siguiente de la cola; si no hay, microfono."""
        if not self.ocupado.acquire(blocking=False):
            self.get_logger().warn('ya hay una orden en curso')
            return False
        try:
            if archivo is None and self.archivos:
                archivo = self.archivos.pop(0)
            self._pipeline(archivo)
            return True
        except Exception as e:      # nunca dejar el candado tomado
            self.get_logger().error(f'Error en la cadena de voz: {e!r}')
            return False
        finally:
            self.ocupado.release()

    # ------------------------------------------------------------------ captura
    def _grabar_microfono(self, destino_wav):
        """Graba con arecord hasta `silencio_s` de silencio tras la voz.
        Devuelve el instante del ULTIMO bloque con voz (= el operador termino de hablar)
        o None si nadie hablo."""
        cmd = ['arecord', '-q', '-D', self.dispositivo, '-f', 'S16_LE',
               '-r', str(self.sr), '-c', '1', '-t', 'raw']
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        n_bytes = int(self.sr * 0.1) * 2                       # bloques de 100 ms
        bloques, hablando, t_voz, t0 = [], False, None, time.time()
        try:
            while True:
                datos = proc.stdout.read(n_bytes)
                if len(datos) < n_bytes:
                    break
                ahora = time.time()
                bloques.append(datos)
                x = np.frombuffer(datos, dtype=np.int16).astype(np.float32)
                if float(np.sqrt(np.mean(x * x))) > self.umbral_rms:
                    hablando, t_voz = True, ahora
                if hablando and ahora - t_voz >= self.silencio_s:
                    break
                if not hablando and ahora - t0 > self.espera_voz_s:
                    break
                if ahora - t0 > self.max_grab_s:
                    break
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        if not hablando:
            return None
        with wave.open(destino_wav, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sr)
            w.writeframes(b''.join(bloques))
        return t_voz

    # ------------------------------------------------------------------ cadena
    def _preparar_archivo(self, origen, oid):
        """Copia el audio a evidencia_voz/audio/<id>.<ext>. Si el formato no lo acepta Gemini
        (webm, mp4...) o pesa demasiado, lo convierte a WAV 16 kHz mono con ffmpeg (conserva el original)."""
        ext = os.path.splitext(origen)[1].lower() or '.wav'
        destino = os.path.join(self.dir_reg, 'audio', oid + ext)
        shutil.copyfile(origen, destino)
        if ext in gemini_stt.MIMES and os.path.getsize(destino) <= gemini_stt.MAX_INLINE_BYTES:
            return destino
        if shutil.which('ffmpeg') is None:
            raise ErrorTranscripcion('audio_no_soportado', f'{ext} o muy grande y no hay ffmpeg')
        wav = os.path.join(self.dir_reg, 'audio', oid + '.wav')
        r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', destino, '-ac', '1',
                            '-ar', str(self.sr), wav], capture_output=True)
        if r.returncode != 0:
            raise ErrorTranscripcion('audio_no_soportado', r.stderr.decode(errors='ignore')[:150])
        return wav

    def _pipeline(self, archivo=None):
        self.contador += 1
        oid = f'{datetime.now():%Y%m%d_%H%M%S}_{self.contador:03d}'
        fila = {k: '' for k in CAMPOS}
        fila.update(orden_id=oid, fecha=datetime.now().isoformat(timespec='seconds'))
        with self.lock_filas:
            self.filas[oid] = fila
        audio_path, texto, motivo, t_origen = None, None, None, 0.0

        # 1) CAPTURA ----------------------------------------------------------
        if self.forzar_texto:
            motivo = 'forzado_por_parametro'
        elif archivo:
            fila['fuente_audio'] = 'archivo'
            archivo = os.path.expanduser(archivo)
            if not os.path.isfile(archivo):
                motivo = 'archivo_no_existe'
                self.get_logger().error(f'No existe el audio: {archivo}')
            else:
                t_origen = time.time()             # archivo: "termino de hablar" = ahora (captura ~ 0)
                try:
                    audio_path = self._preparar_archivo(archivo, oid)
                except (ErrorTranscripcion, OSError) as e:
                    motivo = getattr(e, 'motivo', 'audio_no_legible')
                    self.get_logger().warn(f'No se pudo preparar el audio ({e}).')
        else:
            fila['fuente_audio'] = 'microfono'
            self._estado('ESCUCHANDO... habla ahora')
            audio_path = os.path.join(self.dir_reg, 'audio', oid + '.wav')
            try:
                t_origen = self._grabar_microfono(audio_path)
            except FileNotFoundError:
                t_origen, motivo = None, 'arecord_no_instalado'
            if t_origen is None:
                motivo = motivo or 'no_se_detecto_voz'
                audio_path, t_origen = None, 0.0
        if not audio_path:
            t_origen = 0.0
        if audio_path:
            t_wav = time.time()
            fila.update(audio=audio_path, t_origen_epoch=t_origen,
                        t_captura_ms=round((t_wav - t_origen) * 1000, 1))

        # 2) TRANSCRIPCION en la nube (con plazo propio) ------------------------
        if audio_path:
            self._estado('TRANSCRIBIENDO...')
            t0 = time.time()
            try:
                with open(audio_path, 'rb') as f:
                    texto = gemini_stt.transcribir(
                        f.read(), gemini_stt.mime_de(audio_path),
                        gemini_stt.leer_clave(self.var_clave), self.modelo,
                        self.t_limite_stt, self.pista)
                fila.update(modo='voz', estado_stt='ok')
            except ErrorTranscripcion as e:
                motivo = e.motivo
                self.get_logger().warn(f'La transcripcion fallo ({e}).')
            fila['t_transcripcion_ms'] = round((time.time() - t0) * 1000, 1)

        # 3) RESPALDO: MODO TEXTO POR TECLADO -----------------------------------
        if texto is None:
            self._estado(f'MODO TEXTO (motivo: {motivo}). El brazo no espera: escribe la orden.')
            print(f'\n[MODO TEXTO | motivo: {motivo}]', flush=True)
            try:
                texto = input('Escribe la orden > ').strip()
            except EOFError:
                texto = ''
            t_origen = time.time()
            fila.update(modo='texto', estado_stt=f'texto_teclado({motivo})', t_origen_epoch=t_origen)
            if not texto:
                self.get_logger().warn('Orden vacia: se cancela.')
                fila['resultado'] = 'cancelada'
                self._volcar()
                return
        fila['transcripcion'] = texto
        if audio_path:                              # la transcripcion queda junto al audio
            with open(os.path.splitext(audio_path)[0] + '.txt', 'w', encoding='utf-8') as f:
                f.write(texto + '\n')
        self.get_logger().info(f'[{oid}] texto: "{texto}"')
        self._volcar()

        # 4) DECISION + COLA + BRAZO: lo construido en la P1 y la P2 ---------------
        if not self.cliente.act.wait_for_server(timeout_sec=1.0):
            self.get_logger().error('move_arm no esta activo: ¿corre el broker en este ROS_DOMAIN_ID?')

        def al_terminar(fc):
            res = fc.get('resultado', '')
            with self.lock_filas:
                fila['pedido_id'] = fc.get('pedido_id', '')
                fila['resultado'] = res
                if res == 'rechazado':
                    fila['detalle_brazo'] = 'RECHAZADA antes de encolar: ' + str(fc.get('motivo_rechazo_broker', ''))
                elif res == 'ok':
                    fila['detalle_brazo'] = (f"ejecutada (espera {fc.get('espera_s')} s, "
                                             f"plan {fc.get('planificador')}, error FK {fc.get('error_fk_mm')} mm)")
                else:
                    fila['detalle_brazo'] = 'NO completada: ' + str(fc.get('mensaje', ''))
            self._volcar()

        fila['t_ini_envio_epoch'] = time.time()
        d = self.cliente.enviar_frase(texto, t_origen_epoch=t_origen,
                                      esperar_resultado=False, al_terminar=al_terminar)
        with self.lock_filas:
            if d is None:
                fila['resultado'] = 'sin_decision'
                fila['detalle_brazo'] = '/interpretar_orden no respondio'
            else:
                for k in ('accion', 'objeto', 'color', 'zona', 'prioridad', 'permitido',
                          'causa', 'degradado', 'fuente'):
                    fila[k] = getattr(d, k, '')
                if not fila['resultado']:
                    fila['resultado'] = 'en_curso'
        self._volcar()

    # ------------------------------------------------------------------ utilidades
    def _estado(self, texto):
        self.get_logger().info(texto)
        m = String()
        m.data = texto
        self.pub_estado.publish(m)

    def _cargar_previas(self):
        if not os.path.exists(self.csv_ruta):
            return
        with open(self.csv_ruta, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r.get('orden_id'):
                    self.filas[r['orden_id']] = {k: r.get(k, '') for k in CAMPOS}

    def _volcar(self):
        """Reescribe el CSV completo (son pocas filas): una fila por orden, siempre al dia."""
        with self.lock_filas:
            tmp = self.csv_ruta + '.tmp'
            with open(tmp, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=CAMPOS)
                w.writeheader()
                w.writerows(self.filas.values())
            os.replace(tmp, self.csv_ruta)


def main(args=None):
    rclpy.init(args=args)
    nodo = TranscriptorVoz()
    ex = MultiThreadedExecutor(num_threads=4)
    ex.add_node(nodo)
    ex.add_node(nodo.cliente)
    hilo = threading.Thread(target=ex.spin, daemon=True)
    hilo.start()
    try:
        if nodo.interactivo:
            print('\nModo interactivo: Enter = hablar (o siguiente archivo en cola) | '
                  'escribe la RUTA de un audio para usarlo | q = salir.', flush=True)
            while rclpy.ok():
                try:
                    r = input('[Enter = hablar | ruta de audio | q] > ').strip()
                except EOFError:
                    break
                if r.lower() in ('q', 'salir', 'exit'):
                    break
                if r and os.path.isfile(os.path.expanduser(r)):
                    nodo.procesar_una(archivo=r)
                else:
                    nodo.procesar_una()
            nodo.cliente.decir('esperando los pedidos pendientes (Ctrl+C para salir ya)...')
            nodo.cliente.esperar_todos()
        else:
            while rclpy.ok():
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        ex.shutdown()
        hilo.join(timeout=2.0)
        nodo.cliente.destroy_node()
        nodo.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
