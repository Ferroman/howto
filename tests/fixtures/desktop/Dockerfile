# The image of the app that the desktop tests film.
FROM howto-desktop
RUN apt-get update && apt-get install -y --no-install-recommends gir1.2-gtk-3.0 python3-gi-cairo \
 && rm -rf /var/lib/apt/lists/*
COPY app.py cover.py /opt/fixture/
