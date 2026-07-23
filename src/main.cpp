#include <Arduino.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <math.h>
#include <string.h>

// ---------------------------------------------------------------------------
// Wi-Fi and MQTT broker configuration
// Update these values for your network and Raspberry Pi MQTT broker.
// ---------------------------------------------------------------------------
const char *WIFI_SSID = "BananaHammock";
const char *WIFI_PASSWORD = "MoutainMan69!";

const char *MQTT_BROKER_IP = "10.0.0.179";
const uint16_t MQTT_PORT = 1883;

// ---------------------------------------------------------------------------
// DHT11 temperature/humidity sensor configuration
// DHT_PIN is the module data pin. Most DHT11 modules include the needed pull-up.
// ---------------------------------------------------------------------------
const uint8_t DHT_PIN = 3;
const uint8_t DHT_TYPE = DHT11;

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
const char *RESPONSES_TOPIC = "home/devices/esp32-c3-test/responses";

// ---------------------------------------------------------------------------
// Timing and payload configuration
// All recurring work uses millis() so reconnects and publishing stay responsive.
// ---------------------------------------------------------------------------
const unsigned long STATUS_INTERVAL_MS = 10000;
const unsigned long TELEMETRY_INTERVAL_MS = 15000;
const unsigned long WIFI_RECONNECT_INTERVAL_MS = 10000;
const unsigned long MQTT_RECONNECT_INTERVAL_MS = 5000;
const unsigned long MIN_TELEMETRY_INTERVAL_SECONDS = 5;
const unsigned long MAX_TELEMETRY_INTERVAL_SECONDS = 3600;

const size_t COMMAND_PAYLOAD_BUFFER_SIZE = 256;
const size_t COMMAND_NAME_BUFFER_SIZE = 32;
const size_t COMMAND_RESPONSE_BUFFER_SIZE = 192;
const uint16_t MQTT_PACKET_BUFFER_SIZE = 384;

const char *STATUS_JSON_FORMAT = "{\"device\":\"esp32-c3-test\",\"firmware_version\":\"0.1.0\",\"uptime_ms\":%lu,\"wifi_rssi\":%ld,\"free_heap\":%lu}";
const char *DHT_TELEMETRY_JSON_FORMAT = "{\"device\":\"esp32-c3-test\",\"temperature_c\":%.1f,\"humidity_percent\":%.1f,\"sensor_ok\":true,\"uptime_ms\":%lu}";
const char *DHT_TELEMETRY_ERROR_JSON_FORMAT = "{\"device\":\"esp32-c3-test\",\"temperature_c\":null,\"humidity_percent\":null,\"sensor_ok\":false,\"uptime_ms\":%lu}";

const char *COMMAND_READ_NOW = "read_now";
const char *COMMAND_SET_INTERVAL = "set_interval";
const char *UNKNOWN_COMMAND_NAME = "unknown";

const char *ERROR_MALFORMED_JSON = "malformed_json";
const char *ERROR_PAYLOAD_TOO_LARGE = "payload_too_large";
const char *ERROR_MISSING_COMMAND = "missing_command";
const char *ERROR_UNKNOWN_COMMAND = "unknown_command";
const char *ERROR_MISSING_INTERVAL_SECONDS = "missing_interval_seconds";
const char *ERROR_INVALID_INTERVAL_SECONDS = "invalid_interval_seconds";
const char *ERROR_INTERVAL_OUT_OF_RANGE = "interval_out_of_range";

enum CommandType
{
    COMMAND_TYPE_READ_NOW,
    COMMAND_TYPE_SET_INTERVAL,
    COMMAND_TYPE_UNKNOWN
};

struct DhtReading
{
    bool ok;
    float temperatureC;
    float humidityPercent;
};

struct CommandRequest
{
    CommandType type;
    char command[COMMAND_NAME_BUFFER_SIZE];
    bool hasIntervalSeconds;
    unsigned long intervalSeconds;
    const char *intervalError;
};

DHT dht(DHT_PIN, DHT_TYPE);
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

String mqttClientId;
unsigned long lastStatusPublishAt = 0;
unsigned long lastTelemetryPublishAt = 0;
unsigned long lastWiFiConnectAttemptAt = 0;
unsigned long lastMqttConnectAttemptAt = 0;
unsigned long telemetryIntervalMs = TELEMETRY_INTERVAL_MS;
bool wifiConnectStarted = false;

bool publishCommandResponse(
    const char *command,
    bool success,
    const char *error = nullptr,
    unsigned long intervalSeconds = 0,
    bool includeIntervalSeconds = false);
