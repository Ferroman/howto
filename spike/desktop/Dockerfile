# The image of the measurements: what the base image is expected to hold, two
# window managers to compare, and four apps, one of each kind.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11-xserver-utils x11-utils xdotool wmctrl openbox metacity \
      dbus at-spi2-core python3 python3-gi gir1.2-atspi-2.0 python3-pil \
      ffmpeg tesseract-ocr tesseract-ocr-eng libgl1-mesa-dri \
      fonts-dejavu-core fonts-liberation fonts-noto-core fontconfig \
      adwaita-icon-theme hicolor-icon-theme ca-certificates curl \
      gedit gnome-calculator featherpad \
 && curl -fsSL -o /tmp/code.deb https://update.code.visualstudio.com/latest/linux-deb-x64/stable \
 && apt-get install -y --no-install-recommends /tmp/code.deb \
 && rm -rf /tmp/code.deb /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash howto \
 && mkdir /out && chown howto /out
