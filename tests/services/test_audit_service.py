"""
JROS Service Tests — AuditService (Module 14)
=================================================
"""

import uuid
from app.repositories.audit_repository import AuditRepository
from app.services.audit_service import AuditService


async def _make_log(db_session, tenant_id):
    log = await AuditRepository.create_log(
        db_session,
        tenant_id=tenant_id,
        actor_user_id=f"usr_test_{uuid.uuid4().hex[:8]}",
        actor_name="Test Actor",
        actor_role="Admin",
        action="PAYMENT_UPDATE",
        target_entity="payments",
        target_id=f"tgt_{uuid.uuid4().hex[:8]}",
    )
    await db_session.commit()
    return log


class TestAuditServiceListLogs:

    async def test_pagination_math(self, db_session, test_tenant, superadmin_user):
        for _ in range(5):
            await _make_log(db_session, test_tenant.id)

        result = await AuditService.list_logs(
            db_session, superadmin_user, tenant_id=test_tenant.id, actor_role=None,
            target_entity=None, action=None, date_from=None, date_to=None, page=1, page_size=2,
        )
        assert result.pagination.total_items == 5
        assert result.pagination.total_pages == 3
        assert result.pagination.page == 1
        assert len(result.logs) == 2

    async def test_empty_result_has_zero_total_pages(self, db_session, superadmin_user):
        result = await AuditService.list_logs(
            db_session, superadmin_user, tenant_id="tnt_nonexistent_xyz", actor_role=None,
            target_entity=None, action=None, date_from=None, date_to=None, page=1, page_size=25,
        )
        assert result.pagination.total_items == 0
        assert result.pagination.total_pages == 0
        assert result.logs == []

    async def test_log_items_map_correctly(self, db_session, test_tenant, superadmin_user):
        log = await _make_log(db_session, test_tenant.id)

        result = await AuditService.list_logs(
            db_session, superadmin_user, tenant_id=test_tenant.id, actor_role=None,
            target_entity=None, action=None, date_from=None, date_to=None, page=1, page_size=25,
        )
        found = next(l for l in result.logs if l.id == log.id)
        assert found.actor_name == "Test Actor"
        assert found.action == "PAYMENT_UPDATE"
        assert found.target_entity == "payments"
