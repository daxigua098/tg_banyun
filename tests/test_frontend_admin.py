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


def test_content_settings_offer_edit_and_delete_sync_toggles() -> None:
    app_source = (PROJECT_ROOT / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    api_source = (PROJECT_ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")

    assert "syncSettings.edits" in app_source
    assert "syncSettings.deletes" in app_source
    assert "源消息编辑同步" in app_source
    assert "源消息删除同步" in app_source
    assert "getSyncBehavior" in api_source
    assert "updateSyncBehavior" in api_source


def test_source_page_offers_delete_action() -> None:
    app_source = (PROJECT_ROOT / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    api_source = (PROJECT_ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")

    assert "removeSource(row)" in app_source
    assert "deleteSource(row.id)" in app_source
    assert "export const deleteSource" in api_source


def test_route_page_offers_edit_action() -> None:
    app_source = (PROJECT_ROOT / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    api_source = (PROJECT_ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")

    assert "openRouteEditor(row)" in app_source
    assert "saveRouteEditor" in app_source
    assert "编辑路由搭配" in app_source
    assert "export const updateRoute" in api_source


def test_user_management_offers_edit_with_password_and_delete() -> None:
    app_source = (PROJECT_ROOT / "frontend" / "src" / "App.vue").read_text(encoding="utf-8")
    api_source = (PROJECT_ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")

    assert "openUserEditor(row)" in app_source
    assert "saveUserEditor" in app_source
    assert "removeUser(row)" in app_source
    assert "留空则不修改密码" in app_source
    assert "export const deleteUser" in api_source
