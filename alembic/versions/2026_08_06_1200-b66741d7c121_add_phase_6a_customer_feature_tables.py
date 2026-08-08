"""add phase 6a customer feature tables

Revision ID: b66741d7c121
Revises: 7a63facd02af
Create Date: 2026-08-06 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b66741d7c121'
down_revision: Union[str, None] = '7a63facd02af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Phase 6A / Module 31 — Customer Support System, Wishlist, KYC Documents ###

    # -- support_tickets ---------------------------------------------------
    op.create_table(
        'support_tickets',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('ticket_number', sa.String(length=30), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('priority', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'ticket_number', name='uq_support_tickets_tenant_number'),
    )
    op.create_index(op.f('ix_support_tickets_tenant_id'), 'support_tickets', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_support_tickets_user_id'), 'support_tickets', ['user_id'], unique=False)
    op.create_index(op.f('ix_support_tickets_status'), 'support_tickets', ['status'], unique=False)

    # -- support_messages ----------------------------------------------------
    op.create_table(
        'support_messages',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('ticket_id', sa.String(length=50), nullable=False),
        sa.Column('sender_id', sa.String(length=50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['support_tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_support_messages_ticket_id'), 'support_messages', ['ticket_id'], unique=False)

    # -- faqs -----------------------------------------------------------------
    op.create_table(
        'faqs',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('question', sa.String(length=500), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_faqs_tenant_id'), 'faqs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_faqs_is_active'), 'faqs', ['is_active'], unique=False)

    # -- wishlist_items ---------------------------------------------------------
    op.create_table(
        'wishlist_items',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('product_id', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'product_id', name='uq_wishlist_user_product'),
    )
    op.create_index(op.f('ix_wishlist_items_tenant_id'), 'wishlist_items', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_wishlist_items_user_id'), 'wishlist_items', ['user_id'], unique=False)
    op.create_index(op.f('ix_wishlist_items_product_id'), 'wishlist_items', ['product_id'], unique=False)

    # -- kyc_documents ----------------------------------------------------------
    op.create_table(
        'kyc_documents',
        sa.Column('id', sa.String(length=50), nullable=False),
        sa.Column('tenant_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('document_type', sa.String(length=50), nullable=False),
        sa.Column('document_url', sa.String(length=1000), nullable=False),
        sa.Column('verification_status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_kyc_documents_tenant_id'), 'kyc_documents', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_kyc_documents_user_id'), 'kyc_documents', ['user_id'], unique=False)
    # ### end Phase 6A table creation ###


def downgrade() -> None:
    # ### Phase 6A / Module 31 — reverse order of upgrade() ###
    op.drop_index(op.f('ix_kyc_documents_user_id'), table_name='kyc_documents')
    op.drop_index(op.f('ix_kyc_documents_tenant_id'), table_name='kyc_documents')
    op.drop_table('kyc_documents')

    op.drop_index(op.f('ix_wishlist_items_product_id'), table_name='wishlist_items')
    op.drop_index(op.f('ix_wishlist_items_user_id'), table_name='wishlist_items')
    op.drop_index(op.f('ix_wishlist_items_tenant_id'), table_name='wishlist_items')
    op.drop_table('wishlist_items')

    op.drop_index(op.f('ix_faqs_is_active'), table_name='faqs')
    op.drop_index(op.f('ix_faqs_tenant_id'), table_name='faqs')
    op.drop_table('faqs')

    op.drop_index(op.f('ix_support_messages_ticket_id'), table_name='support_messages')
    op.drop_table('support_messages')

    op.drop_index(op.f('ix_support_tickets_status'), table_name='support_tickets')
    op.drop_index(op.f('ix_support_tickets_user_id'), table_name='support_tickets')
    op.drop_index(op.f('ix_support_tickets_tenant_id'), table_name='support_tickets')
    op.drop_table('support_tickets')
    # ### end Phase 6A table drop ###
