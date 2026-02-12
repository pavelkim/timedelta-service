#!/bin/sh
set -e

if [ -f ".version" ]; then
    APP_VERSION=$(cat ".version")
else
    APP_VERSION="0.0.0"
fi

export APP_VERSION

echo " TimeDelta Service (tdsvc)"
echo " Version: ${APP_VERSION}"
echo " Host ID: ${HOST_ID:-$(hostname)}"
echo " Log Level: ${LOG_LEVEL:-INFO}"
echo " RMQ URI: ${RMQ_SERVER_URI:-not set}"

exec python -m tdsvc.tdsvc
