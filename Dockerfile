FROM docker.io/gelbpunkt/python:3.11

WORKDIR /src

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY telegram-logger.py .
COPY LICENSE .

CMD [ "python", "-u", "telegram-logger.py"]
