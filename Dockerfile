FROM python:latest

RUN mkdir /iBot
WORKDUR /iBot
ADD . /iBot/
RUN pip install -r requirements.txt

CMD ["python", "/iBot/ibot.py"]`