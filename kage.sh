#!/usr/bin/env bash

export PATH="/usr/local/bin:/usr/bin:/bin:/opt/bin"
export LC_ALL="ru_RU.UTF-8"
cd /home/tolich/anime-fetch

if [ -f 'flags/stop' ]; then
	exit 0
fi

./kage.py -u &> kage.log
err=$?
if [ $err -ne 0 ]; then
	touch flags/stop
	cat kage.log
fi

exit $err
