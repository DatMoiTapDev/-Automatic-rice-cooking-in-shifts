from pydantic import BaseModel, ConfigDict
from typing import Optional
from uuid import UUID
from enum import Enum
from datetime import date, datetime

# Quy định các quyền trong hệ thống
class RoleType(str, Enum):
    leader = "leader"
    member = "member"

# Các phiên nấu ăn trong tuần
class MealType(str, Enum):
    sang = "Sáng"
    trua = "Trưa"
    toi = "Tối"

# Schema dùng để nhận dữ liệu từ client gửi lên khi tạo User
class UserCreate(BaseModel):
    full_name: str
    telegram_chat_id: Optional[str] = None
    role_type: RoleType = RoleType.member

# Schema dùng để trả dữ liệu từ Database về cho client
class UserResponse(BaseModel):
    user_id: UUID
    full_name: str
    telegram_chat_id: Optional[str]
    role_type: str
    is_active: bool

    # Chuyển đổi dữ liệu từ ORM (SQLAlchemy) sang JSON
    model_config = ConfigDict(from_attributes=True)