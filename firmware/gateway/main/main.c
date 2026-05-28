#include <stdint.h>
#include <stdio.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "rescue_gateway";

static void init_gateway_board(void)
{
    ESP_LOGI(TAG, "Gateway board resources initialized");
}

static void init_lora_downlink(void)
{
    ESP_LOGI(TAG, "LoRa receiver initialized");
}

static void init_upper_computer_link(void)
{
    ESP_LOGI(TAG, "Upper computer serial link initialized, baud=115200");
}

static void gateway_forward_task(void *arg)
{
    (void)arg;

    uint32_t counter = 0;
    while (true) {
        printf("NODE,1,CSI,%lu,RSSI,-55,TEMP,25.3,HUM,60.1\n", (unsigned long)counter++);
        fflush(stdout);
        ESP_LOGI(TAG, "Forwarded one sample frame to upper computer");
        vTaskDelay(pdMS_TO_TICKS(3000));
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "ESP32-S3 LoRa gateway starting");

    init_gateway_board();
    init_lora_downlink();
    init_upper_computer_link();

    xTaskCreate(gateway_forward_task, "gateway_forward", 4096, NULL, 5, NULL);
}
