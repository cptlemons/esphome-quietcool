FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static/ static/

ENV ESPHOME_HOST=192.168.50.114
ENV ESPHOME_PORT=6053
ENV ESPHOME_API_KEY=""
ENV WEB_PORT=8080

EXPOSE 8080

CMD ["python", "app.py"]
