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
from tests.test_integration import (
    CompilationMetaTests,
    ConfigValidationTests,
    CrossSkillArtifactContractTests,
    LayoutRegressionTests,
    ResearchFlowIntegrationTests,
    SchemaRegressionTests,
)
from tests.test_manuscript import (
    AuditGateTests,
    CritiqueGateTests,
    IngestTests,
    ManuscriptSchemaTests,
    ReflectGateTests,
)
from tests.test_paper_artifact import PaperArtifactTests
from tests.test_reference_agent import (
    BibtexTests,
    ReadingStateTests,
    ReferenceAgentSchemaTests,
    RetractionTests,
    SyncTests,
)
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
        IngestTests,
        AuditGateTests,
        CritiqueGateTests,
        ReflectGateTests,
        ManuscriptSchemaTests,
        SyncTests,
        BibtexTests,
        ReadingStateTests,
        RetractionTests,
        ReferenceAgentSchemaTests,
        AgentFrontmatterTests,
        # Integration + regression
        ResearchFlowIntegrationTests,
        CrossSkillArtifactContractTests,
        SchemaRegressionTests,
        CompilationMetaTests,
        ConfigValidationTests,
        LayoutRegressionTests,
    )
    sys.exit(failures)
