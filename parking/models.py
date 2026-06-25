from django.db import models
from django.utils import timezone

class ParkingSpot(models.Model):
    SPOT_TYPES = [
        ('STANDARD', 'Standard'),
        ('VIP', 'VIP'),
        ('DISABLED', 'Nogironlar'),
    ]

    code = models.CharField(max_length=10, unique=True)
    is_occupied = models.BooleanField(default=False)
    spot_type = models.CharField(max_length=15, choices=SPOT_TYPES, default='STANDARD')

    def get_multiplier(self):
        if self.spot_type == 'VIP':
            return 2.0
        elif self.spot_type == 'DISABLED':
            return 0.0  # Free parking for disabled individuals
        return 1.0

    def __str__(self):
        return f"{self.code} ({self.get_spot_type_display()})"

    class Meta:
        ordering = ['code']

class ParkingSession(models.Model):
    spot = models.ForeignKey(ParkingSpot, on_delete=models.CASCADE, related_name='sessions')
    plate = models.CharField(max_length=20)
    entry_time = models.DateTimeField(default=timezone.now)
    exit_time = models.DateTimeField(null=True, blank=True)
    total_minutes = models.FloatField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def calculate_fee(self, hourly_rate, free_minutes=10, min_charge_amount=5000, min_charge_duration=60):
        """
        Calculates fee based on advanced logic:
        1. If duration <= free_minutes => amount = 0.
        2. Else if duration <= min_charge_duration => amount = min_charge_amount * multiplier.
        3. Else => amount = (min_charge_amount + (duration - min_charge_duration) * (hourly_rate / 60)) * multiplier.
        The amount is rounded to the nearest 100 UZS.
        """
        end_time = self.exit_time if self.exit_time else timezone.now()
        duration = end_time - self.entry_time
        duration_seconds = max(0.0, duration.total_seconds())
        minutes = duration_seconds / 60.0
        
        multiplier = float(self.spot.get_multiplier())
        
        if minutes <= free_minutes:
            calculated_amount = 0.0
        elif minutes <= min_charge_duration:
            calculated_amount = float(min_charge_amount) * multiplier
        else:
            extra_minutes = minutes - float(min_charge_duration)
            rate_per_minute = float(hourly_rate) / 60.0
            base_amount = float(min_charge_amount) + (extra_minutes * rate_per_minute)
            calculated_amount = base_amount * multiplier
            
        # Round to the nearest 100 UZS
        rounded_amount = round(calculated_amount / 100.0) * 100
        
        return minutes, int(rounded_amount)

    def __str__(self):
        status = "Active" if self.is_active else "Closed"
        return f"{self.plate} at {self.spot.code} ({status})"

    class Meta:
        ordering = ['-entry_time']

class ParkingSetting(models.Model):
    key = models.CharField(max_length=50, unique=True)
    value = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.key}: {self.value}"
