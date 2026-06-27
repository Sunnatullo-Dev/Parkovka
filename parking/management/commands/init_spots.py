from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from parking.constants import PARKING_SETTING_DEFAULTS
from parking.models import ParkingSpot, ParkingSetting, ParkingSubscription

class Command(BaseCommand):
    help = 'Initializes default parking spots, subscriptions, and advanced commercial settings'

    def handle(self, *args, **options):
        # 1. Initialize settings
        for key, (value, description) in PARKING_SETTING_DEFAULTS.items():
            setting, created = ParkingSetting.objects.get_or_create(
                key=key,
                defaults={'value': value, 'description': description},
            )
            if not created:
                setting.value = value
                setting.description = description
                setting.save()
            self.stdout.write(self.style.SUCCESS(f"Setting '{key}' initialized to '{value}'."))

        # 2. Initialize spots
        vip_spots = {'A9', 'A10', 'B9', 'B10'}
        disabled_spots = {'A1', 'B1'}

        spots_created_count = 0
        spots_updated_count = 0

        for section in ['A', 'B']:
            for num in range(1, 11):
                code = f"{section}{num}"
                
                # Determine spot type
                if code in vip_spots:
                    spot_type = 'VIP'
                elif code in disabled_spots:
                    spot_type = 'DISABLED'
                else:
                    spot_type = 'STANDARD'

                spot, created = ParkingSpot.objects.get_or_create(
                    code=code,
                    defaults={'spot_type': spot_type}
                )
                
                if created:
                    spots_created_count += 1
                else:
                    if spot.spot_type != spot_type:
                        spot.spot_type = spot_type
                        spot.save()
                        spots_updated_count += 1

        if spots_created_count > 0:
            self.stdout.write(self.style.SUCCESS(f"Created {spots_created_count} parking spots."))
        if spots_updated_count > 0:
            self.stdout.write(self.style.SUCCESS(f"Updated {spots_updated_count} parking spots to VIP/Disabled/Standard types."))

        # 3. Seed active subscribers (monthly abonement)
        subscribers_to_seed = [
            {
                'plate': '01A777AA',
                'owner_name': 'Samandarov Sunnatulla',
                'expiry_days': 30
            },
            {
                'plate': '01777AAA',
                'owner_name': 'Lazizbekov Shaxzod',
                'expiry_days': 30
            }
        ]

        for sub_data in subscribers_to_seed:
            sub, created = ParkingSubscription.objects.get_or_create(
                plate=sub_data['plate'],
                defaults={
                    'owner_name': sub_data['owner_name'],
                    'expiry_date': timezone.localdate() + timedelta(days=sub_data['expiry_days']),
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Subscription seeded for {sub_data['plate']} ({sub_data['owner_name']})."))
            else:
                sub.expiry_date = timezone.localdate() + timedelta(days=sub_data['expiry_days'])
                sub.is_active = True
                sub.save()
        
        # 4. Create default superuser if it doesn't exist
        from django.contrib.auth.models import User
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
            self.stdout.write(self.style.SUCCESS("Superuser 'admin' created with password 'admin123'."))
        
        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully."))
