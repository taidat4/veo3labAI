FROM node:20-slim

# Install Python
RUN apt-get update && apt-get install -y python3 python3-pip python3-venv && \
    ln -sf /usr/bin/python3 /usr/bin/python && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Node dependencies
COPY package*.json ./
RUN npm ci

# Install Python dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r backend/requirements.txt

# Copy all source
COPY . .

# Build Next.js
RUN npm run build

# Expose port (Railway sets PORT=8080)
EXPOSE 8080

# Start both: Python backend on 8000, Next.js on 8080
CMD bash -c "(cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000) & sleep 3 && npm start"
