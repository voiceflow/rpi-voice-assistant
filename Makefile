.PHONY: all clean install

all: dist/dialogbank.deb

clean:
	rm -rf dist build dialogbank.egg-info

dist:
	mkdir -p dist

install: dist/dialogbank.deb
	apt install ./dist/dialogbank.deb

dist/dialogbank.deb: dist
	fpm \
		--verbose \
		--debug \
		--architecture all \
		--input-type virtualenv \
		--output-type deb \
		--force \
		--name dialogbank \
		--package dist/dialogbank.deb \
		--prefix /usr/share/python \
		--depends portaudio19-dev \
		--depends mpv \
		--deb-systemd deb/dialogbank.service \
		--deb-systemd-enable \
		--config-files etc/dialogbank/dialogbank.env \
		.
