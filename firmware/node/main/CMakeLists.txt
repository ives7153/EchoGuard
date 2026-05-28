idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_wifi
        esp_event
        esp_netif
        nvs_flash
        driver
        esp_adc
        esp_driver_gpio
        esp_driver_i2c
        esp_driver_spi
        esp_timer
)
