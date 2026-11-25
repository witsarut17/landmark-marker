# Python 3.12 + โปรแกรมเสริมของเซิร์ฟเวอร์ สำหรับเครื่อง Linux ที่ไม่มี Python 3.11+ หรือไม่มีสิทธิ์ sudo
# build (บริบท = โฟลเดอร์ server/ ที่มี requirements.txt):
#   docker build -f <ROOT>/app/server/linux/Dockerfile -t pelnav-py312 <ROOT>/app/server
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV PYTHONUNBUFFERED=1 TZ=Asia/Bangkok
