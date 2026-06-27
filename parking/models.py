from django.db import models
from django.utils import timezone

class ParkingSpot(models.Model):
    SPOT_TYPES = [
        ('STANDARD', 'Standard'),
        ('VIP', 'VIP'),
        ('DISABLED', 'Nogironlar'),
        ('RESERVED', 'Rezervlangan'),
    ]

    code = models.CharField(max_length=10, unique=True)
    is_occupied = models.BooleanField(default=False)
    spot_type = models.CharField(max_length=15, choices=SPOT_TYPES, default='STANDARD')

    def get_multiplier(self):
        if self.spot_type == 'VIP':
            return 2.0
        elif self.spot_type == 'DISABLED':
            return 0.0  # Free parking for disabled individuals
        elif self.spot_type == 'RESERVED':
            return 1.5  # Higher multiplier for reserved spots
        return 1.0

    def __str__(self):
        return f"{self.code} ({self.get_spot_type_display()})"

    class Meta:
        ordering = ['code']

class ParkingSubscription(models.Model):
    plate = models.CharField(max_length=20, unique=True)
    owner_name = models.CharField(max_length=100)
    expiry_date = models.DateField()
    is_active = models.BooleanField(default=True)

    def is_valid(self):
        return self.is_active and self.expiry_date >= timezone.localdate()

    def __str__(self):
        status = "Active" if self.is_valid() else "Expired"
        return f"Abonement: {self.plate} ({self.owner_name}) - {status}"

class ParkingShift(models.Model):
    guard_name = models.CharField(max_length=100)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        status = "Active" if self.is_active else f"Closed at {self.end_time}"
        return f"Shift by {self.guard_name} ({status})"

class ParkingSession(models.Model):
    SESSION_TYPES = [
        ('PAID', 'Standard'),
        ('SUBSCRIBED', 'Abonement'),
    ]

    spot = models.ForeignKey(ParkingSpot, on_delete=models.CASCADE, related_name='sessions')
    shift = models.ForeignKey(ParkingShift, on_delete=models.SET_NULL, null=True, blank=True, related_name='sessions')
    plate = models.CharField(max_length=20)
    entry_time = models.DateTimeField(default=timezone.now)
    exit_time = models.DateTimeField(null=True, blank=True)
    total_minutes = models.FloatField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    session_type = models.CharField(max_length=15, choices=SESSION_TYPES, default='PAID')
    is_lost_ticket = models.BooleanField(default=False)

    def calculate_fee(self, hourly_rate, free_minutes=0, min_charge_amount=0, min_charge_duration=0, daily_max_cap=80000, lost_ticket_penalty=50000):
        """
        Calculates fee based on advanced commercial logic:
        1. Subscriptions yield 0 UZS.
        2. Lost ticket yields flat penalty.
        3. Standard calculation: hourly rate, capping to daily_max_cap per 24 hours, and spot multiplier.
        All sums rounded to nearest 100 UZS.
        """
        if self.session_type == 'SUBSCRIBED':
            return 0.0, 0
            
        if self.is_lost_ticket:
            return 0.0, int(lost_ticket_penalty)
            
        end_time = self.exit_time if self.exit_time else timezone.now()
        duration = end_time - self.entry_time
        duration_seconds = max(0.0, duration.total_seconds())
        minutes = duration_seconds / 60.0
        
        multiplier = float(self.spot.get_multiplier())
        
        if minutes <= free_minutes:
            calculated_amount = 0.0
        else:
            # Daily capping calculator: calculate in 24h blocks (1440 minutes)
            days = int(minutes // 1440)
            rem_minutes = minutes % 1440
            
            # Remaining time cost calculation
            if rem_minutes <= min_charge_duration:
                rem_charge = float(min_charge_amount)
            else:
                extra_minutes = rem_minutes - float(min_charge_duration)
                rate_per_minute = float(hourly_rate) / 60.0
                rem_charge = float(min_charge_amount) + (extra_minutes * rate_per_minute)
                
            # Capping remaining cost
            rem_charge_capped = min(rem_charge, float(daily_max_cap))
            
            # Total base
            base_amount = (days * float(daily_max_cap)) + rem_charge_capped
            calculated_amount = base_amount * multiplier
            
        # Round to nearest 100 UZS
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

class ParkingNotification(models.Model):
    NOTIFICATION_TYPES = [
        ('TELEGRAM', 'Telegram Bot'),
        ('SMS', 'SMS Gateway'),
    ]
    
    notification_type = models.CharField(max_length=15, choices=NOTIFICATION_TYPES)
    recipient = models.CharField(max_length=50)
    message = models.TextField()
    sent_time = models.DateTimeField(default=timezone.now)
    
    def __str__(self):
        return f"[{self.get_notification_type_display()}] to {self.recipient} at {self.sent_time}"
        
    class Meta:
        ordering = ['-sent_time']
