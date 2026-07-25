#pragma once

#include <stdint.h>

// Copy this file to include/secrets.h and replace the placeholder values.
// include/secrets.h is ignored by Git so real credentials stay local.

const char *WIFI_SSID = "your-wifi-ssid";
const char *WIFI_PASSWORD = "your-wifi-password";

const char *MQTT_BROKER_IP = "10.0.0.180";
const uint16_t MQTT_PORT = 1883;

const char *OTA_PASSWORD = "replace-with-a-strong-ota-password";
