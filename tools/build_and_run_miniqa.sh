#!/bin/bash

# Run miniqa depending on which installation mode is available; tries podman, then docker, then pre-existing local
# install and lastly installs via pip.
# This script will also download the latest GNOME OS nightly disk image, if its not yet present, and build miniQA from
# source.

cd ../sample_tests

set -eou pipefail

IMG_DOWNLOAD_URL="https://os.gnome.org/download/latest/gnome_os_nightly.iso"
IMG_PTH="img/gnome_os_disk.img"

MINIQA_EXTRAS="ocr"


if [ "$#" -gt 0 ]; then
    COMMAND=("$@")
else
    COMMAND=("run")
fi


# Download the latest GNOME OS nightly disk image, if its not yet downloaded:
if [ ! -f "$IMG_PTH" ]; then
  echo "Downloading GNOME OS disk image from $IMG_DOWNLOAD_URL"
  curl -Lo "$IMG_PTH.tmp" "$IMG_DOWNLOAD_URL"
  mv "$IMG_PTH.tmp" "$IMG_PTH"
fi


if [ -x "$(command -v podman)" ]; then
  echo "Running using podman"

  # Build the image locally from source:
  podman build -t miniqa --build-arg EXTRAS="$MINIQA_EXTRAS" ..

  podman run \
      --rm \
      -it \
      --device /dev/kvm \
      --tmpfs /tmp:size=1G,mode=1700 \
      -p 8080:8080 \
      -p 6080:6080 \
      -v .:/tests:z \
      miniqa "${COMMAND[@]}"

elif [ -x "$(command -v docker)" ]; then
  echo "Running using docker"

  # Build the image locally from source:
  docker build -t miniqa --build-arg EXTRAS="$MINIQA_EXTRAS" ..

  docker run \
      --rm \
      -it \
      --device /dev/kvm \
      --tmpfs /tmp:size=1G,mode=1700 \
      -p 8080:8080 \
      -p 6080:6080 \
      -v .:/tests \
      miniqa "${COMMAND[@]}"

elif [ -x "$(command -v pip)" ]; then
  echo "Installing miniQA via pip..."
  pip install ..["$EXTRAS"]
  miniqa "${COMMAND[@]}"

else
  echo "Need either podman, docker or pip to run miniQA"

fi
