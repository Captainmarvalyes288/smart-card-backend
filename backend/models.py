from pydantic import BaseModel
from typing import Optional

class PaymentRequest(BaseModel):
    amount: float
    vendor_id: str

class WalletRechargeRequest(BaseModel):
    amount: float
    student_id: str

class VerifyPayment(BaseModel):
    order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    vendor_id: str

class StudentPaymentRequest(BaseModel):
    student_id: str
    vendor_id: str
    amount: float
    description: Optional[str] = None

class StudentQRData(BaseModel):
    student_id: str
