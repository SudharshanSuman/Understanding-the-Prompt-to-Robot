"""Unit tests run without a simulator. They need the ROS 2 environment sourced and the backend package (app.executor)."""
import os
import sys
from pathlib import Path

os.environ['ROS_LOCALHOST_ONLY'] = '1'
os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
os.environ.setdefault('ROS_DOMAIN_ID', '99')   # keep clear of the sim domains

# find <repo>/backend (and its venv, which has pydantic) relative to this file or from MD_BACKEND_DIR
for base in [Path(os.environ[k]) for k in ('MD_BACKEND_DIR',) if k in os.environ] + list(Path(__file__).resolve().parents):
    cand = base if (base / 'app' / 'executor.py').exists() else base / 'backend'
    if (cand / 'app' / 'executor.py').exists():
        sys.path.insert(0, str(cand))
        for sp in cand.glob('.venv/lib/python3*/site-packages'):
            sys.path.insert(0, str(sp))
        sys.modules.pop('typing_extensions', None)   # the system copy is too old for pydantic; re-import from the venv
        break
