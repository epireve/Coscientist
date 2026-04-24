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
from tests.test_citation_validation import (
    AuditGateNewKindsTests,
    BibParserTests,
    IngestReferencesTests,
    ManuscriptReferencesSchemaTests,
    ValidateCitationsTests,
)
from tests.test_manuscript_auditability import (
    AuditGateProjectDbTests,
    CitationParserTests,
    CritiqueReflectProjectDbTests,
    IngestGraphIntegrationTests,
    ManuscriptCitationsSchemaTests,
    ResolveCitationsTests,
)
from tests.test_paper_artifact import PaperArtifactTests
from tests.test_reference_agent import (
    BibtexTests,
    PopulateCitationsTests,
    PopulateConceptsTests,
    ReadingStateTests,
    ReferenceAgentSchemaTests,
    RetractionTests,
    SyncTests,
)
from tests.test_refactor import ArtifactTests, GraphTests, ProjectTests
from tests.test_schema import SchemaTests
from tests.test_writing_style import (
    ApplyTests,
    AuditTests,
    FingerprintTests,
    TextstatsUnitTests,
)

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
        CitationParserTests,
        IngestGraphIntegrationTests,
        AuditGateProjectDbTests,
        CritiqueReflectProjectDbTests,
        ResolveCitationsTests,
        ManuscriptCitationsSchemaTests,
        BibParserTests,
        IngestReferencesTests,
        ValidateCitationsTests,
        AuditGateNewKindsTests,
        ManuscriptReferencesSchemaTests,
        SyncTests,
        BibtexTests,
        ReadingStateTests,
        RetractionTests,
        ReferenceAgentSchemaTests,
        PopulateCitationsTests,
        PopulateConceptsTests,
        FingerprintTests,
        AuditTests,
        ApplyTests,
        TextstatsUnitTests,
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
