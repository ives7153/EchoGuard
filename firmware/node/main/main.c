#include <stdint.h>
#include <stdio.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "rescue_node";

static void init_board_status(void)
{
    ESP_LOGI(TAG, "Board status resources initialized");
}

static void init_sensor_pipeline(void)
{
    ESP_LOGI(TAG, "Sensor pipeline initialized");
}

static void init_wifi_csi_pipeline(void)
{
    ESP_LOGI(TAG, "WiFi CSI pipeline initialized");
}

static void init_lora_uplink(void)
{
    ESP_LOGI(TAG, "LoRa uplink initialized");
}

static void node_heartbeat_task(void *arg)
{
    (void)arg;

    uint32_t counter = 0;
    while (true) {
        ESP_LOGI(TAG, "Rescue node running, heartbeat=%lu", (unsigned long)counter++);
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "ESP32-S3 WiFi CSI + LoRa rescue node starting");

    init_board_status();
    init_sensor_pipeline();
    init_wifi_csi_pipeline();
    init_lora_uplink();

    xTaskCreate(node_heartbeat_task, "node_heartbeat", 4096, NULL, 5, NULL);
}
