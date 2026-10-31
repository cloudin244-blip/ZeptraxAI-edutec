# The implementation lives in zeptrax-learn-flow/api/_db_router.py because the Vercel
# project root is zeptrax-learn-flow/, and only files inside it are deployed.
# This module keeps `from db_router import ...` working for serve_app.py and the other handlers.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "zeptrax-learn-flow" / "api"))

from _db_router import *  # noqa: E402,F401,F403
from _db_router import db, handle_db_request  # noqa: E402,F401
