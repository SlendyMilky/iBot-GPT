FROM python:latest

RUN mkdir /iBot
WORKDIR /iBot
ADD . /iBot/
RUN pip install -r requirements.txt

CMD ["python", "/iBot/ibot.py"]`