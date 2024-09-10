FROM ubuntu:23.04

HEALTHCHECK NONE

RUN apt-get update
RUN apt-get install rsync -y
RUN apt-get install python3 -y
RUN apt-get install python3-pip -y
RUN apt-get install python3-venv -y
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install boto3

USER root
WORKDIR /
COPY main.py /
CMD ["python3", "/main.py"]
