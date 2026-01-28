from fastapi import FastAPI, APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext
import jwt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from io import BytesIO

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI()
api_router = APIRouter(prefix="/api")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.environ.get("JWT_SECRET", "bluecust-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    contact_number: str
    business_name: str
    business_type: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: EmailStr
    contact_number: str
    business_name: str
    business_type: str
    is_admin: bool = False
    created_at: str

class OrderCreate(BaseModel):
    quantity: int
    sticker_text: str
    sticker_design_notes: Optional[str] = ""
    payment_mode: str

class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    user_email: str
    business_name: str
    contact_number: str
    quantity: int
    sticker_text: str
    sticker_design_notes: str
    payment_mode: str
    unit_price: int = 16
    total_amount: int
    order_date: str
    status: str = "pending"

class Supplier(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    supplier_type: str
    contact_number: str
    email: EmailStr
    address: str
    created_at: str

class SupplierCreate(BaseModel):
    name: str
    supplier_type: str
    contact_number: str
    email: EmailStr
    address: str

@api_router.get("/")
async def root():
    return {"message": "BlueCust API"}

@api_router.post("/auth/register")
async def register(user_data: UserRegister):
    existing = await db.users.find_one({"email": user_data.email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "email": user_data.email,
        "password": hash_password(user_data.password),
        "contact_number": user_data.contact_number,
        "business_name": user_data.business_name,
        "business_type": user_data.business_type,
        "is_admin": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    token = create_access_token({"user_id": user_id, "email": user_data.email})
    return {"token": token, "user": User(**{k: v for k, v in user_doc.items() if k != "password"})}

@api_router.post("/auth/login")
async def login(login_data: UserLogin):
    user = await db.users.find_one({"email": login_data.email}, {"_id": 0})
    if not user or not verify_password(login_data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_access_token({"user_id": user["id"], "email": user["email"]})
    return {"token": token, "user": User(**{k: v for k, v in user.items() if k != "password"})}

@api_router.post("/orders", response_model=Order)
async def create_order(order_data: OrderCreate, user_email: str):
    user = await db.users.find_one({"email": user_email}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    order_id = str(uuid.uuid4())
    total_amount = order_data.quantity * 16
    
    order_doc = {
        "id": order_id,
        "user_id": user["id"],
        "user_email": user["email"],
        "business_name": user["business_name"],
        "contact_number": user["contact_number"],
        "quantity": order_data.quantity,
        "sticker_text": order_data.sticker_text,
        "sticker_design_notes": order_data.sticker_design_notes,
        "payment_mode": order_data.payment_mode,
        "unit_price": 16,
        "total_amount": total_amount,
        "order_date": datetime.now(timezone.utc).isoformat(),
        "status": "pending"
    }
    await db.orders.insert_one(order_doc)
    return Order(**order_doc)

@api_router.get("/orders/user/{user_email}", response_model=List[Order])
async def get_user_orders(user_email: str):
    orders = await db.orders.find({"user_email": user_email}, {"_id": 0}).to_list(1000)
    return [Order(**order) for order in orders]

@api_router.get("/orders", response_model=List[Order])
async def get_all_orders():
    orders = await db.orders.find({}, {"_id": 0}).to_list(1000)
    return [Order(**order) for order in orders]

@api_router.get("/orders/{order_id}/pdf")
async def download_order_pdf(order_id: str):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    p.setFont("Helvetica-Bold", 24)
    p.drawString(1*inch, height - 1*inch, "BlueCust")
    p.setFont("Helvetica", 12)
    p.drawString(1*inch, height - 1.3*inch, "Custom Branded Water Bottles")
    p.drawString(1*inch, height - 1.5*inch, "Contact: 7385751471")
    p.drawString(1*inch, height - 1.7*inch, "Email: aryanrajput7385@gmail.com")
    
    p.line(1*inch, height - 2*inch, width - 1*inch, height - 2*inch)
    
    p.setFont("Helvetica-Bold", 16)
    p.drawString(1*inch, height - 2.5*inch, "Order Invoice")
    
    p.setFont("Helvetica", 12)
    y_position = height - 3*inch
    p.drawString(1*inch, y_position, f"Order ID: {order['id']}")
    y_position -= 0.3*inch
    p.drawString(1*inch, y_position, f"Date: {order['order_date'][:10]}")
    y_position -= 0.3*inch
    p.drawString(1*inch, y_position, f"Business Name: {order['business_name']}")
    y_position -= 0.3*inch
    p.drawString(1*inch, y_position, f"Contact: {order['contact_number']}")
    y_position -= 0.3*inch
    p.drawString(1*inch, y_position, f"Email: {order['user_email']}")
    
    y_position -= 0.6*inch
    p.line(1*inch, y_position, width - 1*inch, y_position)
    
    y_position -= 0.4*inch
    p.setFont("Helvetica-Bold", 12)
    p.drawString(1*inch, y_position, "Item Details:")
    
    y_position -= 0.3*inch
    p.setFont("Helvetica", 11)
    p.drawString(1*inch, y_position, f"Sticker Text: {order['sticker_text']}")
    y_position -= 0.3*inch
    p.drawString(1*inch, y_position, f"Design Notes: {order['sticker_design_notes'] or 'N/A'}")
    y_position -= 0.3*inch
    p.drawString(1*inch, y_position, f"Quantity: {order['quantity']} bottles")
    y_position -= 0.3*inch
    p.drawString(1*inch, y_position, f"Unit Price: ₹{order['unit_price']}")
    y_position -= 0.3*inch
    p.setFont("Helvetica-Bold", 12)
    p.drawString(1*inch, y_position, f"Total Amount: ₹{order['total_amount']}")
    
    y_position -= 0.6*inch
    p.setFont("Helvetica", 11)
    p.drawString(1*inch, y_position, f"Payment Mode: {order['payment_mode']}")
    if order['payment_mode'] == 'online':
        y_position -= 0.3*inch
        p.drawString(1*inch, y_position, "UPI ID: 7385751471@ybl")
    
    y_position -= 1*inch
    p.setFont("Helvetica-Oblique", 10)
    p.drawString(1*inch, y_position, "Thank you for choosing BlueCust!")
    p.drawString(1*inch, y_position - 0.2*inch, "Build your brand with every bottle.")
    
    p.showPage()
    p.save()
    buffer.seek(0)
    
    return StreamingResponse(buffer, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=BlueCust_Order_{order_id[:8]}.pdf"
    })

@api_router.post("/admin/suppliers", response_model=Supplier)
async def create_supplier(supplier_data: SupplierCreate):
    supplier_id = str(uuid.uuid4())
    supplier_doc = {
        "id": supplier_id,
        "name": supplier_data.name,
        "supplier_type": supplier_data.supplier_type,
        "contact_number": supplier_data.contact_number,
        "email": supplier_data.email,
        "address": supplier_data.address,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.suppliers.insert_one(supplier_doc)
    return Supplier(**supplier_doc)

@api_router.get("/admin/suppliers", response_model=List[Supplier])
async def get_suppliers():
    suppliers = await db.suppliers.find({}, {"_id": 0}).to_list(1000)
    return [Supplier(**supplier) for supplier in suppliers]

@api_router.delete("/admin/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: str):
    result = await db.suppliers.delete_one({"id": supplier_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {"message": "Supplier deleted"}

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()