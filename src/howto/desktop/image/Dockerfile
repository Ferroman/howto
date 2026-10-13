# The base image of a desktop storyboard: a monitor, a window manager, the
# accessibility bus, and howto's helper. `howto image` builds it from this
# file. The image of an app starts with `FROM howto-desktop`.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11-xserver-utils x11-utils xdotool wmctrl openbox \
      dbus at-spi2-core python3 python3-gi gir1.2-atspi-2.0 libgl1-mesa-dri \
      fonts-dejavu-core fonts-liberation fonts-noto-core fontconfig \
      adwaita-icon-theme hicolor-icon-theme ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash howto
COPY helper /opt/howto/helper
# After the packages, so that a new build of howto does not install them again.
ARG BUILD=unknown
LABEL howto.build=$BUILD
ENV HOWTO_BUILD=$BUILD PYTHONPATH=/opt/howto PYTHONDONTWRITEBYTECODE=1
WORKDIR /home/howto
# The image of an app adds to this one as root. The helper, and with it the app, runs as `howto`.
ENTRYPOINT ["setpriv", "--reuid=howto", "--regid=howto", "--init-groups", "env", "HOME=/home/howto", "USER=howto", "python3", "-m", "helper"]
