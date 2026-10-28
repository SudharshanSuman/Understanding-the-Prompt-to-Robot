"""Gazebo Harmonic (headless by default) + Panda + ros2_control controllers."""
import os
import xacro
from ament_index_python.packages import get_package_share_directory as share
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, EmitEvent, ExecuteProcess, SetEnvironmentVariable, RegisterEventHandler
from launch.events import Shutdown
from launch.conditions import IfCondition, UnlessCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    headless = LaunchConfiguration('headless')
    rviz = LaunchConfiguration('rviz')
    world = os.path.join(share('munder_difflin_gazebo'), 'worlds', 'munder_difflin.sdf')
    xacro_file = os.path.join(share('munder_difflin_description'), 'urdf', 'munder_difflin_panda.urdf.xacro')
    # xacro python API: the workspace path contains spaces, which break a shell-split Command
    robot_description = xacro.process_file(xacro_file).toxml()
    worlds_dir = os.path.dirname(world)
    dds_local = [SetEnvironmentVariable('ROS_LOCALHOST_ONLY', '1'), SetEnvironmentVariable('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST')]  # SEC-011-D1
    gz_env = SetEnvironmentVariable('GZ_SIM_RESOURCE_PATH', worlds_dir + os.pathsep + os.environ.get('GZ_SIM_RESOURCE_PATH', ''))

    # -s = server only (no GUI, no rendering): light on RAM. gz_server.sh keeps gz in its own process group so
    # Ctrl+C / launch shutdown cannot leave an orphan server behind.
    gz_script = os.path.join(share('munder_difflin_bringup'), '..', '..', 'lib', 'munder_difflin_bringup', 'gz_server.sh')
    gz_script = os.path.normpath(gz_script)
    render = LaunchConfiguration('render')
    gz_headless = ExecuteProcess(cmd=[gz_script, render, '-r', '-s', '-v2', 'munder_difflin.sdf'], output='screen',
                                 sigterm_timeout='15', sigkill_timeout='10', condition=IfCondition(headless))
    gz_gui = ExecuteProcess(cmd=[gz_script, render, '-r', '-v2', 'munder_difflin.sdf'], output='screen',
                            sigterm_timeout='15', sigkill_timeout='10', condition=UnlessCondition(headless))
    shutdown_on_gz_exit = [RegisterEventHandler(OnProcessExit(target_action=a, on_exit=[EmitEvent(event=Shutdown(reason='gz exited'))]))
                           for a in (gz_headless, gz_gui)]

    rsp = Node(package='robot_state_publisher', executable='robot_state_publisher', output='screen',
               parameters=[{'robot_description': robot_description, 'use_sim_time': True}])
    spawn = Node(package='ros_gz_sim', executable='create', output='screen',
                 arguments=['-topic', 'robot_description', '-name', 'panda', '-world', 'munder_difflin'])
    clock = Node(package='ros_gz_bridge', executable='parameter_bridge', name='clock_bridge', output='screen',
                 arguments=['/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock'])

    objs = ['red_cube', 'blue_cube', 'green_cylinder']
    bridge_args = []
    for o in objs:
        bridge_args += [f'/model/{o}/pose@geometry_msgs/msg/Pose[gz.msgs.Pose',
                        f'/munder_difflin/gz/attach/{o}@std_msgs/msg/Empty]gz.msgs.Empty',
                        f'/munder_difflin/gz/detach/{o}@std_msgs/msg/Empty]gz.msgs.Empty',
                        f'/munder_difflin/gz/attached/{o}@std_msgs/msg/Bool[gz.msgs.Boolean']
    # ground-truth poses (stand-in for perception) and attach/detach commands for the DetachableJoint plugins
    gz_bridge = Node(package='ros_gz_bridge', executable='parameter_bridge', name='gz_bridge', output='screen',
                     arguments=bridge_args)

    def spawner(name):
        return Node(package='controller_manager', executable='spawner', output='screen',
                    arguments=[name, '--controller-manager', '/controller_manager', '--controller-manager-timeout', '60'])

    jsb, arm, hand = spawner('joint_state_broadcaster'), spawner('panda_arm_controller'), spawner('panda_hand_controller')
    chain = [
        RegisterEventHandler(OnProcessExit(target_action=spawn, on_exit=[jsb])),
        RegisterEventHandler(OnProcessExit(target_action=jsb, on_exit=[arm, hand])),
    ]
    rviz_node = Node(package='rviz2', executable='rviz2', condition=IfCondition(rviz), output='log',
                     parameters=[{'use_sim_time': True}])
    return LaunchDescription([
        DeclareLaunchArgument('headless', default_value='true', description='gz server only (no Gazebo GUI)'),
        DeclareLaunchArgument('rviz', default_value='false'),
        DeclareLaunchArgument('render', default_value='auto', description='auto (AMD/Mesa hardware) | software (LIBGL_ALWAYS_SOFTWARE)'),
        *dds_local, gz_env, gz_headless, gz_gui, *shutdown_on_gz_exit, rsp, clock, gz_bridge, spawn, *chain, rviz_node,
    ])
