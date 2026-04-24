#!/usr/bin/env python3
"""Run every test module in tests/ and report totals."""

from tests import _shim  # noqa: F401

import sys

from tests.harness import run_tests
from tests.test_agents import AgentFrontmatterTests
from tests.test_db_state_machine import DbTests
from tests.test_gates import (
    AttackVectorsTests,
    NoveltyGateTests,
    PublishabilityGateTests,
)
from tests.test_paper_artifact import PaperArtifactTests
from tests.test_refactor import ArtifactTests, GraphTests, ProjectTests
from tests.test_schema import SchemaTests

if __name__ == "__main__":
    failures = run_tests(
        SchemaTests,
        PaperArtifactTests,
        ProjectTests,
        ArtifactTests,
        GraphTests,
        DbTests,
        NoveltyGateTests,
        PublishabilityGateTests,
        AttackVectorsTests,
        AgentFrontmatterTests,
    )
    sys.exit(failures)
