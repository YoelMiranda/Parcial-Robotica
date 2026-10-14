# Uso:  source ~/gran_reto_p2/entorno_p2.sh     (en CADA terminal del Jetson)
source /opt/ros/humble/setup.bash
source ~/gran_reto_p1/install/setup.bash                       # P1: jetcobot_interfaces + interprete
[ -f ~/gran_reto_p2/install/setup.bash ] && source ~/gran_reto_p2/install/setup.bash
export ROS_DOMAIN_ID=52            # <-- EL DE SU EQUIPO/BRAZO (el mismo que entorno.sh de la P1). ¡Confírmenlo!
export LAYA=http://172.51.1.10:8000   # <-- IP:puerto que da el docente
# export LAYA_API_KEY=...          # solo si el docente lo pide; NUNCA al repositorio
mkdir -p ~/demo_p2 && cd ~/demo_p2  # aquí quedan evidencia_p2/, bags y calibracion_camara.json
