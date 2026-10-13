"""The helper: the program inside the container that starts the app and does what the stage asks.

It runs on the Python of the image, with the packages of the image. It
imports nothing of howto, and its modules import each other with a leading
dot: the package is `howto.desktop.helper` on the host, where its tests run,
and `helper` in the container.
"""
