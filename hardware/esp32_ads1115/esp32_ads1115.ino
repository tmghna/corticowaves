#include <Wire.h>
#include <Adafruit_ADS1X15.h>

// Change these values to match the wiring and acquisition requirements.
constexpr int I2C_SDA_PIN = 21;
constexpr int I2C_SCL_PIN = 22;
constexpr uint8_t ADS1115_I2C_ADDRESS = 0x48;  // ADDR connected to GND
constexpr uint8_t ADS1115_CHANNEL = 0;         // A0
constexpr uint16_t SAMPLE_RATE_HZ = 250;
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t STARTUP_DELAY_MS = 2000;
constexpr uint32_t ADS_RETRY_INTERVAL_MS = 2000;
constexpr uint16_t I2C_TIMEOUT_MS = 20;
constexpr adsGain_t ADS1115_GAIN = GAIN_TWOTHIRDS;
constexpr const char *CHANNEL_NAME = "A0";
constexpr const char *GAIN_NAME = "2/3";

Adafruit_ADS1115 ads;
uint32_t sequenceNumber = 0;
uint32_t nextSampleMicros = 0;
uint32_t lastAdsRetryMillis = 0;
uint32_t lastStatusMillis = 0;
bool adsReady = false;

void printReady() {
  Serial.printf(
      "READY,%u,%s,%s\n",
      SAMPLE_RATE_HZ,
      CHANNEL_NAME,
      GAIN_NAME
  );
}

bool initializeAds() {
  if (!ads.begin(ADS1115_I2C_ADDRESS, &Wire)) {
    Serial.println("ERROR,ADS1115_NOT_FOUND");
    return false;
  }
  ads.setGain(ADS1115_GAIN);
  ads.setDataRate(RATE_ADS1115_250SPS);
  Serial.println("ADS1115,CONNECTED");
  return true;
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(STARTUP_DELAY_MS);
  Serial.println("BOOT,CORTICOWAVES_ESP32");
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  adsReady = initializeAds();
  if (adsReady) {
    printReady();
    lastStatusMillis = millis();
  }
  nextSampleMicros = micros();
}

void loop() {
  if (!adsReady) {
    const uint32_t nowMillis = millis();
    if (nowMillis - lastAdsRetryMillis >= ADS_RETRY_INTERVAL_MS) {
      lastAdsRetryMillis = nowMillis;
      adsReady = initializeAds();
      if (adsReady) {
        printReady();
        lastStatusMillis = nowMillis;
        nextSampleMicros = micros();
      }
    }
    delay(1);
    return;
  }

  if (millis() - lastStatusMillis >= ADS_RETRY_INTERVAL_MS) {
    printReady();
    lastStatusMillis = millis();
  }

  const uint32_t intervalMicros = 1000000UL / SAMPLE_RATE_HZ;
  const uint32_t now = micros();
  if ((int32_t)(now - nextSampleMicros) < 0) {
    return;
  }
  nextSampleMicros += intervalMicros;

  const int16_t adc = ads.readADC_SingleEnded(ADS1115_CHANNEL);
  if (adc < 0) {
    Serial.println("ERROR,ADS1115_READ_FAILED");
    adsReady = false;
    return;
  }
  const float voltage = ads.computeVolts(adc);
  // Compact CSV keeps 250 SPS reliable at the stable 115200 baud rate.
  Serial.printf("S,%lu,%lu,%d,%.6f\n",
    static_cast<unsigned long>(sequenceNumber++),
    static_cast<unsigned long>(micros()),
    adc,
    voltage
  );
}
