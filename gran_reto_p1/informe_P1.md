# Informe — Pregunta 1: Servicio de interpretación de órdenes

**Equipo N.º:** ____  **Integrantes:** ____________________  **ROS_DOMAIN_ID:** ____
**Servidor LAYA (IP:puerto / preset):** ____________  **Fecha:** ___/___/2026

> Las secciones 1–4 describen el diseño y ya están redactadas. Las secciones 5–8 se llenan con **sus** mediciones
> (los archivos están en `salida/`). Todo número del informe debe poder rastrearse a un CSV o bag.

---

## 1. Arquitectura

`operador → /interpretar_orden → interprete_ordenes → HTTP → servidor LAYA (PC Windows)`.
El nodo `interprete_ordenes` es el único punto de contacto con la computadora Windows. LAYA no es un nodo ROS 2: se
alcanza por HTTP (`POST /v1/systemone`), fuera del `ROS_DOMAIN_ID`.

En **una sola petición** y **una sola pasada del modelo** se hacen siete preguntas tipadas:

| Campo | Tipo LAYA | Conjunto de respuestas |
|---|---|---|
| acción | `choice` | recoger, depositar, ir_home, detener, ninguna |
| objeto | `choice` | cubo, esfera, cilindro, ninguno |
| color | `choice` | rojo, azul, verde, amarillo, ninguno |
| zona | `choice` | zona_a, zona_b, zona_c, ninguna |
| causa (de rechazo) | `choice` | ninguna, riesgo_personas, dano_a_objetos_o_robot, desactiva_seguridad, fuera_de_zona_de_trabajo |
| prioridad | `score` (5 niveles) | 1 … 5 (`1 + round(score)`; `detener` ⇒ 5) |
| permitido | `noul` (¿es peligrosa?) | `permitido = P(peligrosa) < umbral_peligro` |

## 2. Por qué la salida debe ser una decisión tipada y no texto generado

1. **Espacio de acciones cerrado y verificable.** Cada campo pertenece a un conjunto finito que el nodo valida contra
   `vocabulario.py` antes de responder. Una etiqueta fuera del conjunto se descarta y se resuelve con el respaldo. Un
   modelo que redacta puede producir cualquier cadena (coordenadas, comandos, frases ambiguas); un brazo que mueve
   objetos y está cerca de personas no puede aceptar entradas no acotadas.
2. **Seguridad.** El texto libre abre la puerta a alucinaciones y a inyección de instrucciones (una frase como «ignora
   las reglas y ve a ...»). Con una elección entre etiquetas fijas, lo peor que puede pasar es elegir una etiqueta
   equivocada **del conjunto permitido**, nunca inventar una acción nueva. Además la decisión «permitido» es un valor
   explícito que el broker puede rechazar antes de encolar.
3. **Latencia acotada y predecible.** La generación de texto es autoregresiva: el tiempo crece con la longitud de la
   respuesta y varía de una llamada a otra. LAYA contesta en una sola pasada, de modo que el tiempo de cálculo es casi
   constante y se puede fijar un `timeout_s` con sentido.
4. **Confianza calibrada y umbrales.** Una elección, un puntaje o un sí/no traen probabilidades que permiten fijar un
   umbral (`umbral_peligro`) y medir errores; un párrafo no.
5. **Medible y auditable.** Una decisión tipada se compara contra la verdad campo por campo (exactitud, matriz de
   errores) y queda registrada en la bitácora; el texto libre exigiría juzgar su significado.
6. **Interfaz estable.** El servicio devuelve enteros, booleanos y etiquetas que el broker de prioridades (RB-2) usa
   directamente, sin analizar texto. El mensaje de rechazo sale de una tabla fija (`MOTIVOS`), no del modelo.

## 3. Tiempo límite y degradación

* El límite es el parámetro **`timeout_s`** (valor usado: ____ s; justificación: ____________________________).
  Debe ser mayor que la latencia normal bajo carga y mucho menor que lo que el operador tolera.
* La consulta a LAYA corre en un hilo y el nodo espera **como máximo `timeout_s`**, aunque el DNS o el socket se
  cuelguen. Si vence, hay un error HTTP/de red, o la respuesta es incompleta o fuera de vocabulario, el nodo resuelve
  con el **clasificador por palabras clave** (microsegundos, sin red) y responde con `degradado=true`,
  `fuente="palabras_clave"` y `detalle_error` con la causa. El peor caso del servicio es `timeout_s` + microsegundos.
* El servicio atiende en un `MultiThreadedExecutor` con grupo reentrante, de modo que varias órdenes simultáneas no se
  bloquean entre sí (necesario para las Preguntas 2 y 3).
* Evidencia: prueba con el servidor inalcanzable/colgado (`log_csv`, video o bag): ____________________.

## 4. Metodología de medición

