FROM alpine:latest

# Configure timezone and install dependencies
RUN apk update && \
    apk upgrade && \
    apk add --no-cache \
    htop \
    tzdata \
    python3 \
    py3-pip && \
    mkdir /iBot && \
    cp /usr/share/zoneinfo/Europe/Zurich /etc/localtime && \
    echo "Europe/Zurich" > /etc/timezone && \
    ln -sf /usr/bin/python3 /usr/bin/python && \
    pip install --no-cache --upgrade pip setuptools --break-system-packages

# Install python package dependencies
WORKDIR /iBot
COPY . /iBot/
RUN pip install python-dotenv --break-system-packages && \
    pip install -r requirements.txt --break-system-packages

# Run the application
CMD ["python3", "/iBot/ibot-gpt.py"]