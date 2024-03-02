FROM debian:bookworm-slim

RUN apt-get update
RUN apt-get install -y make

RUN apt-get install -y ruby ruby-dev rubygems
RUN gem install --no-document fpm

RUN apt-get install -y python3 python3-pip python3-setuptools portaudio19-dev mpv
RUN pip install --break-system-packages build virtualenv virtualenv-tools3

WORKDIR /root/src
