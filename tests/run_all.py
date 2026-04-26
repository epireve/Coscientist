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
from tests.test_citation_collisions import (
    AmbiguousCitationTests,
    AuditGateAmbiguousKindTests,
    DisambiguatedKeyColumnTests,
    DisambiguationUnitTests,
    IngestDisambiguationTests,
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
from tests.test_tournament import (
    EloMathTests,
    LeaderboardTests,
    PairwiseTests,
    RecordHypothesisTests,
    RecordMatchTests,
)
from tests.test_v0_12_1_hardening import (
    CalibrationHardFailTests,
    HedgeQuotedContextTests,
    KFactorDecayTests,
    NoveltyAnchorUniquenessTests,
    PdfIntegrityTests,
)
from tests.test_v0_13_infrastructure import (
    JournalDriftTests,
    LockfileTests,
    MigrationTests,
    RetryTests,
    TransactionTests,
)
from tests.test_v0_14_adoption import (
    ArtifactLockAdoptionTests,
    MigrationsAdoptionTests,
    MultiDbTxAdoptionTests,
    RetryAdoptionTests,
)
from tests.test_deep_research_pipeline import (
    BreakIdempotencyTests,
    ClaimTests,
    EdgeCaseTests,
    InitTests,
    NextPhaseTests,
    PhaseOutputTests,
    ResumeTests,
)
from tests.test_overnight import (
    CliEdgeTests as OvernightCliEdgeTests,
    DigestTests,
    OvernightInitTests,
    QueueBreakTests,
)
from tests.test_pdf_extract_state_machine import (
    CliEdgeTests as PdfExtractCliEdgeTests,
    DoclingMissingTests,
    IdempotencyTests as PdfExtractIdempotencyTests,
    PreExtractGuardTests,
    V023BehavioralTests,
    V023FixesTests,
)
from tests.test_manuscript_dogfood import (
    ManuscriptDogfoodTests,
    PandocStyleBibTests,
)
from tests.test_paper_state_machine import (
    AcquireGateTests,
    AcquireIntegrityTests,
    AuditLogTests,
    CliEdgeCaseTests as PaperCliEdgeCaseTests,
    DiscoveredStateTests,
    StateMonotonicityTests,
)
from tests.test_personal_knowledge import (
    CrossProjectSearchTests,
    DashboardTests,
    FindPaperTests,
    JournalAddTests,
    JournalListTests,
    JournalSchemaTests,
    JournalSearchTests,
)
from tests.test_writing_style import (
    ApplyTests,
    AuditTests,
    FingerprintTests,
    TextstatsUnitTests,
)
from tests.test_manuscript_draft import (
    CliEdgeTests as ManuscriptDraftCliEdgeTests,
    DraftInitTests,
    DraftSectionTests,
    DraftStatusTests,
    IdempotencyTests as ManuscriptDraftIdempotencyTests,
    TemplateTests,
)
from tests.test_manuscript_format import (
    CliEdgeTests as FormatCliEdgeTests,
    FormatCleanTests,
    FormatExportTests,
    FormatListTests,
    PandocUtilsTests,
)
from tests.test_manuscript_revise import (
    CliEdgeTests as ReviseCliEdgeTests,
    IngestReviewTests,
    PlanTests,
    RespondTests,
    ReviewParserTests,
    StateGuardTests,
    StatusTests,
)
from tests.test_manuscript_version import (
    CliEdgeTests as VersionCliEdgeTests,
    DiffTests,
    LogTests,
    RestoreTests,
    SnapshotTests,
    VersionStoreTests,
)
from tests.test_systematic_review import (
    BiasTests,
    CliEdgeTests as ReviewCliEdgeTests,
    ExtractionTests,
    PrismaTests,
    ProtocolInitTests,
    ScreeningTests,
    SearchTests,
    StatusTests as ReviewStatusTests,
)
from tests.test_figure_agent import (
    TestAudit,
    TestCaption,
    TestCheckPalette,
    TestList,
    TestRegister,
)
from tests.test_retraction_watch import (
    AlertTests,
    ScanTests,
    StatusTests as RetractionStatusTests,
)
from tests.test_statistics import (
    TestAssumptionCheck,
    TestEffectSize,
    TestMathUtils,
    TestMetaAnalysis,
    TestPower,
    TestTestSelect,
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
        DisambiguationUnitTests,
        IngestDisambiguationTests,
        AmbiguousCitationTests,
        AuditGateAmbiguousKindTests,
        DisambiguatedKeyColumnTests,
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
        JournalAddTests,
        JournalListTests,
        JournalSearchTests,
        DashboardTests,
        CrossProjectSearchTests,
        FindPaperTests,
        JournalSchemaTests,
        RecordHypothesisTests,
        RecordMatchTests,
        PairwiseTests,
        LeaderboardTests,
        EloMathTests,
        PdfIntegrityTests,
        NoveltyAnchorUniquenessTests,
        HedgeQuotedContextTests,
        KFactorDecayTests,
        CalibrationHardFailTests,
        MigrationTests,
        TransactionTests,
        LockfileTests,
        RetryTests,
        JournalDriftTests,
        # v0.14 adoption
        MigrationsAdoptionTests,
        ArtifactLockAdoptionTests,
        RetryAdoptionTests,
        MultiDbTxAdoptionTests,
        # v0.15 dry-run pipeline harness
        InitTests,
        NextPhaseTests,
        PhaseOutputTests,
        ClaimTests,
        ResumeTests,
        BreakIdempotencyTests,
        EdgeCaseTests,
        # v0.28 overnight mode
        OvernightInitTests,
        QueueBreakTests,
        DigestTests,
        OvernightCliEdgeTests,
        # v0.20 pdf-extract dry-run harness + v0.23 fixes
        PreExtractGuardTests,
        DoclingMissingTests,
        PdfExtractIdempotencyTests,
        PdfExtractCliEdgeTests,
        V023FixesTests,
        V023BehavioralTests,
        # v0.21 manuscript subsystem dogfood + v0.23 pandoc bib fix
        ManuscriptDogfoodTests,
        PandocStyleBibTests,
        # Per-paper state machine harness
        DiscoveredStateTests,
        AcquireGateTests,
        AcquireIntegrityTests,
        AuditLogTests,
        StateMonotonicityTests,
        PaperCliEdgeCaseTests,
        AgentFrontmatterTests,
        # v0.26 manuscript-draft
        TemplateTests,
        DraftInitTests,
        ManuscriptDraftIdempotencyTests,
        DraftSectionTests,
        DraftStatusTests,
        ManuscriptDraftCliEdgeTests,
        # v0.27 manuscript-format, manuscript-revise, manuscript-version
        PandocUtilsTests,
        FormatExportTests,
        FormatListTests,
        FormatCleanTests,
        FormatCliEdgeTests,
        ReviewParserTests,
        IngestReviewTests,
        PlanTests,
        RespondTests,
        StatusTests,
        StateGuardTests,
        ReviseCliEdgeTests,
        VersionStoreTests,
        SnapshotTests,
        LogTests,
        DiffTests,
        RestoreTests,
        VersionCliEdgeTests,
        # v0.28 systematic-review
        ProtocolInitTests,
        SearchTests,
        ScreeningTests,
        ExtractionTests,
        BiasTests,
        PrismaTests,
        ReviewStatusTests,
        ReviewCliEdgeTests,
        # figure-agent
        TestRegister,
        TestAudit,
        TestCaption,
        TestList,
        TestCheckPalette,
        # retraction-watch skill
        ScanTests,
        AlertTests,
        RetractionStatusTests,
        # statistics skill
        TestMathUtils,
        TestEffectSize,
        TestPower,
        TestMetaAnalysis,
        TestTestSelect,
        TestAssumptionCheck,
        # Integration + regression
        ResearchFlowIntegrationTests,
        CrossSkillArtifactContractTests,
        SchemaRegressionTests,
        CompilationMetaTests,
        ConfigValidationTests,
        LayoutRegressionTests,
    )
    sys.exit(failures)
