from agents.hapax_voice.screen_models import (
    CameraConfig,
    GearObservation,
    Issue,
    ScreenAnalysis,
    WorkspaceAnalysis,
)


def test_issue_creation():
    issue = Issue(severity="error", description="pytest failure", confidence=0.9)
    assert issue.severity == "error"
    assert issue.confidence == 0.9


def test_screen_analysis_creation():
    analysis = ScreenAnalysis(
        app="Google Chrome",
        context="Viewing Pipecat docs",
        summary="User is reading documentation.",
        issues=[],
        suggestions=[],
        keywords=["pipecat", "docs"],
    )
    assert analysis.app == "Google Chrome"
    assert analysis.keywords == ["pipecat", "docs"]


def test_screen_analysis_has_errors():
    err = Issue(severity="error", description="build failed", confidence=0.95)
    warn = Issue(severity="warning", description="deprecated API", confidence=0.6)
    analysis = ScreenAnalysis(
        app="foot",
        context="Running pytest",
        summary="Test output visible.",
        issues=[err, warn],
        suggestions=[],
        keywords=["pytest"],
    )
    high_conf = [i for i in analysis.issues if i.confidence >= 0.8 and i.severity == "error"]
    assert len(high_conf) == 1
    assert high_conf[0].description == "build failed"


def test_screen_analysis_no_issues():
    analysis = ScreenAnalysis(
        app="Obsidian",
        context="Editing notes",
        summary="Writing in vault.",
        issues=[],
        suggestions=[],
        keywords=["obsidian"],
    )
    assert len(analysis.issues) == 0


def test_camera_config_defaults():
    cfg = CameraConfig(device="/dev/video0", role="operator")
    assert cfg.width == 1280
    assert cfg.height == 720
    assert cfg.input_format == "mjpeg"
    assert cfg.pixel_format is None


def test_camera_config_ir():
    cfg = CameraConfig(
        device="/dev/video2", role="ir",
        width=340, height=340,
        input_format="rawvideo", pixel_format="gray",
    )
    assert cfg.pixel_format == "gray"


def test_gear_observation():
    obs = GearObservation(
        device="MPC Live III", powered=True,
        display_content="Song mode", notes="",
    )
    assert obs.powered is True


def test_workspace_analysis_extends_screen():
    wa = WorkspaceAnalysis(
        app="foot", context="running pytest", summary="Tests passing.",
        issues=[], suggestions=[], keywords=["pytest"],
        operator_present=True, operator_activity="typing",
        operator_attention="screen", gear_state=[], workspace_change=False,
    )
    assert wa.operator_present is True
    assert wa.app == "foot"


def test_workspace_analysis_defaults():
    wa = WorkspaceAnalysis(
        app="unknown", context="", summary="",
    )
    assert wa.operator_present is None
    assert wa.operator_activity == "unknown"
    assert wa.gear_state == []
