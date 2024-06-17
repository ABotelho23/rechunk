#!/usr/bin/env bash

if [ $(id -u) -ne 0 ]; then
    echo "Run as superuser"
    exit 1
fi

# This file creates a container based on the ostree repository
# with tag $OUT_TAG
MAX_LAYERS=${MAX_LAYERS:=80}
OUT_NAME=${OUT_TAG:=bazzite-deck}
OUT_TAG=master
RPM_OSTREE=${RPM_OSTREE:=rpm-ostree}

${RPM_OSTREE} compose \
    container-encapsulate \
    --repo=repo ${OUT_TAG} \
    --max-layers ${MAX_LAYERS} \
    oci-archive:${OUT_NAME}.oci-archive

echo Created archive with name $OUT_NAME.oci-archive