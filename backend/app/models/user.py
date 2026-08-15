import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Links to Supabase's auth.users.id (the JWT `sub` claim).
    supabase_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    """Soft-deactivation - e.g. an admin deactivating a teacher account. Does not
    revoke Supabase Auth login (out of scope for a DB column); routers/services
    that assemble scheduling-eligible teacher lists must filter on this."""

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    school_id: Mapped[int | None] = mapped_column(ForeignKey("schools.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    role: Mapped["Role"] = relationship(back_populates="users")
    school: Mapped["School | None"] = relationship(back_populates="users")
