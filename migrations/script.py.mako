"""Alembic migration template."""
${imports}

${upgrades if upgrades else "pass"}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
