"""add updated_at to ft_training_jobs and ft_model_artifacts

Revision ID: b4aadc4ac8f6
Revises: 20260523_0014
Create Date: 2026-05-25 20:43:57.517870
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4aadc4ac8f6'
down_revision: Union[str, Sequence[str], None] = '20260523_0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ft_model_artifacts', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False))
    op.add_column('ft_training_jobs', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False))


def downgrade() -> None:
    op.drop_column('ft_training_jobs', 'updated_at')
    op.drop_column('ft_model_artifacts', 'updated_at')
