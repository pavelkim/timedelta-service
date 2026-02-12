#!/bin/sh
#
# Docker container entrypoint script for tdsvc_exporter
#

set -e

if [ -f ".version" ]; then
    APP_VERSION=$(cat ".version")
else
    APP_VERSION="0.0.0"
fi

export APP_VERSION

echo " TimeDelta Service Exporter (tdsvc_exporter)"
echo " Version: ${APP_VERSION}"
echo " Log Level: ${LOG_LEVEL:-INFO}"
echo " RMQ URI: ${RMQ_SERVER_URI:-not set}"
echo " Display Interval: ${EXPORTER_DISPLAY_INTERVAL:-5}s"

python -m tdsvc.tdsvc_exporter
