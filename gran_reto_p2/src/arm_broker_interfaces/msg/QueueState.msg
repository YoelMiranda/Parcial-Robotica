# Estado de la cola del broker (RB-2), publicado en /arm/queue_state a 5 Hz.
builtin_interfaces/Time stamp
string executing_client
string executing_goal_id
float64 executing_elapsed_s
uint32 queue_length
string[] queued_goal_ids
string[] queued_clients
uint8[] queued_priorities
float64[] queued_wait_s
uint32 total_accepted
uint32 total_rejected
uint32 total_completed
# --- P2 (para el video: qué se pidió y en qué etapa va) ---
string executing_descripcion
string executing_etapa
string[] queued_descripciones
float64[] queued_puntajes
string politica
