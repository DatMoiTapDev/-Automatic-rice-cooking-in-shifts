from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.future import select

from database import get_db #lớp logic
import models
import schemas

from pydantic import BaseModel #lớp bảo mật
from security import create_access_token, verify_token, require_leader

from icalendar import Calendar #lớp lịch ứng dụng
from datetime import datetime
import easyocr #Đọc file ảnh
import re

import numpy as np #xử lý bytes thành mảng
import cv2 #decode thành ảnh
from fastapi import UploadFile, File#Upload File

import httpx
import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

from datetime import timedelta, datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel
tz_vn = ZoneInfo("Asia/Ho_Chi_Minh") #Vì FastAPI ưu tiên giờ quốc tế
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
            raise HTTPException(status_code=400, detail="Số điện thoại này đã được đăng ký!")

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
    user_id: str  # Khi tạo xong tài khoản sẽ được cấp 1 user id bất kì, sử dụng để login nhanh mà không cần các bước xác thực rườm rà

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
        "message": "Chào Trưởng nhà! Bạn đã xác thực thành công.", 
        "thong_tin_cua_ban": user_data
    }

# --- API TẢI FILE LỊCH HỌC (.ICS VÀ ẢNH.JPG,.PNG) ---
@app.post("/upload-schedule/")
async def upload_schedule(
    user_id: str, 
    file: UploadFile = File(...), 
    db: AsyncSession = Depends(get_db)
):
    content = await file.read() # Đọc file dưới dạng byte
    schedules_to_add = []
    reader = easyocr.Reader(['vi', 'en']) 
    
    try:
        filename = file.filename.lower()

        # TRƯỜNG HỢP 1: XỬ LÝ FILE.ICS
        if filename.endswith('.ics'):
            cal = Calendar.from_ical(content)
            for component in cal.walk():
                if component.name == "VEVENT":
                    summary = str(component.get('summary'))
                    start_time = component.get('dtstart').dt
                    end_time = component.get('dtend').dt
                    
                    schedules_to_add.append(models.Schedule(
                        user_id=user_id, event_summary=summary,
                        start_time=start_time, end_time=end_time
                    ))

        # TRƯỜNG HỢP 2: XỬ LÝ FILE ẢNH BẰNG AI (EASYOCR)
        elif filename.endswith(('.png', '.jpg', '.jpeg')):

            # 🔥 FIX QUAN TRỌNG: convert bytes -> image
            nparr = np.frombuffer(content, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                raise HTTPException(status_code=400, detail="Không đọc được ảnh")

            results = reader.readtext(img, detail=0)
            text_data = " ".join(results)
            
            # DEBUG
            print("OCR TEXT:", text_data)
            
            # 🔥 Regex mạnh hơn
            time_pattern = r'(\d{1,2}[:\.]\d{2})\s*(?:-|đến|den)\s*(\d{1,2}[:\.]\d{2})'
            matches = re.finditer(time_pattern, text_data)
            
            today = datetime.now().date()

            for match in matches:
                start_str = match.group(1).replace('.', ':')
                end_str = match.group(2).replace('.', ':')
                
                try:
                    start_time = datetime.strptime(f"{today} {start_str}", "%Y-%m-%d %H:%M")
                    end_time = datetime.strptime(f"{today} {end_str}", "%Y-%m-%d %H:%M")
                except:
                    continue
                
                schedules_to_add.append(models.Schedule(
                    user_id=user_id,
                    event_summary=f"Lịch từ ảnh {start_str}-{end_str}",
                    start_time=start_time,
                    end_time=end_time
                ))
                
            if not schedules_to_add:
                return {"message": "AI đã đọc được chữ nhưng không tìm thấy khung giờ (HH:MM - HH:MM) nào trong ảnh!"}

        # TRƯỜNG HỢP 3: FILE RÁC
        else:
            raise HTTPException(status_code=400, detail="Vui lòng tải lên file.ics,.jpg hoặc.png")
        
        # Lưu vào Database
        if schedules_to_add:
            db.add_all(schedules_to_add)
            await db.commit()
            
        return {
            "message": "Phân tích lịch học thành công! 🎉",
            "tong_so_su_kien": len(schedules_to_add),
            "loai_file": "Ảnh (OCR)" if filename.endswith(('.png', '.jpg', '.jpeg')) else "File iCalendar"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Có lỗi xảy ra khi đọc file: {str(e)}")
    
from datetime import timedelta, datetime
from pydantic import BaseModel

# Schema cho API tạo lịch hàng loạt
class GenerateShiftsRequest(BaseModel):
    start_date: str  # Định dạng YYYY-MM-DD
    days: int = 7    # Số ngày muốn tạo lịch (mặc định 1 tuần)

# --- 1. API TỰ ĐỘNG TẠO CA NẤU TRỐNG (CHỈ LEADER) ---
@app.post("/shifts/generate")
async def generate_shifts(
    req: GenerateShiftsRequest,
    db: AsyncSession = Depends(get_db),
    leader_data: dict = Depends(require_leader)
):
    start_date = datetime.strptime(req.start_date, "%Y-%m-%d").date()
    shifts_to_add = []
    
    for i in range(req.days):
        current_date = start_date + timedelta(days=i)
        
        # Ca Sáng (05:00 - 07:0
        shifts_to_add.append(models.CookingShift(
            shift_date=current_date,
            meal_type="Sáng",
            required_start_time=datetime.combine(current_date, datetime.min.time().replace(hour=5, minute=0), tzinfo=tz_vn),
            required_end_time=datetime.combine(current_date, datetime.min.time().replace(hour=7, minute=0), tzinfo=tz_vn)
        ))
        
        # Ca Trưa (09:30 - 12:00)
        shifts_to_add.append(models.CookingShift(
            shift_date=current_date,
            meal_type="Trưa",
            required_start_time=datetime.combine(current_date, datetime.min.time().replace(hour=9, minute=30), tzinfo=tz_vn),
            required_end_time=datetime.combine(current_date, datetime.min.time().replace(hour=12, minute=0), tzinfo=tz_vn)
        ))
        
        # Ca Tối (16:30 - 19:15)
        shifts_to_add.append(models.CookingShift(
            shift_date=current_date,
            meal_type="Tối",
            required_start_time=datetime.combine(current_date, datetime.min.time().replace(hour=16, minute=30), tzinfo=tz_vn),
            required_end_time=datetime.combine(current_date, datetime.min.time().replace(hour=19, minute=15), tzinfo=tz_vn)
        ))
        
    db.add_all(shifts_to_add)
    await db.commit()
    
    return {"message": f"Đã tạo thành công {len(shifts_to_add)} ca nấu trống cho {req.days} ngày!"}


# --- 2. API XEM LỊCH NẤU CƠM TỔNG HỢP (AI CŨNG XEM ĐƯỢC) ---
@app.get("/shifts/schedule")
async def view_schedule(
    db: AsyncSession = Depends(get_db),
    user_data: dict = Depends(verify_token) 
):
    query = select(
        models.CookingShift, 
        models.ShiftAssignment, 
        models.User
    ).outerjoin(
        models.ShiftAssignment, models.CookingShift.shift_id == models.ShiftAssignment.shift_id
    ).outerjoin(
        models.User, models.ShiftAssignment.user_id == models.User.user_id
    ).order_by(models.CookingShift.shift_date, models.CookingShift.required_start_time)
    
    result = await db.execute(query)
    rows = result.all()
    
    schedule = []
    for shift, assignment, user in rows:
        # ÉP KIỂU VỀ GIỜ VIỆT NAM TRƯỚC KHI HIỂN THỊ
        start_local = shift.required_start_time.astimezone(tz_vn)
        end_local = shift.required_end_time.astimezone(tz_vn)
        
        schedule.append({
            "shift_id": shift.shift_id,
            "ngay": shift.shift_date.strftime('%Y-%m-%d'),
            "bua": shift.meal_type,
            "thoi_gian": f"{start_local.strftime('%H:%M')} - {end_local.strftime('%H:%M')}",
            "trang_thai": assignment.assignment_status if assignment else "Chưa phân người",
            "nguoi_phu_trach": user.full_name if user else "Trống"
        })
        
    return {"tong_so_ca": len(schedule), "lich_nau_com": schedule}

class AssignRequest(BaseModel):
    user_id: str # ID của Member được chọn để nấu

# --- 3. API: AI GỢI Ý NGƯỜI NẤU CƠM (BẠN ĐÃ BỊ THIẾU TRONG CODE CŨ) ---
@app.get("/shifts/{shift_id}/suggestions")
async def get_cooking_suggestions(
    shift_id: int, 
    db: AsyncSession = Depends(get_db),
    user_data: dict = Depends(require_leader) # CHỈ TRƯỞNG NHÀ MỚI ĐƯỢC XEM
):
    from sqlalchemy import and_ # Import toán tử AND để check trùng lịch
    
    # 1. Lấy thông tin ca nấu
    shift_query = select(models.CookingShift).where(models.CookingShift.shift_id == shift_id)
    result = await db.execute(shift_query)
    shift = result.scalars().first()
    
    if not shift:
        raise HTTPException(status_code=404, detail="Không tìm thấy ca nấu này!")

    # 2. Lấy tất cả các thành viên đang hoạt động trong nhà
    users_query = select(models.User).where(models.User.is_active == True)
    users_result = await db.execute(users_query)
    all_users = users_result.scalars().all()

    available_users = []
    
    # 3. Thuật toán Lọc Giao cắt
    for user in all_users:
        if shift.meal_type == "Sáng":
            available_users.append(user)
            continue 
            
        overlap_query = select(models.Schedule).where(
            and_(
                models.Schedule.user_id == user.user_id,
                models.Schedule.start_time < shift.required_end_time,
                models.Schedule.end_time > shift.required_start_time
            )
        )
        overlap_result = await db.execute(overlap_query)
        is_busy = overlap_result.scalars().first()
        
        if not is_busy:
            available_users.append(user)

    # 4. Thuật toán Tham lam (Greedy) Tối ưu Định mức
    suggestions = []
    for user in available_users:
        quota_query = select(models.Quota).where(models.Quota.user_id == user.user_id)
        quota_result = await db.execute(quota_query)
        quota = quota_result.scalars().first()
        
        target = quota.target_shift_count if (quota and quota.target_shift_count) else 0
        completed = quota.completed_shift_count if quota else 0
        priority_score = target - completed
        
        suggestions.append({
            "user_id": str(user.user_id),
            "full_name": user.full_name,
            "target": target if target > 0 else "Optional (Tùy Leader xếp)",
            "completed": completed,
            "priority_score": priority_score,
            "status": "Hoàn toàn rảnh rỗi"
        })

    # 5. Sắp xếp danh sách
    suggestions.sort(key=lambda x: x["priority_score"], reverse=True)

    return {
        "thong_tin_ca_nau": {
            "ngay": shift.shift_date,
            "bua": shift.meal_type
        },
        "so_luong_nguoi_ranh": len(suggestions),
        "danh_sach_goi_y": suggestions
    }

# --- API CHỐT CA VÀ GỬI THÔNG BÁO TỰ ĐỘNG ---
@app.post("/shifts/{shift_id}/assign")
async def assign_shift(
    shift_id: int, 
    req: AssignRequest,
    db: AsyncSession = Depends(get_db),
    leader_data: dict = Depends(require_leader) # CHỈ TRƯỞNG NHÀ MỚI ĐƯỢC CHỐT
):
    # 1. Tìm thông tin ca nấu
    shift_query = select(models.CookingShift).where(models.CookingShift.shift_id == shift_id)
    shift = (await db.execute(shift_query)).scalars().first()
    if not shift:
        raise HTTPException(status_code=404, detail="Không tìm thấy ca nấu")

    # 2. Lấy thông tin người được chọn
    user_query = select(models.User).where(models.User.user_id == req.user_id)
    assigned_user = (await db.execute(user_query)).scalars().first()
    if not assigned_user:
        raise HTTPException(status_code=404, detail="Không tìm thấy thành viên")

    # 3. Tạo bản ghi chốt lịch phân công
    assignment = models.ShiftAssignment(
        shift_id=shift_id,
        user_id=assigned_user.user_id,
        assignment_status="Đã chốt"
    )
    db.add(assignment)

    # 4. Cộng thêm 1 bữa vào "Số ca đã nấu" (Completed Quota) để AI tính toán cho lần sau
    quota_query = select(models.Quota).where(models.Quota.user_id == assigned_user.user_id)
    quota = (await db.execute(quota_query)).scalars().first()
    if quota:
        quota.completed_shift_count += 1
    else:
        new_quota = models.Quota(
            user_id=assigned_user.user_id,
            period_month_year=shift.shift_date.replace(day=1),
            target_shift_count=0,
            completed_shift_count=1
        )
        db.add(new_quota)

    # Lưu toàn bộ thay đổi vào Supabase
    await db.commit()

    return {
        "message": "Đã chốt ca thành công!",
        "nguoi_nau": assigned_user.full_name,
    }
