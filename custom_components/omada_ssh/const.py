"""Constants for the Omada ER605 (SSH) integration."""

from datetime import timedelta

DOMAIN = "omada_ssh"

CONF_CONSIDER_HOME = "consider_home"
CONF_PING_TARGET = "ping_target"

DEFAULT_HOST = "192.168.0.1"
DEFAULT_PORT = 22
DEFAULT_USERNAME = "admin"
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_CONSIDER_HOME = 180
DEFAULT_PING_TARGET = "8.8.8.8"

MIN_SCAN_INTERVAL = 10

UPTIME_TOLERANCE = timedelta(minutes=2)
