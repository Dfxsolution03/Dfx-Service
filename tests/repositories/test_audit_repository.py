"""
JROS Repository Tests — AuditRepository (read side, Module 14)
===================================================================

Covers:
  - list_logs (pagination, filters: tenant_id/actor_role/target_entity/action/date range, ordering)

Does not touch create_log's existing behavior/tests.
"""

import uuid
from datetime import date, timedelta
from app.repositories.audit_repository import AuditRepository


async def _make_log(db_session, tenant_id, actor_role="Admin", target_entity="payments", action="PAYMENT_UPDATE"):
    log = await AuditRepository.create_log(
        db_session,
        tenant_id=tenant_id,
        actor_user_id=f"usr_test_{uuid.uuid4().hex[:8]}",
        actor_name="Test Actor",
        actor_role=actor_role,
        action=action,
        target_entity=target_entity,
        target_id=f"tgt_{uuid.uuid4().hex[:8]}",
        before_state={"a": 1},
        after_state={"a": 2},
    )
    await db_session.commit()
    return log


class TestListLogsPagination:

    async def test_returns_matching_count_and_page(self, db_session, test_tenant):
        for _ in range(3):
            await _make_log(db_session, test_tenant.id)

        logs, total = await AuditRepository.list_logs(
            db_session, tenant_id=test_tenant.id, actor_role=None, target_entity=None,
            action=None, date_from=None, date_to=None, page=1, page_size=2,
        )
        assert total == 3
        assert len(logs) == 2

    async def test_second_page_returns_remainder(self, db_session, test_tenant):
        for _ in range(3):
            await _make_log(db_session, test_tenant.id)

        logs, total = await AuditRepository.list_logs(
            db_session, tenant_id=test_tenant.id, actor_role=None, target_entity=None,
            action=None, date_from=None, date_to=None, page=2, page_size=2,
        )
        assert total == 3
        assert len(logs) == 1

    async def test_orders_newest_first(self, db_session, test_tenant):
        first = await _make_log(db_session, test_tenant.id)
        second = await _make_log(db_session, test_tenant.id)

        logs, _ = await AuditRepository.list_logs(
            db_session, tenant_id=test_tenant.id, actor_role=None, target_entity=None,
            action=None, date_from=None, date_to=None, page=1, page_size=10,
        )
        ids = [l.id for l in logs]
        assert ids.index(second.id) < ids.index(first.id)


class TestListLogsFilters:

    async def test_filters_by_target_entity(self, db_session, test_tenant):
        await _make_log(db_session, test_tenant.id, target_entity="payments")
        await _make_log(db_session, test_tenant.id, target_entity="kyc_records")

        logs, total = await AuditRepository.list_logs(
            db_session, tenant_id=test_tenant.id, actor_role=None, target_entity="kyc_records",
            action=None, date_from=None, date_to=None, page=1, page_size=10,
        )
        assert total == 1
        assert logs[0].target_entity == "kyc_records"

    async def test_filters_by_actor_role(self, db_session, test_tenant):
        await _make_log(db_session, test_tenant.id, actor_role="Admin")
        await _make_log(db_session, test_tenant.id, actor_role="Customer")

        logs, total = await AuditRepository.list_logs(
            db_session, tenant_id=test_tenant.id, actor_role="Customer", target_entity=None,
            action=None, date_from=None, date_to=None, page=1, page_size=10,
        )
        assert total == 1
        assert logs[0].actor_role == "Customer"

    async def test_filters_by_action(self, db_session, test_tenant):
        await _make_log(db_session, test_tenant.id, action="PAYMENT_UPDATE")
        await _make_log(db_session, test_tenant.id, action="KYC_APPROVE")

        logs, total = await AuditRepository.list_logs(
            db_session, tenant_id=test_tenant.id, actor_role=None, target_entity=None,
            action="KYC_APPROVE", date_from=None, date_to=None, page=1, page_size=10,
        )
        assert total == 1
        assert logs[0].action == "KYC_APPROVE"

    async def test_filters_by_tenant_id_excludes_other_tenants(self, db_session, test_tenant):
        await _make_log(db_session, test_tenant.id)
        # tenant_id is a real FK — None is the only guaranteed-valid "not
        # this tenant" value without provisioning a second Tenant row.
        await _make_log(db_session, None)

        logs, total = await AuditRepository.list_logs(
            db_session, tenant_id=test_tenant.id, actor_role=None, target_entity=None,
            action=None, date_from=None, date_to=None, page=1, page_size=10,
        )
        assert total == 1
        assert all(l.tenant_id == test_tenant.id for l in logs)

    async def test_filters_by_date_range_excludes_out_of_range(self, db_session, test_tenant):
        await _make_log(db_session, test_tenant.id)

        far_future_from = date.today() + timedelta(days=10)
        far_future_to = date.today() + timedelta(days=20)

        logs, total = await AuditRepository.list_logs(
            db_session, tenant_id=test_tenant.id, actor_role=None, target_entity=None,
            action=None, date_from=far_future_from, date_to=far_future_to, page=1, page_size=10,
        )
        assert total == 0

    async def test_date_range_includes_today(self, db_session, test_tenant):
        await _make_log(db_session, test_tenant.id)
        today = date.today()

        logs, total = await AuditRepository.list_logs(
            db_session, tenant_id=test_tenant.id, actor_role=None, target_entity=None,
            action=None, date_from=today, date_to=today, page=1, page_size=10,
        )
        assert total == 1

    async def test_no_filters_returns_all_for_tenant(self, db_session, test_tenant):
        for _ in range(4):
            await _make_log(db_session, test_tenant.id)

        logs, total = await AuditRepository.list_logs(
            db_session, tenant_id=test_tenant.id, actor_role=None, target_entity=None,
            action=None, date_from=None, date_to=None, page=1, page_size=10,
        )
        assert total == 4
        assert len(logs) == 4
