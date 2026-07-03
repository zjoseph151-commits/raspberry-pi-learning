#include <Arduino.h>
#include <PubSubClient.h>
#include <WiFi.h>

// ---------------------------------------------------------------------------
// User configuration
// Update these values for your Wi-Fi network and Raspberry Pi MQTT broker.
// ---------------------------------------------------------------------------
const char *WIFI_SSID = "BananaHammock";
const char *WIFI_PASSWORD = "MoutainMan69!";

const char *MQTT_BROKER_IP = "10.0.0.179";
const uint16_t MQTT_PORT = 1883;
const char *MQTT_TOPIC = "home/esp32/status";
const char *MQTT_CLIENT_ID = "esp32-s3-heartbeat-client";

const unsigned long HEARTBEAT_INTERVAL_MS = 5000;
const unsigned long WIFI_RETRY_DELAY_MS = 500;
const unsigned long MQTT_RETRY_DELAY_MS = 5000;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

unsigned long lastHeartbeatAt = 0;
unsigned long heartbeatCount = 0;

void printWiFiStatus()
{
    Serial.println("[WiFi] Connected.");
    Serial.print("[WiFi] IP address: ");
    Serial.println(WiFi.localIP());
    Serial.print("[WiFi] Signal strength (RSSI): ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
}

void connectToWiFi()
{
    if (WiFi.status() == WL_CONNECTED)
    {
        return;
    }

    Serial.println();
    Serial.print("[WiFi] Connecting to SSID: ");
    Serial.println(WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned int attempt = 1;
    while (WiFi.status() != WL_CONNECTED)
    {
        Serial.print("[WiFi] Attempt ");
        Serial.print(attempt++);
        Serial.println(" failed; retrying...");
        delay(WIFI_RETRY_DELAY_MS);
    }

    printWiFiStatus();
}

void setupMQTT()
{
    mqttClient.setServer(MQTT_BROKER_IP, MQTT_PORT);

    Serial.print("[MQTT] Broker configured at ");
    Serial.print(MQTT_BROKER_IP);
    Serial.print(":");
    Serial.println(MQTT_PORT);
    Serial.print("[MQTT] Publish topic: ");
    Serial.println(MQTT_TOPIC);
}

void connectToMQTT()
{
    if (mqttClient.connected())
    {
        return;
    }

    unsigned int attempt = 1;
    while (!mqttClient.connected())
    {
        if (WiFi.status() != WL_CONNECTED)
        {
            Serial.println("[MQTT] Wi-Fi is disconnected; pausing MQTT reconnect.");
            return;
        }

        Serial.print("[MQTT] Connecting to broker, attempt ");
        Serial.print(attempt++);
        Serial.print(" as client '");
        Serial.print(MQTT_CLIENT_ID);
        Serial.println("'...");

        if (mqttClient.connect(MQTT_CLIENT_ID))
        {
            Serial.println("[MQTT] Connected to broker.");
        }
        else
        {
            Serial.print("[MQTT] Connection failed. State: ");
            Serial.print(mqttClient.state());
            Serial.print(". Retrying in ");
            Serial.print(MQTT_RETRY_DELAY_MS / 1000);
            Serial.println(" seconds...");
            delay(MQTT_RETRY_DELAY_MS);
        }
    }
}

void ensureWiFiConnected()
{
    if (WiFi.status() == WL_CONNECTED)
    {
        return;
    }

    Serial.println("[WiFi] Connection lost.");
    mqttClient.disconnect();
    connectToWiFi();
}

void ensureMQTTConnected()
{
    if (mqttClient.connected())
    {
        return;
    }

    Serial.println("[MQTT] Connection lost or not yet established.");
    connectToMQTT();
}

void publishHeartbeat()
{
    if (!mqttClient.connected())
    {
        Serial.println("[MQTT] Skipping heartbeat publish because MQTT is disconnected.");
        return;
    }

    const unsigned long now = millis();
    if (now - lastHeartbeatAt < HEARTBEAT_INTERVAL_MS)
    {
        return;
    }

    lastHeartbeatAt = now;
    heartbeatCount++;

    char payload[160];
    snprintf(
        payload,
        sizeof(payload),
        "{\"status\":\"online\",\"count\":%lu,\"uptime_ms\":%lu,\"ip\":\"%s\"}",
        heartbeatCount,
        now,
        WiFi.localIP().toString().c_str());

    const bool published = mqttClient.publish(MQTT_TOPIC, payload);

    Serial.print("[MQTT] Publishing heartbeat to ");
    Serial.print(MQTT_TOPIC);
    Serial.print(": ");
    Serial.println(payload);

    if (published)
    {
        Serial.println("[MQTT] Heartbeat published successfully.");
    }
    else
    {
        Serial.println("[MQTT] Heartbeat publish failed.");
    }
}

void setup()
{
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("[System] ESP32-S3 MQTT heartbeat starting.");

    connectToWiFi();
    setupMQTT();
    connectToMQTT();
}

void loop()
{
    // Keep the two connections healthy before doing MQTT work. If Wi-Fi drops,
    // reconnecting it first gives the broker client a valid network path again.
    ensureWiFiConnected();
    ensureMQTTConnected();

    mqttClient.loop();
    publishHeartbeat();
}
