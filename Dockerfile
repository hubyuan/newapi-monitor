FROM python:3.12-slim
WORKDIR /app
COPY server.py index.html ./
EXPOSE 8898
CMD ["python3", "server.py"]
