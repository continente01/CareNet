FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
CMD ["python3", "thermometer_sensor.py"]