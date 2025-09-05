FROM python:3.12-slim
RUN apt-get update && apt-get install -y gcc g++ build-essential
COPY . .
RUN pip3 install -r requirements.txt
CMD ["python3","-u","./time_control.py"]
