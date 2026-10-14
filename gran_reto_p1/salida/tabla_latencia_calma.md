### Latencia — escenario: calma
Llamadas: 50 (frases=50 × repeticiones=1, hilos=1) · degradadas: 0 · sin respuesta: 7 · duración: 82.7 s

| Métrica | n | Mediana | P95 | Media | Mín | Máx |
|---|---:|---:|---:|---:|---:|---:|
| Tiempo visto por el cliente (ROS) [ms] | 43 | 279.1 | 371.3 | 295.5 | 231.4 | 513.0 |
| Tiempo total dentro del nodo [ms] | 43 | 274.4 | 361.6 | 288.8 | 225.1 | 506.9 |
| Ida y vuelta HTTP con LAYA (rtt) [ms] | 43 | 273.1 | 360.3 | 287.4 | 223.7 | 505.7 |
| Cálculo del modelo (informado por el servidor) [ms] | 43 | 224.2 | 290.8 | 234.7 | 191.2 | 324.6 |
| Red y cola = rtt − cálculo [ms] | 43 | 45.0 | 101.8 | 52.7 | 14.1 | 213.8 |

Línea base de red (GET /health): mediana 102.4 ms · P95 611.8 ms

Predicción vs medición (tiempo visto por el cliente): mediana predicha 60.0 ms, medida 279.1 ms (Δ +219.1); P95 predicho 120.0 ms, medido 371.3 ms (Δ +251.3)
