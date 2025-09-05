FROM python:3.12-slim
COPY . .
RUN pip3 install -r requirements.txt
RUN apt-get update && apt-get install -y tzdata
ENV TZ=Europe/Rome
CMD ["python3","-u","./telegram_bot.py"]
