FROM python:3

RUN apt-get -qq update
RUN apt-get -y upgrade >/dev/null
RUN pip install --upgrade pip
RUN pip install fastapi uvicorn docker pyyaml pydantic aiofiles

RUN useradd -d /app app

ADD src /app
WORKDIR /app

ENTRYPOINT ["python3", "swarm_api.py"]
EXPOSE 8080

LABEL org.opencontainers.image.title SwarmPY
LABEL org.opencontainers.image.description "Swarm API and GUI"
