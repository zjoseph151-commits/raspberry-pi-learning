#include <Arduino.h>
#include <PubSubClient.h>
#include <WiFi.h>

// ---------------------------------------------------------------------------
// Wi-Fi and MQTT broker configuration
// Update these values for your network and Raspberry Pi MQTT broker.
// ---------------------------------------------------------------------------
const char *WIFI_SSID = "BananaHammock";
const char *WIFI_PASSWORD = "MoutainMan69!";

const char *MQTT_BROKER_IP = "10.0.0.179";
const uint16_t MQTT_PORT = 1883;

// ---------------------------------------------------------------------------
// Water level sensor configuration
// WTR_PIN must be an ADC-capable GPIO on the ESP32-C3.
// Calibrate the dry/full raw values after testing your specific sensor.
// ---------------------------------------------------------------------------
const uint8_t WTR_PIN = 2;
const int WTR_DRY_RAW = 0;
const int WTR_FULL_RAW = 4095;

// ---------------------------------------------------------------------------
// Device identity and MQTT topic layout
// Keep all identity values together so this sketch can become a reusable
// foundation for future ESP32-C3 sensor nodes.
// ---------------------------------------------------------------------------
const char *DEVICE_ID = "esp32-c3-test";
const char *FIRMWARE_VERSION = "0.1.0";

const char *STATUS_TOPIC = "home/devices/esp32-c3-test/status";
const char *AVAILABILITY_TOPIC = "home/devices/esp32-c3-test/availability";
const char *TELEMETRY_TOPIC = "home/devices/esp32-c3-test/telemetry";
const char *COMMANDS_TOPIC = "home/devices/esp32-c3-test/commands";

// ---------------------------------------------------------------------------
// Timing and payload configuration
// All recurring work uses millis() so reconnects and publishing stay responsive.
// ---------------------------------------------------------------------------
const unsigned long STATUS_INTERVAL_MS = 10000;
const unsigned long TELEMETRY_INTERVAL_MS = 15000;
const unsigned long WIFI_RECONNECT_INTERVAL_MS = 10000;
const unsigned long MQTT_RECONNECT_INTERVAL_MS = 5000;

const char *STATUS_JSON_FORMAT = "{\"device\":\"esp32-c3-test\",\"firmware_version\":\"0.1.0\",\"uptime_ms\":%lu,\"wifi_rssi\":%ld,\"free_heap\":%lu}";
const char *WATER_TELEMETRY_JSON_FORMAT = "{\"device\":\"esp32-c3-test\",\"water_level_percent\":%d,\"sensor_ok\":true,\"uptime_ms\":%lu}";
const char *WATER_TELEMETRY_ERROR_JSON_FORMAT = "{\"device\":\"esp32-c3-test\",\"water_level_percent\":null,\"sensor_ok\":false,\"uptime_ms\":%lu}";

struct WaterLevelReading
{
    bool ok;
    int percent;
    int raw;
};

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

String mqttClientId;
unsigned long lastStatusPublishAt = 0;
unsigned long lastTelemetryPublishAt = 0;
unsigned long lastWiFiConnectAttemptAt = 0;
unsigned long lastMqttConnectAttemptAt = 0;
bool wifiConnectStarted = false;

String buildMqttClientId()
{
    const uint64_t chipId = ESP.getEfuseMac();
    char chipIdText[13];
    snprintf(
        chipIdText,
        sizeof(chipIdText),
        "%04X%08X",
        static_cast<uint16_t>(chipId >> 32),
        static_cast<uint32_t>(chipId));

    return String(DEVICE_ID) + "-" + chipIdText;
}

