from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.future import select

from database import get_db
import models
import schemas

from pydantic import BaseModel
from security import create_access_token, verify_token, require_leader

# Khởi tạo ứng dụng FastAPI
app = FastAPI(
    title="API Chia Ca Nấu Cơm",
    description="Hệ thống tự động so khớp lịch học và gợi ý người nấu cơm.",
    version="1.0.0"
)

@app.get("/")
async def read_root():
    return {"message": "Server FastAPI đã chạy thành công!"}

@app.get("/test-db")
async def test_database_connection(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("SELECT version();"))
        db_version = result.scalar()
        return {"status": "Kết nối Supabase thành công! 🎉", "postgresql_version": db_version}
    except Exception as e:
        return {"status": "Kết nối thất bại ❌", "error": str(e)}

# --- API MỚI: TẠO TÀI KHOẢN NGƯỜI DÙNG ---
@app.post("/users/", response_model=schemas.UserResponse)
async def create_user(user: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    # 1. Kiểm tra xem telegram_chat_id đã tồn tại chưa (nếu có nhập)
    if user.telegram_chat_id:
        query = select(models.User).where(models.User.telegram_chat_id == user.telegram_chat_id)
        result = await db.execute(query)
        existing_user = result.scalars().first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Telegram Chat ID này đã được đăng ký!")

    # 2. Tạo đối tượng User mới để lưu vào Database
    new_user = models.User(
        full_name=user.full_name,
        telegram_chat_id=user.telegram_chat_id,
        role_type=user.role_type.value
    )
    
    # 3. Thực thi lưu vào Supabase
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user) # Lấy dữ liệu mới nhất (bao gồm cả user_id vừa được sinh ra)
    
    return new_user

# --- SCHEMA CHO LOGIN ---
class LoginRequest(BaseModel):
    user_id: str  # Trong thực tế nhà ở chung, ta cho phép login nhanh bằng ID

# --- API ĐĂNG NHẬP (LẤY TOKEN) ---
@app.post("/login/")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Tìm user trong database
    query = select(models.User).where(models.User.user_id == req.user_id)
    result = await db.execute(query)
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng này trong hệ thống")
        
    # Tạo token chứa ID và Role của người đó
    token_data = {"sub": str(user.user_id), "role": user.role_type}
    token = create_access_token(token_data)
    
    return {"access_token": token, "token_type": "bearer", "role": user.role_type}

# --- API TEST: AI CŨNG XEM ĐƯỢC (Ví dụ: Xem lịch nấu cơm) ---
@app.get("/test-view-only/")
async def view_only_action(user_data: dict = Depends(verify_token)):
    return {
        "message": "Thành công! Bạn đang xem dữ liệu chung của ngôi nhà.", 
        "thong_tin_cua_ban": user_data
    }

# --- API TEST: CHỈ LEADER MỚI ĐƯỢC VÀO (Ví dụ: Chốt ca nấu) ---
@app.post("/test-leader-only/")
async def leader_only_action(user_data: dict = Depends(require_leader)):
    return {
        "message": "Chào Trưởng nhà! Bạn đã truy cập thành công khu vực quản trị.", 
        "thong_tin_cua_ban": user_data
    }