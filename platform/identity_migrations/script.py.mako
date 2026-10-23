"""${message}"""
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = None
depends_on = None


def upgrade():
    from alembic import op


def downgrade():
    from alembic import op
