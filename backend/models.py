from database import Base
from sqlalchemy import Integer, String, Float, ForeignKey
from sqlalchemy.orm import Mapped, relationship, mapped_column


class Professor(Base):
    __tablename__ = "professor"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str] = mapped_column(String, nullable=False)
    
class Course(Base):
    __tablename__ = "course"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str] = mapped_column(String, nullable=False)
    