import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

# Tải các biến bảo mật từ file.env vào hệ thống
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Khởi tạo engine kết nối bất đồng bộ tới PostgreSQL
# Sử dụng poolclass=NullPool là bắt buộc khi đi qua cổng 6543 của Supabase
engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=True)

# Tạo phiên làm việc (session) để thực thi truy vấn dữ liệu
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

Base = declarative_base()

# Hàm dependency để các endpoint API sử dụng khi cần chọc vào database
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session