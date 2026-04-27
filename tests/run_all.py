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
from tests.test_evolve_loop import (
    CloseRoundTests as EvoCloseRoundTests,
    IntegrationTests as EvoIntegrationTests,
    LineageTests as EvoLineageTests,
    OpenRoundTests as EvoOpenRoundTests,
    StatusTests as EvoStatusTests,
)
from tests.test_audit_query import (
    CliTests as AuditCliTests,
    FetchesTests as AuditFetchesTests,
    IncludeArchivesTests as AuditIncludeArchivesTests,
    SandboxTests as AuditSandboxTests,
    SummaryTests as AuditSummaryTests,
)
from tests.test_audit_rotate import (
    CliTests as AuditRotateCliTests,
    InspectTests as AuditRotateInspectTests,
    ListArchivesTests as AuditRotateListArchivesTests,
    RotateTests as AuditRotateTests,
)
from tests.test_lib_cache import ArchivesForTests
from tests.test_rate_limit import (
    DomainParseTests as RateLimitDomainParseTests,
    WaitTests as RateLimitWaitTests,
)
from tests.test_agent_frontmatter import (
    BodyContentTests as AgentBodyContentTests,
    FrontmatterShapeTests as AgentFrontmatterShapeTests,
    ToolsFieldTests as AgentToolsFieldTests,
)
from tests.test_transaction_edges import (
    CardinalityTests as TxCardinalityTests,
    IsolationBetweenContextsTests as TxIsolationBetweenContextsTests,
    IsolationLevelTests as TxIsolationLevelTests,
)
from tests.test_persona_input import (
    DiscoveryTests as PersonaInputDiscoveryTests,
    ErrorHandlingTests as PersonaInputErrorTests,
    LayoutTests as PersonaInputLayoutTests,
    RoundTripTests as PersonaInputRoundTripTests,
)
from tests.test_harvest import (
    CliTests as HarvestCliTests,
    ShowTests as HarvestShowTests,
    StatusTests as HarvestStatusTests,
    WriteTests as HarvestWriteTests,
)
from tests.test_graph_query import (
    AuthorClusterTests,
    CliTests as GraphQueryCliTests,
    ConceptPathTests,
    ExpandCitationsTests,
    HubsTests as GraphQueryHubsTests,
    InDegreeTests,
    NeighborsTests,
)
from tests.test_bibtex_import import (
    CliTests as BibtexCliTests,
    DryRunTests as BibtexDryRunTests,
    ImportTests as BibtexImportTests,
    ParseOnlyTests as BibtexParseOnlyTests,
    ParseTests as BibtexParseTests,
)
from tests.test_citation_format_converter import (
    CliTests as CFCliTests,
    ConvertTests,
    FormatStyleTests,
    StylesCommandTests,
)
from tests.test_expedition_dry_run import FullPipelineTests
from tests.test_arxiv_to_markdown import (
    CliTests as ArxivToMarkdownCliTests,
    NormalizeArxivIdTests,
    RunFunctionTests as ArxivToMarkdownRunTests,
)
from tests.test_paper_discovery import (
    CliTests as PaperDiscoveryCliTests,
    MergeEntriesTests,
    RankTests as PaperDiscoveryRankTests,
)
from tests.test_research_eval import (
    EvalClaimsTests,
    EvalReferencesTests,
)
from tests.test_institutional_check import (
    CheckCommandTests as InstAccessCheckTests,
    IdpRunnerTests as InstAccessIdpRunnerTests,
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
from tests.test_preprint_alerts import (
    DigestTests as PreprintDigestTests,
    HistoryTests as PreprintHistoryTests,
    ListSubsTests,
    SubscribeTests,
)
from tests.test_peer_review import (
    ReviewTests,
    RespondTests,
    DecideTests,
    StatusTests as PeerReviewStatusTests,
)
from tests.test_grant_draft import (
    DraftInitTests,
    DraftSectionTests,
    DraftStatusTests,
    FundersListTests,
    OutlineTests,
)
from tests.test_idea_attacker import (
    GateCliTests as IdeaAttackerCliTests,
    GatePersistTests as IdeaAttackerPersistTests,
    GateValidationTests as IdeaAttackerValidationTests,
)
from tests.test_negative_results import (
    AnalyzeTests as NegResAnalyzeTests,
    InitTests as NegResInitTests,
    IntegrationTests as NegResIntegrationTests,
    ShareTests as NegResShareTests,
    StatusListTests as NegResStatusListTests,
)
from tests.test_dataset_agent import (
    HashTests as DatasetHashTests,
    ListStatusTests as DatasetListStatusTests,
    RegisterTests as DatasetRegisterTests,
    VersionTests as DatasetVersionTests,
)
from tests.test_credit_tracker import (
    AssignTests as CreditAssignTests,
    AuditTests as CreditAuditTests,
    ListTests as CreditListTests,
    RolesListTests as CreditRolesListTests,
    StatementTests as CreditStatementTests,
    UnassignTests as CreditUnassignTests,
)
from tests.test_reading_pace import (
    BacklogTests as ReadingPaceBacklogTests,
    ReadOnlyContractTests as ReadingPaceReadOnlyTests,
    SummaryTests as ReadingPaceSummaryTests,
    TrendTests as ReadingPaceTrendTests,
    VelocityTests as ReadingPaceVelocityTests,
)
from tests.test_slide_draft import (
    FormatsListTests as SlideFormatsListTests,
    ListCleanTests as SlideListCleanTests,
    OutlineTests as SlideOutlineTests,
    RenderTests as SlideRenderTests,
    SlideMdBuildTests as SlideMdBuildTests,
)
from tests.test_reviewer_assistant import (
    AddCommentTests as ReviewerAddCommentTests,
    ExportTests as ReviewerExportTests,
    IdStabilityTests as ReviewerIdStabilityTests,
    InitTests as ReviewerInitTests,
    RecommendationTests as ReviewerRecommendationTests,
    StatusTests as ReviewerStatusTests,
)
from tests.test_citation_alerts import (
    AddRemoveTests as CitationAlertsAddRemoveTests,
    DigestTests as CitationAlertsDigestTests,
    ListCheckTests as CitationAlertsListCheckTests,
    ListTrackedTests as CitationAlertsListTrackedTests,
    PersistTests as CitationAlertsPersistTests,
    StatusTests as CitationAlertsStatusTests,
)
from tests.test_field_trends import (
    AuthorsTests as FieldTrendsAuthorsTests,
    ConceptsTests as FieldTrendsConceptsTests,
    MomentumTests as FieldTrendsMomentumTests,
    PapersTests as FieldTrendsPapersTests,
    ReadOnlyTests as FieldTrendsReadOnlyTests,
    SummaryTests as FieldTrendsSummaryTests,
)
from tests.test_phase2_remaining import (
    DmpGeneratorTests,
    EthicsIrbTests,
    RegisteredReportsTests,
    ZenodoPrepareTests,
)
from tests.test_experiment_design import (
    InitTests as ExpDesignInitTests,
    MetricTests as ExpDesignMetricTests,
    PreregisterTests as ExpDesignPreregisterTests,
    StatusListTests as ExpDesignStatusListTests,
    VariableTests as ExpDesignVariableTests,
)
from tests.test_project_manager import (
    ActiveMarkerTests as PMActiveMarkerTests,
    ArchiveTests as PMArchiveTests,
    HelperTests as PMHelperTests,
    InitListTests as PMInitListTests,
    StatusTests as PMStatusTests,
)
from tests.test_meta_research import (
    ConceptsTests as MetaConceptsTests,
    ProductivityTests as MetaProductivityTests,
    ReadOnlyContractTests as MetaReadOnlyTests,
    SummaryTests as MetaSummaryTests,
    TrajectoryTests as MetaTrajectoryTests,
)
from tests.test_sandbox import (
    AuditTests as SandboxAuditTests,
    BuildArgsTests as SandboxBuildArgsTests,
    CheckCommandTests as SandboxCheckCommandTests,
    CmdRunValidationTests as SandboxCmdRunValidationTests,
    DiagnoseTests as SandboxDiagnoseTests,
    HelperTests as SandboxHelperTests,
    RunRequiresDaemonTests as SandboxRunRequiresDaemonTests,
    ValidateWorkspaceTests as SandboxValidateWorkspaceTests,
    WorkspaceLockTests as SandboxWorkspaceLockTests,
)
from tests.test_experiment_reproduce import (
    AnalyzeTests as ExpReproAnalyzeTests,
    MetricExtractionTests as ExpReproMetricExtractionTests,
    ReproduceCheckTests as ExpReproReproduceCheckTests,
    RunStateTransitionTests as ExpReproRunStateTransitionTests,
    StatusTests as ExpReproStatusTests,
)
# v0.53.x — Wide Research, mode selector, phase parallelization
from tests.test_wide_research import (
    CLITests as WideCLITests,
    CollectResultsTests as WideCollectResultsTests,
    CostEstimateTests as WideCostEstimateTests,
    DecomposeTests as WideDecomposeTests,
    EdgeCaseTests as WideEdgeCaseTests,
    Gate23ObserveTests as WideGate23ObserveTests,
    HandoffEdgeCaseTests as WideHandoffEdgeCaseTests,
    SynthesisTests as WideSynthesisTests,
    SynthesizeCLITests as WideSynthesizeCLITests,
    TaskSpecTests as WideTaskSpecTests,
    TaskTypeDefaultsTests as WideTaskTypeDefaultsTests,
    V537Tests as WideV537Tests,
    WideToDeepHandoffTests,
    WorkspaceTests as WideWorkspaceTests,
)
from tests.test_mode_selector import (
    ConfidenceTests as ModeConfidenceTests,
    ExplicitOverrideTests as ModeExplicitOverrideTests,
    ItemDrivenTests as ModeItemDrivenTests,
    QuestionDrivenTests as ModeQuestionDrivenTests,
)
from tests.test_phase_groups import (
    BatchableTests as PhaseGroupsBatchableTests,
    CmdNextPhaseBatchTests,
    GroupForTests as PhaseGroupsForTests,
)
# v0.54 — brief richness + retention transparency
from tests.test_brief_renderer import (
    DiscussionQuestionsTests as BriefDiscussionQuestionsTests,
    EvidenceTableTests as BriefEvidenceTableTests,
    HypothesisCardsTests as BriefHypothesisCardsTests,
    RunRecoveryTests as BriefRunRecoveryTests,
)
# v0.55 A5 Tier A — gap-analyzer + contribution-mapper + venue-match
from tests.test_a5_trio import (
    ContributionMapperTests,
    GapAnalyzerTests,
    VenueMatchTests,
)
# v0.56 A5 capstone — self-play debate
from tests.test_debate import (
    DecideVerdictTests,
    FalsifiabilityTests,
    GroundednessTests,
    PositionSerializationTests,
    PromptTests as DebatePromptTests,
    RenderBriefTests as DebateRenderBriefTests,
    ResponsivenessTests,
    ScorePositionTests,
    SpecificityTests,
)
# v0.57 — DB persistence + db-notify
from tests.test_v0_57_persistence import (
    AuditQueryRecordsTests,
    DbNotifyTests,
    MigrationV9Tests,
    SkillPersistTests,
    WideResearchPersistenceTests,
)
# v0.58 — resolve-citation skill
from tests.test_citation_resolver import (
    CitationResolverCLITests,
    CitationResolverParserTests,
    CitationResolverPickBestTests,
    CitationResolverScoreTests,
)
# v0.59 — graph-viz mermaid renderer
from tests.test_graph_viz import (
    CliTests as GraphVizCliTests,
    RenderMermaidTests,
    SubgraphTests as GraphVizSubgraphTests,
)
# v0.60 — writing-style venue overlays
from tests.test_venue_style_overlay import (
    CliTests as VenueOverlayCliTests,
    EdgeCaseTests as VenueOverlayEdgeCaseTests,
    HedgeDensityTests as VenueOverlayHedgeTests,
    PronounDetectionTests as VenueOverlayPronounTests,
    RegistryTests as VenueOverlayRegistryTests,
    TenseDetectionTests as VenueOverlayTenseTests,
    VoiceDetectionTests as VenueOverlayVoiceTests,
)
# v0.61 — calibration set tooling
from tests.test_calibration import (
    AddRemoveTests as CalibrationAddRemoveTests,
    CalibrationCaseTests,
    CliSmokeTests as CalibrationCliSmokeTests,
    CoverageCheckTests as CalibrationCoverageCheckTests,
    PersistenceTests as CalibrationPersistenceTests,
    RenderSummaryTests as CalibrationRenderSummaryTests,
    SlugifyTests as CalibrationSlugifyTests,
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
        EvoOpenRoundTests,
        EvoCloseRoundTests,
        EvoStatusTests,
        EvoLineageTests,
        EvoIntegrationTests,
        InstAccessCheckTests,
        InstAccessIdpRunnerTests,
        AuditFetchesTests,
        AuditSandboxTests,
        AuditSummaryTests,
        AuditIncludeArchivesTests,
        AuditCliTests,
        AuditRotateInspectTests,
        AuditRotateTests,
        AuditRotateListArchivesTests,
        AuditRotateCliTests,
        ArchivesForTests,
        RateLimitDomainParseTests,
        RateLimitWaitTests,
        AgentFrontmatterShapeTests,
        AgentToolsFieldTests,
        AgentBodyContentTests,
        TxCardinalityTests,
        TxIsolationLevelTests,
        TxIsolationBetweenContextsTests,
        PersonaInputRoundTripTests,
        PersonaInputErrorTests,
        PersonaInputDiscoveryTests,
        PersonaInputLayoutTests,
        HarvestWriteTests,
        HarvestStatusTests,
        HarvestShowTests,
        HarvestCliTests,
        ExpandCitationsTests,
        InDegreeTests,
        GraphQueryHubsTests,
        NeighborsTests,
        ConceptPathTests,
        AuthorClusterTests,
        GraphQueryCliTests,
        BibtexParseTests,
        BibtexParseOnlyTests,
        BibtexDryRunTests,
        BibtexImportTests,
        BibtexCliTests,
        StylesCommandTests,
        ConvertTests,
        FormatStyleTests,
        CFCliTests,
        FullPipelineTests,
        EvalReferencesTests,
        EvalClaimsTests,
        MergeEntriesTests,
        PaperDiscoveryRankTests,
        PaperDiscoveryCliTests,
        NormalizeArxivIdTests,
        ArxivToMarkdownRunTests,
        ArxivToMarkdownCliTests,
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
        # preprint-alerts skill
        SubscribeTests,
        PreprintDigestTests,
        ListSubsTests,
        PreprintHistoryTests,
        # peer-review skill
        ReviewTests,
        RespondTests,
        DecideTests,
        PeerReviewStatusTests,
        # grant-draft skill
        OutlineTests,
        DraftInitTests,
        DraftSectionTests,
        DraftStatusTests,
        FundersListTests,
        # idea-attacker skill
        IdeaAttackerValidationTests,
        IdeaAttackerPersistTests,
        IdeaAttackerCliTests,
        # Tier C Phase 1 — negative-results-logger
        NegResInitTests,
        NegResAnalyzeTests,
        NegResShareTests,
        NegResStatusListTests,
        NegResIntegrationTests,
        # Tier C Phase 1 — dataset-agent
        DatasetRegisterTests,
        DatasetHashTests,
        DatasetVersionTests,
        DatasetListStatusTests,
        # Tier C Phase 1 — credit-tracker
        CreditAssignTests,
        CreditUnassignTests,
        CreditAuditTests,
        CreditStatementTests,
        CreditRolesListTests,
        CreditListTests,
        # Tier C Phase 1 — reading-pace-analytics
        ReadingPaceVelocityTests,
        ReadingPaceBacklogTests,
        ReadingPaceTrendTests,
        ReadingPaceSummaryTests,
        ReadingPaceReadOnlyTests,
        # Tier C Phase 1 — slide-draft
        SlideOutlineTests,
        SlideMdBuildTests,
        SlideRenderTests,
        SlideListCleanTests,
        SlideFormatsListTests,
        # Tier C Phase 1 — reviewer-assistant
        ReviewerInitTests,
        ReviewerAddCommentTests,
        ReviewerRecommendationTests,
        ReviewerExportTests,
        ReviewerStatusTests,
        ReviewerIdStabilityTests,
        # Tier C Phase 2 — citation-alerts
        CitationAlertsAddRemoveTests,
        CitationAlertsListTrackedTests,
        CitationAlertsListCheckTests,
        CitationAlertsPersistTests,
        CitationAlertsDigestTests,
        CitationAlertsStatusTests,
        # Tier C Phase 2 — field-trends-analyzer
        FieldTrendsConceptsTests,
        FieldTrendsPapersTests,
        FieldTrendsAuthorsTests,
        FieldTrendsMomentumTests,
        FieldTrendsSummaryTests,
        FieldTrendsReadOnlyTests,
        # Tier C Phase 2 — dmp/ethics/regrep/zenodo
        DmpGeneratorTests,
        EthicsIrbTests,
        RegisteredReportsTests,
        ZenodoPrepareTests,
        # Tier C Phase 3A — experiment-design
        ExpDesignInitTests,
        ExpDesignVariableTests,
        ExpDesignMetricTests,
        ExpDesignPreregisterTests,
        ExpDesignStatusListTests,
        # Tier C Phase 3D — project-manager
        PMInitListTests,
        PMActiveMarkerTests,
        PMArchiveTests,
        PMStatusTests,
        PMHelperTests,
        # Tier C Phase 3E — meta-research
        MetaTrajectoryTests,
        MetaConceptsTests,
        MetaProductivityTests,
        MetaSummaryTests,
        MetaReadOnlyTests,
        # Tier C Phase 3B — reproducibility-mcp (Docker sandbox)
        SandboxHelperTests,
        SandboxBuildArgsTests,
        SandboxCheckCommandTests,
        SandboxRunRequiresDaemonTests,
        SandboxDiagnoseTests,
        SandboxValidateWorkspaceTests,
        SandboxCmdRunValidationTests,
        SandboxWorkspaceLockTests,
        SandboxAuditTests,
        # Tier C Phase 3C — experiment-reproduce
        ExpReproMetricExtractionTests,
        ExpReproRunStateTransitionTests,
        ExpReproAnalyzeTests,
        ExpReproReproduceCheckTests,
        ExpReproStatusTests,
        # v0.53.x — Wide Research suite
        WideTaskSpecTests,
        WideDecomposeTests,
        WideCostEstimateTests,
        WideWorkspaceTests,
        WideCollectResultsTests,
        WideTaskTypeDefaultsTests,
        WideCLITests,
        WideGate23ObserveTests,
        WideSynthesisTests,
        WideSynthesizeCLITests,
        WideToDeepHandoffTests,
        WideEdgeCaseTests,
        WideHandoffEdgeCaseTests,
        WideV537Tests,
        # v0.53.6 — mode auto-selector
        ModeItemDrivenTests,
        ModeQuestionDrivenTests,
        ModeExplicitOverrideTests,
        ModeConfidenceTests,
        # v0.51 — phase concurrency groups
        PhaseGroupsForTests,
        PhaseGroupsBatchableTests,
        CmdNextPhaseBatchTests,
        # v0.54 — brief renderer
        BriefHypothesisCardsTests,
        BriefEvidenceTableTests,
        BriefDiscussionQuestionsTests,
        BriefRunRecoveryTests,
        # v0.55 — A5 Tier A trio
        GapAnalyzerTests,
        ContributionMapperTests,
        VenueMatchTests,
        # v0.56 — self-play debate
        SpecificityTests,
        GroundednessTests,
        ResponsivenessTests,
        FalsifiabilityTests,
        DecideVerdictTests,
        ScorePositionTests,
        DebatePromptTests,
        DebateRenderBriefTests,
        PositionSerializationTests,
        # v0.57 — DB persistence + db-notify
        MigrationV9Tests,
        DbNotifyTests,
        SkillPersistTests,
        WideResearchPersistenceTests,
        AuditQueryRecordsTests,
        # v0.58 — resolve-citation skill
        CitationResolverParserTests,
        CitationResolverScoreTests,
        CitationResolverPickBestTests,
        CitationResolverCLITests,
        # v0.59 — graph-viz mermaid renderer
        RenderMermaidTests,
        GraphVizSubgraphTests,
        GraphVizCliTests,
        # v0.60 — writing-style venue overlays
        VenueOverlayRegistryTests,
        VenueOverlayVoiceTests,
        VenueOverlayTenseTests,
        VenueOverlayPronounTests,
        VenueOverlayHedgeTests,
        VenueOverlayEdgeCaseTests,
        VenueOverlayCliTests,
        # v0.61 — calibration set tooling
        CalibrationCaseTests,
        CalibrationSlugifyTests,
        CalibrationAddRemoveTests,
        CalibrationPersistenceTests,
        CalibrationRenderSummaryTests,
        CalibrationCoverageCheckTests,
        CalibrationCliSmokeTests,
        # Integration + regression
        ResearchFlowIntegrationTests,
        CrossSkillArtifactContractTests,
        SchemaRegressionTests,
        CompilationMetaTests,
        ConfigValidationTests,
        LayoutRegressionTests,
    )
    sys.exit(failures)
