import uuid
from sqlalchemy import Column, Integer, String, Boolean, Date, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from database import Base

class User(Base):
    __tablename__ = "users"
    
    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String(255), nullable=False)
    telegram_chat_id = Column(String(100), unique=True)
    role_type = Column(String(50), default="member")  
    is_active = Column(Boolean, default=True)

class Schedule(Base):
    __tablename__ = "schedules"
    
    schedule_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"))
    event_summary = Column(String(255))
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)

class CookingShift(Base):
    __tablename__ = "cookingshifts"
    
    shift_id = Column(Integer, primary_key=True, autoincrement=True)
    shift_date = Column(Date, nullable=False)
    meal_type = Column(String(50))  
    required_start_time = Column(DateTime(timezone=True), nullable=False)
    required_end_time = Column(DateTime(timezone=True), nullable=False)

class ShiftAssignment(Base):
    __tablename__ = "shiftassignments"
    
    assignment_id = Column(Integer, primary_key=True, autoincrement=True)
    shift_id = Column(Integer, ForeignKey("cookingshifts.shift_id", ondelete="CASCADE"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"))
    assignment_status = Column(String(50), default="Đề xuất")

class Quota(Base):
    __tablename__ = "quotas"
    
    quota_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"))
    period_month_year = Column(Date, nullable=False)
    target_shift_count = Column(Integer, default=0)
    completed_shift_count = Column(Integer, default=0)