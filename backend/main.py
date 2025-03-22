from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import razorpay
from database import students_collection, vendors_collection, transactions_collection
from models import PaymentRequest, WalletRechargeRequest, VerifyPayment, StudentPaymentRequest, StudentQRData
from config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
import qrcode
from io import BytesIO
import base64
import json
from bson import ObjectId
import datetime

app = FastAPI(title="Smart Card Payment System")

# Configure CORS
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Razorpay client
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

@app.get("/")
def read_root():
    return {"message": "Smart Card Payment System API"}

# Generate Vendor QR Code
@app.get("/get_vendor_qr/{vendor_id}")
def get_vendor_qr(vendor_id: str):
    vendor = vendors_collection.find_one({"vendor_id": vendor_id})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    upi_id = vendor["upi_id"]
    qr_code_data = f"upi://pay?pa={upi_id}&pn=Vendor&mc=0000&mode=02&purpose=00"
    
    qr = qrcode.make(qr_code_data)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return {"qr_code": f"data:image/png;base64,{qr_base64}"}

# Create Razorpay Order for Vendor
@app.post("/create_razorpay_order")
def create_razorpay_order(payment: PaymentRequest):
    vendor = vendors_collection.find_one({"vendor_id": payment.vendor_id})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    order = razorpay_client.order.create({
        "amount": int(payment.amount * 100),
        "currency": "INR",
        "payment_capture": 1,
    })

    transactions_collection.insert_one({
        "order_id": order["id"],
        "vendor_id": payment.vendor_id,
        "amount": payment.amount,
        "status": "pending",
    })

    return {"order_id": order["id"], "amount": payment.amount}

# Verify Razorpay Payment
@app.post("/verify_payment")
def verify_payment(payment: VerifyPayment):
    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": payment.order_id,
            "razorpay_payment_id": payment.razorpay_payment_id,
            "razorpay_signature": payment.razorpay_signature,
        })

        transactions_collection.update_one({"order_id": payment.order_id}, {"$set": {"status": "completed"}})

        return {"message": "Payment verified successfully!"}

    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Payment verification failed")

@app.get("/student/{student_id}")
async def get_student(student_id: str):
    student = students_collection.find_one({"student_id": student_id})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Convert ObjectId to string for JSON serialization
    student["_id"] = str(student["_id"])
    return student

@app.get("/vendor/{vendor_id}")
async def get_vendor(vendor_id: str):
    vendor = vendors_collection.find_one({"vendor_id": vendor_id})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {
        "vendor_id": vendor["vendor_id"],
        "name": vendor["name"],
        "upi_id": vendor["upi_id"]
    }

# Generate Student QR Code
@app.get("/get_student_qr/{student_id}")
async def get_student_qr(student_id: str):
    student = students_collection.find_one({"student_id": student_id})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Create QR code data with student information
    qr_data = json.dumps({"student_id": student_id})
    
    qr = qrcode.make(qr_data)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return {
        "qr_code": f"data:image/png;base64,{qr_base64}",
        "student_name": student["name"],
        "balance": student["balance"]
    }

# Process Student Payment
@app.post("/process_student_payment")
async def process_student_payment(payment: StudentPaymentRequest):
    # Verify student exists and has sufficient balance
    student = students_collection.find_one({"student_id": payment.student_id})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    if student["balance"] < payment.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    # Verify vendor exists
    vendor = vendors_collection.find_one({"vendor_id": payment.vendor_id})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Process the transaction
    new_balance = student["balance"] - payment.amount
    
    # Update student balance
    students_collection.update_one(
        {"student_id": payment.student_id},
        {"$set": {"balance": new_balance}}
    )

    # Record the transaction
    transaction = {
        "student_id": payment.student_id,
        "vendor_id": payment.vendor_id,
        "amount": payment.amount,
        "type": "purchase",
        "description": payment.description,
        "status": "completed",
        "timestamp": datetime.datetime.now()
    }
    transactions_collection.insert_one(transaction)

    return {
        "message": "Payment processed successfully",
        "new_balance": new_balance,
        "transaction_id": str(transaction["_id"])
    }

# Get Student Transactions
@app.get("/student/transactions/{student_id}")
async def get_student_transactions(student_id: str):
    student = students_collection.find_one({"student_id": student_id})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    transactions = list(transactions_collection.find({"student_id": student_id}))
    # Convert ObjectId to string for JSON serialization
    for transaction in transactions:
        transaction["_id"] = str(transaction["_id"])
    
    return {"transactions": transactions}
