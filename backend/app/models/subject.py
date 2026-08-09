from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20))

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)

    school: Mapped["School"] = relationship(back_populates="subjects")
