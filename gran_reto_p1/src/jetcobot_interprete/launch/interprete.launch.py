from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("laya_url", default_value="http://127.0.0.1:8000"),
        DeclareLaunchArgument("timeout_s", default_value="1.0"),
        DeclareLaunchArgument("modelo", default_value=""),
        DeclareLaunchArgument("log_csv", default_value=""),
        Node(
            package="jetcobot_interprete",
            executable="interprete_ordenes",
            name="interprete_ordenes",
            output="screen",
            parameters=[{
                "laya_url": ParameterValue(LaunchConfiguration("laya_url"), value_type=str),
                "timeout_s": ParameterValue(LaunchConfiguration("timeout_s"), value_type=float),
                "modelo": ParameterValue(LaunchConfiguration("modelo"), value_type=str),
                "log_csv": ParameterValue(LaunchConfiguration("log_csv"), value_type=str),
            }],
        ),
    ])
