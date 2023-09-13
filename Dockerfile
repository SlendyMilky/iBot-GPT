FROM python:alpine3.18

ENV Discord_Forum_Name = **None** \
    Discord_Bot_Token = **None** \
    GPT_KEY = **None**

RUN mkdir /iBot
WORKDIR /iBot
ADD . /iBot/
RUN pip install -r requirements.txt

CMD ["python", "/iBot/ibot.py"]`