void printWiFiStatus()
{
    Serial.println("[WiFi] Connected.");
    Serial.print("[WiFi] IP address: ");
    Serial.println(WiFi.localIP());
    Serial.print("[WiFi] RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
}

void beginWiFiConnection()
{
    lastWiFiConnectAttemptAt = millis();
    wifiConnectStarted = true;

    Serial.print("[WiFi] Connecting to SSID: ");
    Serial.println(WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void maintainWiFiConnection()
{
    static bool wasConnected = false;
    const bool connected = WiFi.status() == WL_CONNECTED;
    const unsigned long now = millis();

    if (connected)
    {
        if (!wasConnected)
        {
            printWiFiStatus();
        }
        wasConnected = true;
        return;
    }

    if (wasConnected)
    {
        Serial.println("[WiFi] Connection lost.");
        mqttClient.disconnect();
    }
    wasConnected = false;

    if (!wifiConnectStarted || now - lastWiFiConnectAttemptAt >= WIFI_RECONNECT_INTERVAL_MS)
    {
        beginWiFiConnection();
    }
}

void handleMqttMessage(char *topic, byte *payload, unsigned int length)
{
    Serial.print("[MQTT] Command received on ");
    Serial.print(topic);
    Serial.print(": ");

    for (unsigned int index = 0; index < length; index++)
    {
        Serial.print(static_cast<char>(payload[index]));
    }

    Serial.println();
}

void setupMQTT()
{
    mqttClientId = buildMqttClientId();
    mqttClient.setServer(MQTT_BROKER_IP, MQTT_PORT);
    mqttClient.setCallback(handleMqttMessage);
    mqttClient.setKeepAlive(30);
    mqttClient.setSocketTimeout(2);

    Serial.print("[MQTT] Broker: ");
    Serial.print(MQTT_BROKER_IP);
    Serial.print(":");
    Serial.println(MQTT_PORT);
    Serial.print("[MQTT] Client ID: ");
    Serial.println(mqttClientId);
    Serial.print("[MQTT] Status topic: ");
    Serial.println(STATUS_TOPIC);
    Serial.print("[MQTT] Availability topic: ");
    Serial.println(AVAILABILITY_TOPIC);
    Serial.print("[MQTT] Telemetry topic reserved: ");
    Serial.println(TELEMETRY_TOPIC);
    Serial.print("[MQTT] Commands topic: ");
    Serial.println(COMMANDS_TOPIC);
}

bool connectToMQTT()
{
    if (WiFi.status() != WL_CONNECTED)
    {
        return false;
    }

    Serial.print("[MQTT] Connecting as ");
    Serial.print(mqttClientId);
    Serial.println(" with retained LWT offline message...");

    const bool connected = mqttClient.connect(
        mqttClientId.c_str(),
        AVAILABILITY_TOPIC, 1, true, "offline");

    if (!connected)
    {
        Serial.print("[MQTT] Connection failed. State: ");
        Serial.println(mqttClient.state());
        return false;
    }

    Serial.println("[MQTT] Connected.");

    if (mqttClient.publish(AVAILABILITY_TOPIC, "online", true))
    {
        Serial.println("[MQTT] Published retained availability: online");
    }
    else
    {
        Serial.println("[MQTT] Failed to publish retained availability.");
    }

    if (mqttClient.subscribe(COMMANDS_TOPIC))
    {
        Serial.print("[MQTT] Subscribed to commands: ");
        Serial.println(COMMANDS_TOPIC);
    }
    else
    {
        Serial.println("[MQTT] Failed to subscribe to commands topic.");
    }

    lastStatusPublishAt = 0;
    lastTelemetryPublishAt = 0;
    return true;
}

void maintainMQTTConnection()
{
    const unsigned long now = millis();

    if (mqttClient.connected())
    {
        mqttClient.loop();
        return;
    }

    if (WiFi.status() != WL_CONNECTED)
    {
        return;
    }

    if (now - lastMqttConnectAttemptAt < MQTT_RECONNECT_INTERVAL_MS)
    {
        return;
    }

    lastMqttConnectAttemptAt = now;
    connectToMQTT();
}

bool buildStatusPayload(char *payload, size_t payloadSize)
{
    const int written = snprintf(
        payload,
        payloadSize,
        STATUS_JSON_FORMAT,
        millis(),
        static_cast<long>(WiFi.RSSI()),
        static_cast<unsigned long>(ESP.getFreeHeap()));

    return written > 0 && static_cast<size_t>(written) < payloadSize;
}

WaterLevelReading readWaterLevelSensor()
{
    WaterLevelReading reading = {false, 0, -1};

    if (WTR_FULL_RAW <= WTR_DRY_RAW)
    {
        Serial.println("[Sensor] Water level calibration is invalid; read failed.");
        return reading;
    }

    const int raw = analogRead(WTR_PIN);
    reading.raw = raw;

    if (raw < WTR_DRY_RAW || raw > WTR_FULL_RAW)
    {
        Serial.print("[Sensor] Water level raw read out of range: ");
        Serial.println(raw);
        return reading;
    }

    const long scaled = (static_cast<long>(raw - WTR_DRY_RAW) * 100L) / (WTR_FULL_RAW - WTR_DRY_RAW);
    reading.percent = constrain(static_cast<int>(scaled), 0, 100);
    reading.ok = true;
    return reading;
}

bool buildWaterTelemetryPayload(char *payload, size_t payloadSize, const WaterLevelReading &reading)
{
    const int written = reading.ok
                            ? snprintf(
                                  payload,
                                  payloadSize,
                                  WATER_TELEMETRY_JSON_FORMAT,
                                  reading.percent,
                                  millis())
                            : snprintf(
                                  payload,
                                  payloadSize,
                                  WATER_TELEMETRY_ERROR_JSON_FORMAT,
                                  millis());

    return written > 0 && static_cast<size_t>(written) < payloadSize;
}

void publishStatus()
{
    if (!mqttClient.connected())
    {
        return;
    }

    char payload[192];
    if (!buildStatusPayload(payload, sizeof(payload)))
    {
        Serial.println("[MQTT] Status payload too large; publish skipped.");
        return;
    }

    Serial.print("[MQTT] Publishing status to ");
    Serial.print(STATUS_TOPIC);
    Serial.print(": ");
    Serial.println(payload);

    if (mqttClient.publish(STATUS_TOPIC, payload))
    {
        Serial.println("[MQTT] Status published.");
    }
    else
    {
        Serial.println("[MQTT] Status publish failed.");
    }
}

void publishStatusIfDue()
{
    if (!mqttClient.connected())
    {
        return;
    }

    const unsigned long now = millis();
    if (lastStatusPublishAt != 0 && now - lastStatusPublishAt < STATUS_INTERVAL_MS)
    {
        return;
    }

    lastStatusPublishAt = now;
    publishStatus();
}

void publishWaterTelemetry()
{
    if (!mqttClient.connected())
    {
        return;
    }

    const WaterLevelReading reading = readWaterLevelSensor();
    if (!reading.ok)
    {
        Serial.println("[Sensor] Water level read failed; publishing sensor_ok=false telemetry.");
    }
    else
    {
        Serial.print("[Sensor] Water level raw=");
        Serial.print(reading.raw);
        Serial.print(", percent=");
        Serial.print(reading.percent);
        Serial.println("%");
    }

    char payload[160];
    if (!buildWaterTelemetryPayload(payload, sizeof(payload), reading))
    {
        Serial.println("[MQTT] Water telemetry payload too large; publish skipped.");
        return;
    }

    Serial.print("[MQTT] Publishing water telemetry to ");
    Serial.print(TELEMETRY_TOPIC);
    Serial.print(": ");
    Serial.println(payload);

    if (mqttClient.publish(TELEMETRY_TOPIC, payload))
    {
        Serial.println("[MQTT] Water telemetry published.");
    }
    else
    {
        Serial.println("[MQTT] Water telemetry publish failed.");
    }
}

void publishWaterTelemetryIfDue()
{
    if (!mqttClient.connected())
    {
        return;
    }

    const unsigned long now = millis();
    if (lastTelemetryPublishAt != 0 && now - lastTelemetryPublishAt < TELEMETRY_INTERVAL_MS)
    {
        return;
    }

    lastTelemetryPublishAt = now;
    publishWaterTelemetry();
}

void setup()
{
    Serial.begin(115200);
    Serial.println();
    Serial.println("[System] ESP32-C3 IoT sensor-node foundation starting.");
    Serial.print("[System] Device: ");
    Serial.println(DEVICE_ID);
    Serial.print("[System] Firmware: ");
    Serial.println(FIRMWARE_VERSION);
    Serial.print("[Sensor] Water level sensor pin GPIO");
    Serial.println(WTR_PIN);

    pinMode(WTR_PIN, INPUT);
    setupMQTT();
    beginWiFiConnection();
}

void loop()
{
    maintainWiFiConnection();
    maintainMQTTConnection();
    publishStatusIfDue();
    publishWaterTelemetryIfDue();
}
