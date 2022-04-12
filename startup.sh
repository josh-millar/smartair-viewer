#!/bin/sh

apt-get update -y && apt install -y libsm6 libxext6
apt-get install -y python3-opencv

pip install opencv-python

echo $PWD $APP_PATH

cd $APP_PATH

python app.py