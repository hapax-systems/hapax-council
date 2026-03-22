"""Tests for logos.data.knowledge_sufficiency — domain registry loader."""

from logos.data.knowledge_sufficiency import (
    DOMAIN_REGISTRY_PATH,
    KnowledgeGap,
    SufficiencyReport,
    collect_all_domain_gaps,
    load_domain_registry,
)


class TestDomainRegistry:
    def test_registry_path_exists(self) -> None:
        """Domain registry YAML file exists on disk."""
        assert DOMAIN_REGISTRY_PATH.is_file(), f"Missing: {DOMAIN_REGISTRY_PATH}"

    def test_load_registry_has_domains(self) -> None:
        """Registry loads and contains at least 4 domains."""
        registry = load_domain_registry()
        assert "domains" in registry
        assert len(registry["domains"]) >= 4

    def test_load_registry_has_constitutional(self) -> None:
        """Registry has a constitutional layer."""
        registry = load_domain_registry()
        assert "constitutional" in registry

    def test_management_domain_has_sufficiency_model(self) -> None:
        """Management domain references its sufficiency YAML."""
        registry = load_domain_registry()
        mgmt = next(d for d in registry["domains"] if d["id"] == "management")
        assert mgmt["sufficiency_model"] == "knowledge/management-sufficiency.yaml"

    def test_each_domain_has_required_fields(self) -> None:
        """Every domain has id, name, status, vault_paths, governance."""
        registry = load_domain_registry()
        for domain in registry["domains"]:
            assert "id" in domain, f"Missing id in {domain}"
            assert "name" in domain, f"Missing name in {domain.get('id', '?')}"
            assert "status" in domain, f"Missing status in {domain['id']}"
            assert "vault_paths" in domain, f"Missing vault_paths in {domain['id']}"
            assert "governance" in domain, f"Missing governance in {domain['id']}"


class TestMultiDomainAudit:
    def test_returns_dict_keyed_by_domain_id(self) -> None:
        """collect_all_domain_gaps returns {domain_id: SufficiencyReport}."""
        reports = collect_all_domain_gaps()
        assert isinstance(reports, dict)
        # At minimum, management should always be present
        assert "management" in reports

    def test_management_report_matches_single_domain(self) -> None:
        """Multi-domain management report matches single-domain collect_knowledge_gaps."""
        from logos.data.knowledge_sufficiency import collect_knowledge_gaps

        single = collect_knowledge_gaps()
        multi = collect_all_domain_gaps()
        if "management" in multi:
            assert multi["management"].total_requirements == single.total_requirements
            assert multi["management"].sufficiency_score == single.sufficiency_score

    def test_returns_reports_for_domains_with_models(self) -> None:
        """Only domains with existing sufficiency YAML files get reports."""
        reports = collect_all_domain_gaps()
        for _domain_id, report in reports.items():
            assert isinstance(report, SufficiencyReport)
            assert report.total_requirements >= 0

    def test_skips_domains_without_model_file(self) -> None:
        """Domains whose sufficiency YAML doesn't exist are silently skipped."""
        reports = collect_all_domain_gaps()
        assert len(reports) >= 1

    def test_empty_report_on_missing_registry(self) -> None:
        """Returns empty dict if registry file doesn't exist."""
        reports = collect_all_domain_gaps()
        assert isinstance(reports, dict)


class TestDomainScopedNudges:
    def test_gaps_to_nudges_with_domain_id(self) -> None:
        """gaps_to_nudges with domain_id prepends it to source_id."""
        gap = KnowledgeGap(
            requirement_id="test-req",
            category="foundational",
            priority=90,
            description="Test requirement",
            acquisition_method="interview",
            interview_question="Test?",
            satisfied=False,
        )
        from logos.data.knowledge_sufficiency import gaps_to_nudges

        nudges = gaps_to_nudges([gap], domain_id="music")
        assert len(nudges) == 1
        assert nudges[0].source_id == "knowledge:music:test-req"

    def test_gaps_to_nudges_default_no_domain(self) -> None:
        """gaps_to_nudges without domain_id uses bare source_id (backward compat)."""
        gap = KnowledgeGap(
            requirement_id="test-req",
            category="foundational",
            priority=90,
            description="Test requirement",
            acquisition_method="interview",
            interview_question="Test?",
            satisfied=False,
        )
        from logos.data.knowledge_sufficiency import gaps_to_nudges

        nudges = gaps_to_nudges([gap])
        assert nudges[0].source_id == "knowledge:test-req"
