"""Public native terminal widget and replaceable engine interface."""

from .engine.api import TerminalEngineProtocol
from .widget import NativeTerminalWidget

__all__ = ["NativeTerminalWidget", "TerminalEngineProtocol"]
