FROM python:3.8.12-alpine
COPY . .
RUN apk add --no-cache gcc musl-dev
RUN pip3 install -r requirements.txt
CMD ["python3","./catalog.py"]
