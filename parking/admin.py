from django.contrib import admin

from parking.models import (
    ParkingNotification,
    ParkingSession,
    ParkingSetting,
    ParkingShift,
    ParkingSpot,
    ParkingSubscription,
)


@admin.register(ParkingSpot)
class ParkingSpotAdmin(admin.ModelAdmin):
    list_display = ('code', 'spot_type', 'is_occupied')
    list_filter = ('spot_type', 'is_occupied')
    search_fields = ('code',)


@admin.register(ParkingSession)
class ParkingSessionAdmin(admin.ModelAdmin):
    list_display = ('plate', 'spot', 'session_type', 'is_active', 'entry_time', 'exit_time', 'amount')
    list_filter = ('is_active', 'session_type', 'is_lost_ticket')
    search_fields = ('plate', 'spot__code')
    readonly_fields = ('entry_time',)


@admin.register(ParkingSubscription)
class ParkingSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('plate', 'owner_name', 'expiry_date', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('plate', 'owner_name')


@admin.register(ParkingShift)
class ParkingShiftAdmin(admin.ModelAdmin):
    list_display = ('guard_name', 'start_time', 'end_time', 'is_active')
    list_filter = ('is_active',)


@admin.register(ParkingSetting)
class ParkingSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'description')
    search_fields = ('key',)


@admin.register(ParkingNotification)
class ParkingNotificationAdmin(admin.ModelAdmin):
    list_display = ('notification_type', 'recipient', 'sent_time')
    list_filter = ('notification_type',)
    readonly_fields = ('sent_time',)
