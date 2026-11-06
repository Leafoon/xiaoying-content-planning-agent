"""Planning compatibility module.

The actual planning loop lives in :mod:`src.agent.core`; this module keeps the
model-facing decision contract discoverable for integrations.
"""
from ..models.schemas import Decision
from ..mock.mock_model import MockModelClient

__all__ = ["Decision", "MockModelClient"]
