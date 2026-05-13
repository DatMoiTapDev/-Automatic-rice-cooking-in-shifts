import os
from datetime import datetime, timedelta
import jwt
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

# Khai báo cơ chế bảo mật Bearer Token cho Swagger UI
security = HTTPBearer()

# Hàm tạo thẻ Token khi người dùng đăng nhập
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=30) # Token có hạn 30 ngày 
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Hàm kiểm tra Token xem có hợp lệ không (Dùng cho Member và Leader)
def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token đã hết hạn. Vui lòng đăng nhập lại.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token không hợp lệ hoặc đã bị thay đổi.")

# Hàm lọc quyền: CHỈ CHO PHÉP LEADER ĐI QUA
def require_leader(payload: dict = Security(verify_token)):
    if payload.get("role")!= "leader":
        raise HTTPException(status_code=403, detail="Cảnh báo: Chỉ Trưởng nhà (Leader) mới có quyền thực hiện hành động này!")
    return payload