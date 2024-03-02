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
