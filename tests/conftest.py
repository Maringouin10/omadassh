"""Load the integration modules that do not depend on Home Assistant."""

import importlib
from pathlib import Path
import sys
import types

FIXTURES = Path(__file__).parent / "fixtures"
_PKG_DIR = Path(__file__).parents[1] / "custom_components" / "omada_ssh"

# Register the package without running its __init__ (which needs Home Assistant).
_pkg = types.ModuleType("omada_ssh")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules.setdefault("omada_ssh", _pkg)

parsers = importlib.import_module("omada_ssh.parsers")
client = importlib.import_module("omada_ssh.client")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


try:
    import pytest_socket  # noqa: F401
except ImportError:
    import pytest

    @pytest.fixture
    def socket_enabled():
        """No-op when pytest-socket is not installed."""
