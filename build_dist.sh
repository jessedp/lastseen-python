#!/bin/bash
rm -rf dist/lastseen
#export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu
#export LD_LIBRARY_PATH=/usr/lib/python3.6/config-3.6m-x86_64-linux-gnu
#pyinstaller --clean -y lastseen.py --onefile
#yinstaller --clean --onefile lastseen-custom.spec
docker run -v "$(pwd):/src/" cdrx/pyinstaller-linux \
    "apt-get update -y && apt-get upgrade -y && apt-get install -y python3-gi python3-dbus upx-ucl \
        && pip install --upgrade pip && pip install -r requirements.txt && pyinstaller \
        --clean -y --dist ./dist/linux --workpath /tmp lastseen.spec"