"""Start the FastAPI backend with the RosExecutor plugged in (ROS sourced + backend venv + sim/move_group running).

    source /opt/ros/jazzy/setup.bash && source <ros2_ws>/install/setup.bash
    MD_API_TOKEN=<32+ chars> PYTHONPATH=<backend>:<ros2_ws>/pylib <backend>/.venv/bin/python -m munder_difflin_control.backend_with_ros

Uses app.main.main(), so MD_BIND_HOST (loopback by default) / MD_ALLOW_REMOTE checks and APP_PORT apply.
"""
import os

# DDS stays on this machine (SEC-011-D1); set before anything imports rclpy
os.environ['ROS_LOCALHOST_ONLY'] = '1'
os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'

from app.main import main  # noqa: E402

from .ros_executor import RosExecutor  # noqa: E402


def run():
    main(RosExecutor())


if __name__ == '__main__':
    run()
