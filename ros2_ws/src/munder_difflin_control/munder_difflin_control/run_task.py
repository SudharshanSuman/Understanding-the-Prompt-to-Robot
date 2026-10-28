"""CLI: run one pick-and-place through RosExecutor against the running sim and print every stage event.

    python -m munder_difflin_control.run_task red_cube storage_box
Exit code 0 only if verification succeeded.
"""
import sys
import time

from app.schemas import RoboticTask, StageState

from .ros_executor import RosExecutor


def main():
    if len(sys.argv) != 3:
        print('usage: run_task <object> <destination>   e.g. run_task red_cube storage_box')
        return 2
    obj, dst = sys.argv[1], sys.argv[2]
    ex = RosExecutor()
    t0 = time.time()
    while not ex.status().connected and time.time() - t0 < 90:
        time.sleep(1)
    print('executor status:', ex.status().model_dump(), flush=True)
    events = []

    def emit(e):
        events.append(e)
        print(f'[{e.stage:22s}] {e.state.value:9s} {e.message}', flush=True)
    try:
        ex.execute(RoboticTask(task_id='cli-' + obj, target_object=obj, destination=dst), emit, lambda: False)
    except Exception as exc:  # noqa: BLE001
        print('FAILED:', exc)
        return 1
    ok = any(e.stage == 'verification' and e.state == StageState.SUCCESS for e in events)
    print('RESULT:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
