from __future__ import annotations

import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for webapp UI seam tests")
def test_webapp_ui_node_suite() -> None:
    subprocess.run(
        ["node", "--test", "tests/webapp_ui.test.mjs"],
        check=True,
    )
