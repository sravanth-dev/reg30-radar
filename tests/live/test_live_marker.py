"""Placeholder for the live suite.

Real network tests land here from Slice 0 Step 2 onward. Until then this exists so that a
plain `pytest` run reports it as deselected, which is the evidence that the `live` marker
is keeping network tests out of the default run.
"""

import pytest


@pytest.mark.live
def test_live_suite_is_selectable():
    assert True
