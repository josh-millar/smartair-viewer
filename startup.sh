#!/bin/sh

apt-get update
apt-get upgrade
apt-get install libx11-dev 
apt-get install libx11-6 
apt-get install libsm6 
apt-get install libxext6 
apt-get install libgl1-mesa-dev 
apt-get install libxrender1 

gunicorn --bind=0.0.0.0 --timeout 600 app:app