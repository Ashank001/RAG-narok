FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Make start.sh executable
RUN chmod +x start.sh

CMD ["sh", "start.sh"]