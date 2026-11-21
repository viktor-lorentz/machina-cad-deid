#!/bin/bash
# VM bootstrap: RAID0 the local NVMe SSDs into /data (case-sensitive ext4), install tooling.
set -eux
if [ ! -e /data/.ready ]; then
  DEVS=$(ls /dev/disk/by-id/google-local-nvme-ssd-* 2>/dev/null || true)
  N=$(echo "$DEVS" | wc -w)
  apt-get update -y
  apt-get install -y mdadm python3-venv python3-pip git p7zip-full unzip tesseract-ocr aria2 curl
  if [ "$N" -gt 1 ]; then mdadm --create /dev/md0 --level=0 --raid-devices=$N $DEVS --run; DEV=/dev/md0; else DEV=$DEVS; fi
  mkfs.ext4 -F -E lazy_itable_init=1 $DEV
  mkdir -p /data && mount -o discard,noatime $DEV /data && chmod 777 /data
  touch /data/.ready
fi
