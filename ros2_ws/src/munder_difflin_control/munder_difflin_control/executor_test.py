"""Live test of RosExecutor against the running sim (moveit.launch.py). Scenarios: pick | estop | cancel | all.

Run with the backend venv python + ROS sourced (see docs/ros2_interfaces.md). Prints every PipelineStageEvent.
"""
import sys
import threading
import time

from app.schemas import RoboticTask, StageState

from .ros_executor import RosExecutor


def run_task(ex, task_id, obj, dst, cancel_after=None):
    events, cancelled = [], threading.Event()
    def emit(e):
        events.append(e)
        print(f'  [{e.stage:22s}] {e.state.value:9s} {e.message}', flush=True)
    err = []
    def target():
        try:
            ex.execute(RoboticTask(task_id=task_id, target_object=obj, destination=dst), emit, cancelled.is_set)
        except Exception as exc:  # noqa: BLE001
            err.append(exc)
    th = threading.Thread(target=target); th.start()
    return th, events, err, cancelled


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    ex = RosExecutor()
    t0 = time.time()
    while not ex.status().connected and time.time() - t0 < 60:
        time.sleep(1)
    print('STATUS:', ex.status().model_dump())
    ok = True
    if which in ('pick', 'all'):
        print('== pick red_cube -> storage_box')
        th, events, err, _ = run_task(ex, 't-pick', 'red_cube', 'storage_box')
        th.join(300)
        v = [e for e in events if e.stage == 'verification' and e.state == StageState.SUCCESS]
        print('PICK RESULT:', 'PASS' if (v and not err) else f'FAIL err={err}')
        ok &= bool(v and not err)
    if which in ('estop', 'all'):
        print('== e-stop during motion (blue_cube -> platform)')
        th, events, err, _ = run_task(ex, 't-estop', 'blue_cube', 'platform')
        t1 = time.time()
        while time.time() - t1 < 120 and not any(e.stage == 'execution' and 'descending' in e.message or 'moving to above' in e.message for e in events):
            time.sleep(0.2)
        time.sleep(1.0)
        pre = max(abs(ex._node.vel.get(j, 0.0)) for j in ('panda_joint%d' % i for i in range(1, 8)))
        print(f'max arm joint velocity BEFORE e-stop: {pre:.4f} rad/s (arm is moving if > 0.01)')
        rep = ex.emergency_stop()
        print('E-STOP REPORT:', rep.model_dump())
        th.join(60)
        print('task thread error:', err)
        print('STATUS after stop:', ex.status().model_dump())
        rejected = False
        try:
            ex.execute(RoboticTask(task_id='t-after', target_object='blue_cube', destination='platform'), lambda e: None, lambda: False)
        except Exception as exc:  # noqa: BLE001
            rejected = True
            print('execute after e-stop refused:', exc)
        st = ex.reset()
        print('STATUS after reset:', st.model_dump())
        good = rep.status == 'e_stop_confirmed' and rejected and err and st.can_execute
        print('ESTOP RESULT:', 'PASS' if good else 'FAIL')
        ok &= bool(good)
    if which in ('cancel', 'all'):
        print('== cancel mid-run (green_cylinder -> table_left)')
        th, events, err, cancelled = run_task(ex, 't-cancel', 'green_cylinder', 'table_left')
        t1 = time.time()
        while time.time() - t1 < 120 and not any(e.stage == 'execution' for e in events):
            time.sleep(0.2)
        time.sleep(2.0)
        cancelled.set(); ex.cancel('t-cancel')
        th.join(60)
        c = [e for e in events if e.state == StageState.CANCELLED]
        print('CANCEL RESULT:', 'PASS' if c and not err else f'FAIL err={err}')
        ok &= bool(c and not err)
    print('ALL:', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
