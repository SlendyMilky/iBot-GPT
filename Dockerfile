FROM alpine:latest

# Prepare Image
RUN apk update && apk upgrade
RUN apk add htop tzdata
RUN cp /usr/share/zoneinfo/Europe/Zurich /etc/localtime
RUN echo "Europe/Zurich" >  /etc/timezone

# Install python/pip
ENV PYTHONUNBUFFERED=1
RUN apk add --update --no-cache python3 && ln -sf python3 /usr/bin/python
RUN python3 -m ensurepip
RUN pip3 install --no-cache --upgrade pip setuptools

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install dependencies:
RUN mkdir /iBot
WORKDIR /iBot
ADD . /iBot/
RUN pip install -U python-dotenv
RUN pip install -r requirements.txt

# Run the application:
CMD ["python3", "/iBot/ibot.py"]`