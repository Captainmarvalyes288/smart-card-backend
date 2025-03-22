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
import os
import hmac
import hashlib

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
client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))

@app.get("/")
def read_root():
    return {"message": "Smart Card Payment System API"}

# Generate Vendor QR Code
@app.get("/get_vendor_qr/{vendor_id}")
async def get_vendor_qr(vendor_id: str):
    vendor = vendors_collection.find_one({"vendor_id": vendor_id})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Create QR code data with vendor information
    vendor_data = {
        "vendor_id": vendor_id,
        "name": vendor["name"],
        "upi_id": vendor["upi_id"]
    }
    
    qr_code_data = json.dumps(vendor_data)
    qr = qrcode.make(qr_code_data)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return {
        "qr_code": f"data:image/png;base64,{qr_base64}",
        "vendor_name": vendor["name"],
        "upi_id": vendor["upi_id"],
        "balance": vendor.get("balance", 0)
    }

# Create Razorpay Order for Wallet Recharge
@app.post("/create_recharge_order")
async def create_recharge_order(request: WalletRechargeRequest):
    try:
        # Check if student exists
        student = students_collection.find_one({"student_id": request.student_id})
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        # Check if vendor exists
        vendor = vendors_collection.find_one({"vendor_id": request.vendor_id})
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")

        # Create Razorpay order
        order_amount = int(float(request.amount) * 100)  # Convert to paise
        order_currency = 'INR'
        
        order_data = {
            'amount': order_amount,
            'currency': order_currency,
            'payment_capture': 1,  # Auto capture payment
            'notes': {
                'student_id': request.student_id,
                'vendor_id': request.vendor_id
            }
        }
        
        try:
            order = client.order.create(data=order_data)
        except Exception as e:
            print(f"Razorpay order creation error: {str(e)}")  # Debug log
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create payment order: {str(e)}"
            )

        # Store order details in database with proper description and formatted date
        current_time = datetime.datetime.now()
        formatted_date = current_time.strftime("%d/%m/%Y, %H:%M:%S")
        
        order_doc = {
            "order_id": order['id'],
            "amount": float(request.amount),
            "student_id": request.student_id,
            "vendor_id": request.vendor_id,
            "status": "pending",
            "description": f"Wallet recharge via {vendor['name']}",
            "created_at": current_time,
            "formatted_date": formatted_date
        }
        transactions_collection.insert_one(order_doc)

        return {
            "id": order['id'],
            "amount": order_amount,
            "currency": order_currency,
            "key": os.getenv("RAZORPAY_KEY_ID")
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Order creation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Verify Razorpay Payment and Update Wallet
@app.post("/verify_recharge_payment")
async def verify_recharge_payment(payment: dict):
    try:
        # Verify payment signature
        params_dict = {
            'razorpay_payment_id': payment.get('razorpay_payment_id'),
            'razorpay_order_id': payment.get('razorpay_order_id'),
            'razorpay_signature': payment.get('razorpay_signature')
        }

        client.utility.verify_payment_signature(params_dict)

        # Get order details from database
        order = transactions_collection.find_one({"order_id": payment['razorpay_order_id']})
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # Update student's wallet balance
        student_update = students_collection.find_one_and_update(
            {"student_id": payment['student_id']},
            {"$inc": {"wallet_balance": order['amount']}},
            return_document=True
        )

        if not student_update:
            raise HTTPException(status_code=404, detail="Student not found")

        # Update vendor's balance
        vendor = vendors_collection.find_one({"vendor_id": payment['vendor_id']})
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")

        vendor_update = vendors_collection.find_one_and_update(
            {"vendor_id": payment['vendor_id']},
            {"$inc": {"balance": order['amount']}},
            return_document=True
        )

        # Update order status with completion time
        current_time = datetime.datetime.now()
        formatted_date = current_time.strftime("%d/%m/%Y, %H:%M:%S")
        
        transactions_collection.update_one(
            {"order_id": payment['razorpay_order_id']},
            {
                "$set": {
                    "status": "completed",
                    "payment_id": payment['razorpay_payment_id'],
                    "completed_at": current_time,
                    "formatted_date": formatted_date,
                    "description": f"Wallet recharge of ₹{order['amount']} via {vendor['name']}"
                }
            }
        )

        return {
            "status": "success",
            "new_balance": student_update.get('wallet_balance', 0)
        }

    except razorpay.errors.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        "upi_id": vendor["upi_id"],
        "balance": vendor.get("balance", 0)  # Return 0 if balance doesn't exist
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

    # Get current vendor balance or default to 0 if not exists
    current_vendor_balance = vendor.get("balance", 0)

    # Process the transaction
    new_student_balance = student["balance"] - payment.amount
    new_vendor_balance = current_vendor_balance + payment.amount
    
    # Update student balance
    students_collection.update_one(
        {"student_id": payment.student_id},
        {"$set": {"balance": new_student_balance}}
    )

    # Update vendor balance
    vendors_collection.update_one(
        {"vendor_id": payment.vendor_id},
        {"$set": {"balance": new_vendor_balance}}
    )

    # Record the transaction
    transaction = {
        "student_id": payment.student_id,
        "vendor_id": payment.vendor_id,
        "amount": payment.amount,
        "type": "purchase",
        "description": payment.description,
        "status": "completed",
        "timestamp": datetime.datetime.now(),
        "student_balance": new_student_balance,
        "vendor_balance": new_vendor_balance
    }
    transactions_collection.insert_one(transaction)

    return {
        "message": "Payment processed successfully",
        "student_balance": new_student_balance,
        "vendor_balance": new_vendor_balance,
        "transaction_id": str(transaction["_id"])
    }

# Get Student Transactions
@app.get("/student/transactions/{student_id}")
async def get_student_transactions(student_id: str):
    student = students_collection.find_one({"student_id": student_id})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    transactions = list(transactions_collection.find(
        {"student_id": student_id},
        sort=[("created_at", -1)]  # Sort by date in descending order
    ))
    
    # Format transactions for display
    formatted_transactions = []
    for transaction in transactions:
        formatted_transaction = {
            "_id": str(transaction["_id"]),
            "date": transaction.get("formatted_date", "N/A"),
            "student_id": transaction["student_id"],
            "amount": f"₹{transaction['amount']}",
            "description": transaction.get("description", "Transaction"),
            "status": transaction["status"]
        }
        formatted_transactions.append(formatted_transaction)
    
    return {"transactions": formatted_transactions}

# Get Vendor Transactions
@app.get("/vendor/transactions/{vendor_id}")
async def get_vendor_transactions(vendor_id: str):
    vendor = vendors_collection.find_one({"vendor_id": vendor_id})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    
    transactions = list(transactions_collection.find({"vendor_id": vendor_id}))
    # Convert ObjectId to string for JSON serialization
    for transaction in transactions:
        transaction["_id"] = str(transaction["_id"])
    
    return {
        "transactions": transactions,
        "current_balance": vendor.get("balance", 0)
    }