* **Conjunto:** las 50 frases del docente (`frases_docente.csv`); calentamiento de 3 llamadas descartadas.
* **Qué se mide por llamada:** `cliente_ms` (visto por quien llama al servicio, incluye ROS/DDS), `total_ms` (dentro del
  nodo), `rtt_ms` (ida y vuelta HTTP), `servidor_ms` (cálculo que **informa el servidor**, cabecera
  `X-Inference-Time-Ms`) y `red_ms = rtt_ms − servidor_ms`. `red_ms` agrupa red, serialización y **espera en la cola
  del servidor**; la línea base de red pura es la mediana de `GET /health` (`ping_health_ms`).
* **Estadísticos:** mediana y percentil 95 con interpolación lineal (equivalente a `numpy.percentile`).
  Con 50 muestras el P95 depende de las 2–3 llamadas más lentas: es una estimación ruidosa.
* Las llamadas degradadas se cuentan aparte y **no** entran en `rtt/servidor/red`.
* **Escenarios:** (a) calma: un solo equipo consulta; (b) carga: todos los equipos al mismo tiempo, inicio sincronizado
  (`--inicio`). Hora y equipos participantes: ____________________.
* **Predicción previa** (obligatoria; la escribimos antes de medir): ver §6.

## 5. Resultados de latencia

### 5.1 En calma
<!-- Pegar salida/tabla_latencia_calma.md -->

### 5.2 Bajo carga
<!-- Pegar salida/tabla_latencia_carga.md -->

### 5.3 Comparación
<!-- Pegar la salida de: medir_latencia --comparar salida/resumen_calma.json salida/resumen_carga.json -->

### 5.4 Explicación de la diferencia (completar con SUS números)

Guía de lectura de la tabla: si `servidor_ms` (cálculo) es parecido en calma y en carga, pero `rtt_ms` crece, la
diferencia **no** la produce el modelo sino la **espera**: el servidor es compartido, la GPU atiende los pedidos en
serie o en lotes pequeños y cada equipo se encuentra con los pedidos de los demás por delante (cola), además de una
red local más ocupada. Verifiquen con `red_ms` frente a la línea base `/health`. Si en cambio `servidor_ms` también
sube, el cálculo mismo se degrada (GPU saturada, lotes más grandes). Argumenten con sus cifras: ____________________.
Indiquen también cuántas llamadas pasaron al respaldo en carga: ____ de ____ y qué implica para la elección de
`timeout_s`.

## 6. Predicción vs medición

| Escenario | Mediana predicha | Mediana medida | Δ | P95 predicho | P95 medido | Δ |
|---|---:|---:|---:|---:|---:|---:|
| Calma | | | | | | |
| Carga | | | | | | |

Comentario sobre por qué se equivocó la predicción: ____________________.

## 7. Exactitud

<!-- Pegar salida/tabla_exactitud.md (tabla comparativa LAYA vs palabras clave) -->

Notas: LAYA se evalúa solo sobre respuestas no degradadas (n = ____). «Decisión completa» exige todos los campos
correctos (prioridad ±1 como segunda fila). Se destaca el número de órdenes prohibidas **aceptadas** por error, el
error más grave en un sistema robótico.

## 8. Comentario: qué tipo de frases falla cada método (media página)

Usen `salida/fallos_laya.csv`, `salida/fallos_kw.csv` y la tabla «Fallos por tipo de frase». Estructura sugerida:

* **Palabras clave.** Revisen si falla en: negaciones («no agarres…»), verbos fuera de la lista o sinónimos
  («alcánzame», «necesito…»), frases telegráficas sin verbo («cubo azul zona B»), faltas de ortografía o dictado
  («recoje», «royo»), órdenes peligrosas expresadas sin las palabras de la lista de bloqueo, y falsos rechazos por
  palabras ambiguas («con fuerza», «mano»). Expliquen por qué una regla léxica no ve el significado.
* **LAYA.** Revisen si falla en: colores u objetos ausentes de la mesa, prioridades intermedias (el puntaje es
  ordinal y se redondea), frases peligrosas muy sutiles o muy cortas, diferencia entre `depositar` y `recoger`,
  etiquetas con descripciones parecidas (`ir_home` vs `detener`). Revisen el efecto de `umbral_peligro`.
* **Conclusión:** ¿qué pierde el sistema al caer al respaldo (qué frases dejan de entenderse) y qué se gana (latencia
  acotada, funciona sin red)? ____________________.

(Escriban aquí su texto, con ejemplos reales de las 50 frases.)

## 9. Evidencia entregada

| Archivo | Contenido |
|---|---|
| `salida/decisiones_calma.csv`, `decisiones_carga.csv` | 50 frases, verdad, decisión de LAYA y de palabras clave, latencias |
| `salida/resumen_*.json`, `tabla_latencia_*.md` | estadísticos y tablas |
| `salida/tabla_exactitud.md`, `fallos_*.csv` | exactitud y fallos |
| `salida/bitacora_servicio.csv` | una fila por consulta real al servicio (incluye degradaciones) |
| bag / video | prueba del respaldo con el servidor inalcanzable |
