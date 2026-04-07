#!/bin/bash

set -eou pipefail

IMG_DOWNLOAD_URL="https://os.gnome.org/download/latest/gnome_os_nightly.iso"
IMG_PTH="img/gnome_os_disk.img"
EXTRAS="ocr"


if [ ! -f "$IMG_PTH" ]; then
  echo "Downloading GNOME OS disk image from $IMG_DOWNLOAD_URL"
  curl -Lo "$IMG_PTH.tmp" "$IMG_DOWNLOAD_URL"
  mv "$IMG_PTH.tmp" "$IMG_PTH"
fi

if [ -x "$(command -v podman)" ]; then
  # Build the image locally from source:
  podman build -t miniqa --build-arg EXTRAS="$EXTRAS" ..

  # Run miniqa in a temporary:
  podman run \
      --rm \
      -it \
      --device /dev/kvm \
      --tmpfs /tmp:size=1G,mode=1700 \
      -p 8080:8080 \
      -p 6080:6080 \
      -v .:/tests \
      miniqa "$@"
  #podman run --rm -v .:/tests --entrypoint bash -it miniqa
fi
