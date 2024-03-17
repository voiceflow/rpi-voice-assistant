from setuptools import setup, find_packages

setup(
    name="dialogbank",
    version="0.1.0",
    packages=find_packages(),
    license="MIT",
    long_description="Dialogbank application",
    install_requires=[
        "google-cloud>=0.34.0",
        "google-cloud-speech>=2.0.1",
        "PyAudio>=0.2.11",
        "gTTS>=2.2.2",
        "playsound>=1.2.2",
        "structlog>=21.1.0",
        "python-dotenv>=1.0.1",
        "requests>=2.31.0",
        # grpcio is a transitive dependency of google-cloud-speech. grpcio is a Cython
        # package and not installing it explicitly causes problems when packaging for Debian
        # for some reason. I haven’t found out why exactly so far.
        "grpcio>=1.49.1,<2.0dev",
    ],
    include_package_data=True,
    package_data={
        "dialogbank": ["assets/*.wav"],
    },
    entry_points={
        "console_scripts": [
            "dbank = dialogbank.main:main",
        ],
    },
)
