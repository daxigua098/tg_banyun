from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_topbar_removes_runtime_action_buttons() -> None:
    source = (PROJECT_ROOT / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    start = source.index('<div class="actions">')
    end = source.index("</div>", start)
    topbar_actions = source[start:end]

    assert "刷新" in topbar_actions
    assert "退出登录" in topbar_actions
    for label in ("暂停", "恢复", "停止全部", "重试失败"):
        assert label not in topbar_actions


def test_frontend_retry_failed_helpers_are_removed() -> None:
    app_source = (PROJECT_ROOT / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    api_source = (PROJECT_ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")

    assert "retryFailed" not in app_source
    assert "retryFailed" not in api_source
    assert "function retry(" not in app_source


def test_route_builder_has_clear_source_and_target_labels() -> None:
    source = (PROJECT_ROOT / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")

    assert 'class="route-builder"' in source
    assert 'class="route-endpoint-label source">搬运源<' in source
    assert 'class="route-endpoint-label target">接收目标<' in source
    assert '批量建立搭配关系' in source
    assert '请选择一个或多个搬运源' in source
    assert '请选择一个或多个接收目标' in source
    assert 'routePreviewCount' in source
    assert 'sourceName(group.source_id)' in source
    assert 'targetName(row.target_id)' in source


def test_source_page_displays_all_bound_targets() -> None:
    source = (PROJECT_ROOT / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "routesForSource(row.id)" in source
    assert "routesForSource(syncForm.sourceId)" in source
    assert "该源还没有建立接收目标" in source
    assert "该搬运源还没有启用的接收目标" in source


def test_source_and_target_pages_offer_permission_checks() -> None:
    app_source = (PROJECT_ROOT / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    api_source = (PROJECT_ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")

    assert "checkSourceAccess(row)" in app_source
    assert "checkTargetAccess(row)" in app_source
    assert "权限检测结果" in app_source
    assert "checkAccess" in api_source
