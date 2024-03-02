# rpi-voice-assistant

## Debian package

Building a Debian package allows easy installation and upgrades of the Dialogbank application and all system dependencies on Raspberry Pis running Debian (or Raspberry Pi OS which is based on Debian).

The Dockerfile in this repository contains the necessary prerequisites in order to build the Debian package, in particular [`fpm`](https://fpm.readthedocs.io/en/latest/) (a tool to build OS packages for different distributions from different source formats) as well as Python 3.11, the default Python version for Debian Bookworm.

In order to build the Debian package run the following command:

```
docker compose run --rm dev make
```

The binary Debian package will be written to `dist/dialogbank.deb`.
