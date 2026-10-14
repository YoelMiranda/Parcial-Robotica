"""Lanza el broker de la P2 con su YAML.

  ros2 launch arm_broker p2.launch.py                       # real
  ros2 launch arm_broker p2.launch.py simulado:=true        # ensayo sin brazo
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _nodos(context):
    share = get_package_share_directory('arm_broker')
    simulado = LaunchConfiguration('simulado').perform(context).lower() in ('true', '1')
    config = LaunchConfiguration('config').perform(context) or os.path.join(share, 'config', 'broker_p2.yaml')
    params = [config]
    if simulado:
        params.append(os.path.join(share, 'config', 'broker_p2_simulado.yaml'))
    return [Node(package='arm_broker', executable='broker', name='arm_broker',
                 output='screen', emulate_tty=True, parameters=params)]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('simulado', default_value='false'),
        DeclareLaunchArgument('config', default_value=''),
        OpaqueFunction(function=_nodos),
    ])
