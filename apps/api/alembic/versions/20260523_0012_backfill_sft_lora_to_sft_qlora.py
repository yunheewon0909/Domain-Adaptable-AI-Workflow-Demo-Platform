"""backfill sft_lora training_method to sft_qlora

Revision ID: 20260523_0012
Revises: 20260417_0011
Create Date: 2026-05-23 12:00:00

The Mac-native MLX transition removed the local_peft/sft_lora training path
in favour of mlx_qlora/sft_qlora. Historical ft_training_jobs rows recorded
training_method='sft_lora' can no longer be completed by the trainer, and
they would also skip the locked-dataset guard in complete_training_job().
This migration rewrites the legacy value so any retried row goes through
the supported MLX path.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260523_0012"
down_revision: Union[str, Sequence[str], None] = "20260417_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE ft_training_jobs SET training_method = 'sft_qlora' "
            "WHERE training_method = 'sft_lora'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE ft_training_jobs SET trainer_backend = 'mlx_qlora' "
            "WHERE trainer_backend = 'local_peft'"
        )
    )


def downgrade() -> None:
    # No-op: legacy names are intentionally retired.
    pass
