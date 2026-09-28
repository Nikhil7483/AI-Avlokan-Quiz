import sys
from pathlib import Path

# Add root directory to sys.path so backend is importable
_root_dir = Path(__file__).resolve().parent.parent
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

from backend.app.main import *  # noqa: F401, F403
from backend.app.main import app  # noqa: F401
