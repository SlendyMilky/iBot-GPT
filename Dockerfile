FROM python:alpine3.18

RUN mkdir /iBot
WORKDIR /iBot
ADD . /iBot/
RUN pip install -r requirements.txt

CMD ["python", "/iBot/ibot.py"]`