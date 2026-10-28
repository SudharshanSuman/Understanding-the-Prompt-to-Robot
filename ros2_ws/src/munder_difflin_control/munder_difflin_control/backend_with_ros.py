"""Start the FastAPI backend with the RosExecutor plugged in (ROS sourced + backend venv + sim/move_group running).

    source /opt/ros/jazzy/setup.bash && source <ros2_ws>/install/setup.bash
    MD_API_TOKEN=<32+ chars> PYTHONPATH=<backend>:<ros2_ws>/pylib <backend>/.venv/bin/python -m munder_difflin_control.backend_with_ros

Uses app.main.main(), so MD_BIND_HOST (loopback by default) / MD_ALLOW_REMOTE checks and APP_PORT apply.
"""
from app.main import main

from .ros_executor import RosExecutor


def run():
    main(RosExecutor())


if __name__ == '__main__':
    run()
