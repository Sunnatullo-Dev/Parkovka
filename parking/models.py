from django.db import models
from django.utils import timezone

class ParkingSpot(models.Model):
    code = models.CharField(max_length=10, unique=True)
    is_occupied = models.BooleanField(default=False)

    def __str__(self):
        return self.code

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

    def calculate_fee(self, hourly_rate):
        """
        Calculates the active/completed session fee based on the hourly rate.
        Formula: total_minutes = duration_in_seconds / 60
                 amount = total_minutes * (hourly_rate / 60)
        """
        end_time = self.exit_time if self.exit_time else timezone.now()
        duration = end_time - self.entry_time
        duration_seconds = max(0.0, duration.total_seconds())
        minutes = duration_seconds / 60.0
        
        rate_per_minute = float(hourly_rate) / 60.0
        calculated_amount = round(minutes * rate_per_minute)
        
        return minutes, calculated_amount

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
