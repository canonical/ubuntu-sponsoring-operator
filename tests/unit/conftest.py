# Copyright 2026 Canonical
# See LICENSE file for licensing details.

"""Shared fixtures for the unit tests."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def no_subprocess():
    """Fail loudly if a test reaches a real subprocess call.

    Unit tests must mock out the Sponsoring methods that touch the machine
    (for example, an unmocked update_source would git clone/pull against the
    real filesystem of whoever runs the tests). Tests that intentionally
    exercise subprocess.run (e.g. via monkeypatch.setattr(sponsoring.subprocess,
    "run", ...)) still work, since their own patch is applied after this one.
    """
    with patch(
        "subprocess.run",
        side_effect=AssertionError(
            "unit test attempted to run a real subprocess; mock the Sponsoring method"
        ),
    ):
        yield
