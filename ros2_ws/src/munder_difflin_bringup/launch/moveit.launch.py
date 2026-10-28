"""Sim + MoveIt 2 move_group (RViz optional). Arg rviz:=true to open RViz."""
import os
from ament_index_python.packages import get_package_share_directory as share
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    xacro_file = os.path.join(share('munder_difflin_description'), 'urdf', 'munder_difflin_panda.urdf.xacro')
    mc = (MoveItConfigsBuilder('panda', package_name='munder_difflin_moveit_config')
          .robot_description(file_path=xacro_file)
          .robot_description_semantic(file_path='config/panda.srdf')
          .robot_description_kinematics(file_path='config/kinematics.yaml')
          .joint_limits(file_path='config/joint_limits.yaml')
          .trajectory_execution(file_path='config/moveit_controllers.yaml')
          .planning_pipelines(pipelines=['ompl'])
          .planning_scene_monitor(publish_robot_description=True, publish_robot_description_semantic=True)
          .to_moveit_configs())
    sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(share('munder_difflin_bringup'), 'launch', 'sim.launch.py')),
        launch_arguments={'headless': LaunchConfiguration('headless'), 'rviz': 'false',
                          'render': LaunchConfiguration('render')}.items())
    move_group = Node(package='moveit_ros_move_group', executable='move_group', output='screen',
                      parameters=[mc.to_dict(), {'use_sim_time': True}])
    rviz = Node(package='rviz2', executable='rviz2', output='log', condition=IfCondition(LaunchConfiguration('rviz')),
                arguments=['-d', os.path.join(share('munder_difflin_moveit_config'), 'config', 'moveit.rviz')],
                parameters=[mc.robot_description, mc.robot_description_semantic, mc.robot_description_kinematics,
                            mc.planning_pipelines, mc.joint_limits, {'use_sim_time': True}])
    return LaunchDescription([
        DeclareLaunchArgument('headless', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='false'),
        DeclareLaunchArgument('render', default_value='auto'),
        sim, move_group, rviz])
