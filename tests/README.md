# tests/

Plan and pass criteria: `docs/project/TEST_PLAN.md`. Layers: L0 unit (default), L1 `ros`, L2 `gazebo`.

    python3 -m venv /tmp/md-test-venv && /tmp/md-test-venv/bin/pip install pytest pytest-timeout -r backend/requirements.txt   # any venv outside the repo works
    pytest -c tests/pytest.ini tests -m unit          # L0
    source /opt/ros/jazzy/setup.bash && pytest -c tests/pytest.ini tests -m "ros and not gazebo"   # L1
    MD_RUN_GAZEBO=1 pytest -c tests/pytest.ini tests -m gazebo                                     # L2

Always read the skip summary (`-ra` is on). A skip means NOT verified.
Backend contract assumptions the tests depend on: `tests/support/adapter.py` (CA-1..CA-6).
