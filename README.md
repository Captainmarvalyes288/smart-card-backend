# Smart Card Payment System

A modern payment system built with FastAPI backend and Next.js frontend for managing student smart card payments.

## Features

- QR Code based student identification
- Real-time payment processing
- Vendor dashboard for payment management
- Student transaction history
- Secure payment handling
- Modern responsive UI

## Tech Stack

### Backend
- FastAPI
- MongoDB
- Python 3.8+
- Razorpay Integration
- QR Code Generation

### Frontend
- Next.js 13+
- Tailwind CSS
- React QR Scanner
- Modern UI Components

## Setup Instructions

### Backend Setup

1. Navigate to the backend directory:
```bash
cd backend
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Start the server:
```bash
uvicorn main:app --reload
```

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Start the development server:
```bash
npm run dev
```

## API Documentation

The API documentation is available at `http://localhost:8000/docs` when the backend server is running.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/) 