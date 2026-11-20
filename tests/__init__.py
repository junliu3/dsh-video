"""Make the engine importable without installing it.

`python -m unittest discover -s tests -t .` executes this package first, so the
sys.path tweak applies to every test module.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "python"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
