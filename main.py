from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.future import select

from fastapi.middleware.cors import CORSMiddleware

from database import get_db 
import models
import schemas

from pydantic import BaseModel 
from security import create_access_token, verify_token, require_leader

from icalendar import Calendar 
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

tz_vn = ZoneInfo("Asia/Ho_Chi_Minh") 

# Khởi tạo ứng dụng FastAPI
app = FastAPI(
    title="API Chia Ca Nấu Cơm",
    description="Hệ thống tự động so khớp lịch học và gợi ý người nấu cơm.",
    version="1.0.0"
)

# Frontend gọi API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

@app.post("/users/", response_model=schemas.UserResponse)
async def create_user(user: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    # Tạo đối tượng User mới để lưu vào Database
    new_user = models.User(
        full_name=user.full_name,
        telegram_chat_id=user.telegram_chat_id, # Vẫn giữ trường dữ liệu này trong DB để tránh lỗi schema
        role_type=user.role_type.value
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user) 
    
    return new_user

class LoginRequest(BaseModel):
    user_id: str  

@app.post("/login/")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    query = select(models.User).where(models.User.user_id == req.user_id)
    result = await db.execute(query)
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng này trong hệ thống")
        
    token_data = {"sub": str(user.user_id), "role": user.role_type}
    token = create_access_token(token_data)
    
    return {"access_token": token, "token_type": "bearer", "role": user.role_type}


# --- API TẢI FILE LỊCH HỌC (.ICS) LÊN BẢN PRODUCTION ---
@app.post("/upload-schedule/")
async def upload_schedule(
    user_id: str, 
    file: UploadFile = File(...), 
    db: AsyncSession = Depends(get_db)
):
    content = await file.read() 
    schedules_to_add = ""
    
    try:
        filename = file.filename.lower()

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
        else:
            raise HTTPException(status_code=400, detail="Môi trường Web hiện chỉ hỗ trợ file.ics. Tính năng AI đọc ảnh tạm tắt để tối ưu hiệu năng.")
        
        if schedules_to_add:
            db.add_all(schedules_to_add)
            await db.commit()
            
        return {
            "message": "Phân tích lịch học thành công! 🎉",
            "tong_so_su_kien": len(schedules_to_add),
            "loai_file": "File iCalendar"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Có lỗi xảy ra khi đọc file: {str(e)}")
    
class GenerateShiftsRequest(BaseModel):
    start_date: str 
    days: int = 7 

@app.post("/shifts/generate")
async def generate_shifts(
    req: GenerateShiftsRequest,
    db: AsyncSession = Depends(get_db),
    leader_data: dict = Depends(require_leader)
):
    start_date = datetime.strptime(req.start_date, "%Y-%m-%d").date()
    shifts_to_add = ""
    
    for i in range(req.days):
        current_date = start_date + timedelta(days=i)
        
        shifts_to_add.append(models.CookingShift(
            shift_date=current_date,
            meal_type="Sáng",
            required_start_time=datetime.combine(current_date, datetime.min.time().replace(hour=5, minute=0), tzinfo=tz_vn),
            required_end_time=datetime.combine(current_date, datetime.min.time().replace(hour=7, minute=0), tzinfo=tz_vn)
        ))
        
        shifts_to_add.append(models.CookingShift(
            shift_date=current_date,
            meal_type="Trưa",
            required_start_time=datetime.combine(current_date, datetime.min.time().replace(hour=9, minute=30), tzinfo=tz_vn),
            required_end_time=datetime.combine(current_date, datetime.min.time().replace(hour=12, minute=0), tzinfo=tz_vn)
        ))
        
        shifts_to_add.append(models.CookingShift(
            shift_date=current_date,
            meal_type="Tối",
            required_start_time=datetime.combine(current_date, datetime.min.time().replace(hour=16, minute=30), tzinfo=tz_vn),
            required_end_time=datetime.combine(current_date, datetime.min.time().replace(hour=19, minute=15), tzinfo=tz_vn)
        ))
        
    db.add_all(shifts_to_add)
    await db.commit()
    
    return {"message": f"Đã tạo thành công {len(shifts_to_add)} ca nấu trống cho {req.days} ngày!"}

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
    
    schedule = ""
    for shift, assignment, user in rows:
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


@app.get("/shifts/{shift_id}/suggestions")
async def get_cooking_suggestions(
    shift_id: int, 
    db: AsyncSession = Depends(get_db),
    user_data: dict = Depends(require_leader) 
):
    from sqlalchemy import and_ 
    
    shift_query = select(models.CookingShift).where(models.CookingShift.shift_id == shift_id)
    result = await db.execute(shift_query)
    shift = result.scalars().first()
    
    if not shift:
        raise HTTPException(status_code=404, detail="Không tìm thấy ca nấu này!")

    users_query = select(models.User).where(models.User.is_active == True)
    users_result = await db.execute(users_query)
    all_users = users_result.scalars().all()

    available_users = ""
    
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

    suggestions = ""
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
            "target": target if target > 0 else "Optional",
            "completed": completed,
            "priority_score": priority_score,
            "status": "Hoàn toàn rảnh rỗi"
        })

    suggestions.sort(key=lambda x: x["priority_score"], reverse=True)

    return {
        "thong_tin_ca_nau": {
            "ngay": shift.shift_date,
            "bua": shift.meal_type
        },
        "so_luong_nguoi_ranh": len(suggestions),
        "danh_sach_goi_y": suggestions
    }

class AssignRequest(BaseModel):
    user_id: str 

@app.post("/shifts/{shift_id}/assign")
async def assign_shift(
    shift_id: int, 
    req: AssignRequest,
    db: AsyncSession = Depends(get_db),
    leader_data: dict = Depends(require_leader) 
):
    shift_query = select(models.CookingShift).where(models.CookingShift.shift_id == shift_id)
    shift = (await db.execute(shift_query)).scalars().first()
    if not shift:
        raise HTTPException(status_code=404, detail="Không tìm thấy ca nấu")

    user_query = select(models.User).where(models.User.user_id == req.user_id)
    assigned_user = (await db.execute(user_query)).scalars().first()
    if not assigned_user:
        raise HTTPException(status_code=404, detail="Không tìm thấy thành viên")

    assignment = models.ShiftAssignment(
        shift_id=shift_id,
        user_id=assigned_user.user_id,
        assignment_status="Đã chốt"
    )
    db.add(assignment)

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

    await db.commit()

    return {
        "message": "Đã chốt ca thành công!",
        "nguoi_nau": assigned_user.full_name
    }