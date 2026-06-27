#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESP32Servo.h>
#include "esp_camera.h"
#include "esp_http_server.h"

// --- BROCHES MOTEURS ET KLAXON ---
const int PIN_DIRECTION = 2; // Broche D1
const int PIN_MOTEUR = 3;    // Broche D2
const int PIN_BUZZER = 4;    // Broche D3 (NOUVEAU)

const int NEUTRE_DIRECTION = 90; 
const int NEUTRE_MOTEUR = 90;    
Servo servoDirection;
Servo escMoteur;

const char *ssid = "Voiture_ZD_Racing";
const char *password = "12345678";
unsigned int localUdpPort = 4210;  
WiFiUDP udp;
unsigned long dernierMessageTemps = 0;

// --- BROCHES CAMÉRA ---
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     10
#define SIOD_GPIO_NUM     40
#define SIOC_GPIO_NUM     39
#define Y9_GPIO_NUM       48
#define Y8_GPIO_NUM       11
#define Y7_GPIO_NUM       12
#define Y6_GPIO_NUM       14
#define Y5_GPIO_NUM       16
#define Y4_GPIO_NUM       18
#define Y3_GPIO_NUM       17
#define Y2_GPIO_NUM       15
#define VSYNC_GPIO_NUM    38
#define HREF_GPIO_NUM     47
#define PCLK_GPIO_NUM     13

httpd_handle_t stream_httpd = NULL;

static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  size_t _jpg_buf_len = 0;
  uint8_t * _jpg_buf = NULL;
  char * part_buf[64];

  res = httpd_resp_set_type(req, "multipart/x-mixed-replace;boundary=123456789000000000000987654321");
  if (res != ESP_OK) return res;

  while (true) {
    fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
    } else {
      _jpg_buf_len = fb->len;
      _jpg_buf = fb->buf;
    }
    
    if (res == ESP_OK) {
      size_t hlen = snprintf((char *)part_buf, 64, "Content-Type: image/jpeg\r\nContent-Length: %zu\r\n\r\n", _jpg_buf_len);
      res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
    }
    if (res == ESP_OK) {
      res = httpd_resp_send_chunk(req, "\r\n--123456789000000000000987654321\r\n", 37);
    }
    
    if (fb) {
      esp_camera_fb_return(fb);
      fb = NULL;
      _jpg_buf = NULL;
    }
    if (res != ESP_OK) break;
  }
  return res;
}

void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  httpd_uri_t index_uri;
  index_uri.uri       = "/";
  index_uri.method    = HTTP_GET;
  index_uri.handler   = stream_handler;
  index_uri.user_ctx  = NULL;
  
  if (httpd_start(&stream_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &index_uri);
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW); // Klaxon éteint par défaut

  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);
  servoDirection.setPeriodHertz(50);
  escMoteur.setPeriodHertz(50);
  servoDirection.attach(PIN_DIRECTION, 1000, 2000);
  escMoteur.attach(PIN_MOTEUR, 1000, 2000);
  
  // --- MODIFICATION ICI : On donne plus de temps à l'ESC pour s'armer
  servoDirection.write(NEUTRE_DIRECTION);
  escMoteur.write(NEUTRE_MOTEUR);
  delay(3000); // 3 secondes d'attente au lieu de 1

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.frame_size = FRAMESIZE_VGA; 
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = 12;
  config.fb_count = 2; 

  esp_camera_init(&config);
  WiFi.softAP(ssid, password);
  startCameraServer();
  udp.begin(localUdpPort);
  
  // NOUVEAU : Réinitialise le timer de sécurité à la toute fin du démarrage
  dernierMessageTemps = millis(); 
}

void loop() {
  int packetSize = udp.parsePacket();
  if (packetSize) {
    char packetBuffer[255];
    int len = udp.read(packetBuffer, 255);
    if (len > 0) packetBuffer[len] = 0;
    
    String message = String(packetBuffer);
    
    // Le format est maintenant : "90,120,1" (Direction, Moteur, Klaxon)
    int indexV1 = message.indexOf(',');
    int indexV2 = message.lastIndexOf(',');
    
    if (indexV1 > 0 && indexV2 > indexV1) {
      servoDirection.write(message.substring(0, indexV1).toInt());
      escMoteur.write(message.substring(indexV1 + 1, indexV2).toInt());
      
      // Active ou désactive le buzzer
      int etatKlaxon = message.substring(indexV2 + 1).toInt();
      digitalWrite(PIN_BUZZER, etatKlaxon ? HIGH : LOW);
      
      dernierMessageTemps = millis();
    }
  }

  // --- MODIFICATION ICI : Sécurité anti-coupure assouplie (1 seconde au lieu de 0.5)
  if (millis() - dernierMessageTemps > 1000) {
    escMoteur.write(NEUTRE_MOTEUR);
    servoDirection.write(NEUTRE_DIRECTION);
    digitalWrite(PIN_BUZZER, LOW); // On coupe le klaxon
  }
}