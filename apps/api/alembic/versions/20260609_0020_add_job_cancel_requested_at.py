"""add jobs.cancel_requested_at (cooperative job cancellation)

Records when a cancel was requested for a job. A queued job is cancelled
immediately; a running job is stopped at its runner's next cooperative
checkpoint (see services/jobs.JobControl + background_runner). Nullable, no
default, SQLite-safe.

Revision ID: 20260609_0020
Revises: 20260607_0019
Create Date: 2026-06-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260609_0020"
down_revision: Union[str, Sequence[str], None] = "20260607_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "cancel_requested_at")
