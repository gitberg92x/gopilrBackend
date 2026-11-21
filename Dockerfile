FROM python:3.11-alphine
RUN apk add --no-cache go
WORKDIR /app
COPY server.py .
EXPOSE 8080
CMD ["python", "server.py"]
