import spidev


class ADS1256:
    def __init__(self, bus=0, device=0):
        self.spi = spidev.SpiDev()
        self.bus = bus
        self.device = device

    def open(self):
        self.spi.open(self.bus, self.device)

        # ADS1256 unterstützt bis ca. 2 MHz SPI.
        # Wir beginnen konservativ mit 1 MHz.
        self.spi.max_speed_hz = 1_000_000

        # SPI Mode 1 laut Datenblatt
        self.spi.mode = 0b01

    def close(self):
        self.spi.close()

    def transfer(self, data):
        return self.spi.xfer2(data)