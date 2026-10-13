# The image of the desktop example: gedit, and a document for it to open.
#
#   howto image
#   docker build -t howto-gedit examples/desktop
#   howto probe examples/desktop/replace.yaml
FROM howto-desktop
RUN apt-get update && apt-get install -y --no-install-recommends gedit \
 && rm -rf /var/lib/apt/lists/*
# The app runs as `howto`. A document that it saves must be that user's.
COPY --chown=howto:howto notes.txt /home/howto/notes.txt