void processCommandPayload(const char *payload);

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

    if (length >= COMMAND_PAYLOAD_BUFFER_SIZE)
    {
        Serial.println("[payload too large]");
        publishCommandResponse(UNKNOWN_COMMAND_NAME, false, ERROR_PAYLOAD_TOO_LARGE);
        return;
    }

    char commandPayload[COMMAND_PAYLOAD_BUFFER_SIZE];
    for (unsigned int index = 0; index < length; index++)
    {
        commandPayload[index] = static_cast<char>(payload[index]);
    }
    commandPayload[length] = '\0';

    Serial.println(commandPayload);
    processCommandPayload(commandPayload);
}

void setupMQTT()
{
    mqttClientId = buildMqttClientId();
    mqttClient.setServer(MQTT_BROKER_IP, MQTT_PORT);
    mqttClient.setCallback(handleMqttMessage);
    mqttClient.setBufferSize(MQTT_PACKET_BUFFER_SIZE);
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
    Serial.print("[MQTT] Telemetry topic: ");
    Serial.println(TELEMETRY_TOPIC);
    Serial.print("[MQTT] Commands topic: ");
    Serial.println(COMMANDS_TOPIC);
    Serial.print("[MQTT] Responses topic: ");
    Serial.println(RESPONSES_TOPIC);
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

DhtReading readDhtSensor()
{
    DhtReading reading = {false, NAN, NAN};

    const float humidity = dht.readHumidity();
    const float temperatureC = dht.readTemperature();

    if (isnan(humidity) || isnan(temperatureC))
    {
        Serial.println("[Sensor] DHT11 read failed; check sensor wiring and power.");
        return reading;
    }

    reading.temperatureC = temperatureC;
    reading.humidityPercent = humidity;
    reading.ok = true;
    return reading;
}

bool buildDhtTelemetryPayload(char *payload, size_t payloadSize, const DhtReading &reading)
{
    const int written = reading.ok
                            ? snprintf(
                                  payload,
                                  payloadSize,
                                  DHT_TELEMETRY_JSON_FORMAT,
                                  reading.temperatureC,
                                  reading.humidityPercent,
                                  millis())
                            : snprintf(
                                  payload,
                                  payloadSize,
                                  DHT_TELEMETRY_ERROR_JSON_FORMAT,
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

void publishDhtTelemetry()
{
    if (!mqttClient.connected())
    {
        return;
    }

    const DhtReading reading = readDhtSensor();
    if (!reading.ok)
    {
        Serial.println("[Sensor] DHT11 read failed; publishing sensor_ok=false telemetry.");
    }
    else
    {
        Serial.print("[Sensor] DHT11 temperature=");
        Serial.print(reading.temperatureC, 1);
        Serial.print(" C, humidity=");
        Serial.print(reading.humidityPercent, 1);
        Serial.println("%");
    }

    char payload[160];
    if (!buildDhtTelemetryPayload(payload, sizeof(payload), reading))
    {
        Serial.println("[MQTT] DHT11 telemetry payload too large; publish skipped.");
        return;
    }

    Serial.print("[MQTT] Publishing DHT11 telemetry to ");
    Serial.print(TELEMETRY_TOPIC);
    Serial.print(": ");
    Serial.println(payload);

    if (mqttClient.publish(TELEMETRY_TOPIC, payload))
    {
        Serial.println("[MQTT] DHT11 telemetry published.");
    }
    else
    {
        Serial.println("[MQTT] DHT11 telemetry publish failed.");
    }
}

void publishDhtTelemetryIfDue()
{
    if (!mqttClient.connected())
    {
        return;
    }

    const unsigned long now = millis();
    if (lastTelemetryPublishAt != 0 && now - lastTelemetryPublishAt < telemetryIntervalMs)
    {
        return;
    }

    lastTelemetryPublishAt = now;
    publishDhtTelemetry();
}

void resetCommandRequest(CommandRequest &request)
{
    request.type = COMMAND_TYPE_UNKNOWN;
    snprintf(request.command, sizeof(request.command), "%s", UNKNOWN_COMMAND_NAME);
    request.hasIntervalSeconds = false;
    request.intervalSeconds = 0;
    request.intervalError = nullptr;
}

void copyCommandName(CommandRequest &request, const char *commandName)
{
    snprintf(request.command, sizeof(request.command), "%s", commandName);
}

bool parseCommandPayload(const char *payload, CommandRequest &request, const char *&error)
{
    resetCommandRequest(request);
    error = nullptr;

    // The command document is intentionally small and bounded; unsupported
    // fields are ignored so future commands can add fields without breaking.
    StaticJsonDocument<256> document;
    const DeserializationError jsonError = deserializeJson(document, payload);
    if (jsonError)
    {
        error = ERROR_MALFORMED_JSON;
        return false;
    }

    const char *commandName = document["command"] | "";
    if (commandName[0] == '\0')
    {
        error = ERROR_MISSING_COMMAND;
        return false;
    }

    copyCommandName(request, commandName);

    if (strcmp(commandName, COMMAND_READ_NOW) == 0)
    {
        request.type = COMMAND_TYPE_READ_NOW;
        return true;
    }

    if (strcmp(commandName, COMMAND_SET_INTERVAL) == 0)
    {
        request.type = COMMAND_TYPE_SET_INTERVAL;

        JsonVariant intervalValue = document["interval_seconds"];
        if (intervalValue.isNull())
        {
            request.intervalError = ERROR_MISSING_INTERVAL_SECONDS;
            return true;
        }

        if (!intervalValue.is<unsigned long>())
        {
            request.intervalError = ERROR_INVALID_INTERVAL_SECONDS;
            return true;
        }

        request.intervalSeconds = intervalValue.as<unsigned long>();
        request.hasIntervalSeconds = true;
        return true;
    }

    request.type = COMMAND_TYPE_UNKNOWN;
    return true;
}

bool publishCommandResponse(
    const char *command,
    bool success,
    const char *error,
    unsigned long intervalSeconds,
    bool includeIntervalSeconds)
{
    StaticJsonDocument<192> response;
    response["device"] = DEVICE_ID;
    response["command"] = command != nullptr && command[0] != '\0' ? command : UNKNOWN_COMMAND_NAME;
    response["success"] = success;

    if (success && includeIntervalSeconds)
    {
        response["interval_seconds"] = intervalSeconds;
    }
    else if (!success)
    {
        response["error"] = error != nullptr ? error : ERROR_UNKNOWN_COMMAND;
    }

    char responsePayload[COMMAND_RESPONSE_BUFFER_SIZE];
    const size_t written = serializeJson(response, responsePayload, sizeof(responsePayload));
    if (written == 0 || written >= sizeof(responsePayload))
    {
        Serial.println("[Command] Response payload too large; publish skipped.");
        return false;
    }

    Serial.print("[Command] Response: ");
    Serial.println(responsePayload);

    if (mqttClient.publish(RESPONSES_TOPIC, responsePayload))
    {
        Serial.println("[MQTT] Command response published.");
        return true;
    }

    Serial.println("[MQTT] Command response publish failed.");
    return false;
}

void executeCommand(const CommandRequest &request)
{
    Serial.print("[Command] Executing: ");
    Serial.println(request.command);

    if (request.type == COMMAND_TYPE_READ_NOW)
    {
        Serial.println("[Command] read_now accepted; publishing telemetry immediately.");
        publishDhtTelemetry();
        publishCommandResponse(request.command, true);
        return;
    }

    if (request.type == COMMAND_TYPE_SET_INTERVAL)
    {
        if (!request.hasIntervalSeconds)
        {
            const char *error = request.intervalError != nullptr ? request.intervalError : ERROR_MISSING_INTERVAL_SECONDS;
            Serial.print("[Command] set_interval rejected: ");
            Serial.println(error);
            publishCommandResponse(request.command, false, error);
            return;
        }

        if (request.intervalSeconds < MIN_TELEMETRY_INTERVAL_SECONDS ||
            request.intervalSeconds > MAX_TELEMETRY_INTERVAL_SECONDS)
        {
            Serial.println("[Command] set_interval rejected: interval out of range.");
            publishCommandResponse(request.command, false, ERROR_INTERVAL_OUT_OF_RANGE);
            return;
        }

        telemetryIntervalMs = request.intervalSeconds * 1000UL;
        Serial.print("[Command] Telemetry interval updated to ");
        Serial.print(request.intervalSeconds);
        Serial.println(" seconds. This temporary setting is not persisted.");
        publishCommandResponse(request.command, true, nullptr, request.intervalSeconds, true);
        return;
    }

    Serial.println("[Command] Rejected: unknown command.");
    publishCommandResponse(request.command, false, ERROR_UNKNOWN_COMMAND);
}

void processCommandPayload(const char *payload)
{
    CommandRequest request;
    const char *parseError = nullptr;

    if (!parseCommandPayload(payload, request, parseError))
    {
        Serial.print("[Command] Rejected: ");
        Serial.println(parseError);
        publishCommandResponse(request.command, false, parseError);
        return;
    }

    executeCommand(request);
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
    Serial.print("[Sensor] DHT11 data pin GPIO");
    Serial.println(DHT_PIN);

    dht.begin();
    setupMQTT();
    beginWiFiConnection();
}

void loop()
{
    maintainWiFiConnection();
    maintainMQTTConnection();
    publishStatusIfDue();
    publishDhtTelemetryIfDue();
}
