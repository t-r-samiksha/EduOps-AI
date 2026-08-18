from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

LIBRARY_TYPES = ("book", "past_paper", "journal", "ebook")
LOAN_STATUSES = ("active", "returned", "overdue")


class LibraryItem(Base):
    """A book, academic journal, past paper, or digital resource in the library catalog."""

    __tablename__ = "library_items"
    __table_args__ = (
        Index("ix_library_items_school_cat", "school_id", "category"),
        Index("ix_library_items_type", "type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str] = mapped_column(String(100), default="General", nullable=False)
    type: Mapped[str] = mapped_column(String(50), default="book", nullable=False)  # book, past_paper, journal, ebook

    available_copies: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    total_copies: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    school: Mapped["School"] = relationship()
    loans: Mapped[list["LibraryLoan"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", order_by="LibraryLoan.issued_at.desc()"
    )


class LibraryLoan(Base):
    """A borrowed book/item loan record for a student."""

    __tablename__ = "library_loans"
    __table_args__ = (
        Index("ix_library_loans_student_status", "student_id", "status"),
        Index("ix_library_loans_item", "library_item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    library_item_id: Mapped[int] = mapped_column(ForeignKey("library_items.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    issued_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)  # active, returned, overdue

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    item: Mapped["LibraryItem"] = relationship(back_populates="loans")
    student: Mapped["User"] = relationship(foreign_keys=[student_id])
    issuer: Mapped["User | None"] = relationship(foreign_keys=[issued_by])
