"""Constants for the tested Haier TV firmware."""

from datetime import timedelta

DOMAIN = "haier_tv"
DEFAULT_PORT = 5555
UPDATE_INTERVAL = timedelta(seconds=10)
MODEL = "LE40AL88G31R1"
SOURCES = {
    "ATV": 1,
    "DTV": 3,
    "AV": 5,
    "Component": 10,
    "HDMI1": 16,
    "HDMI2": 17,
    "HDMI3": 18,
}
SOURCE_NAMES = {value: key for key, value in SOURCES.items()} | {24: "Android"}
