from django.core.management.base import BaseCommand
from parking.models import ParkingSpot, ParkingSetting

class Command(BaseCommand):
    help = 'Initializes default parking spots (A1-A10, B1-B10) with VIP/Disabled types and default settings'

    def handle(self, *args, **options):
        # 1. Initialize settings
        settings_to_seed = [
            {
                'key': 'hourly_rate',
                'value': '10000',
                'description': 'Parking fee rate per hour in UZS'
            },
            {
                'key': 'free_minutes',
                'value': '10',
                'description': 'Number of initial minutes that are free of charge'
            },
            {
                'key': 'min_charge_amount',
                'value': '5000',
                'description': 'Minimum charge amount in UZS'
            },
            {
                'key': 'min_charge_duration',
                'value': '60',
                'description': 'Minimum charge duration in minutes'
            }
        ]

        for setting_data in settings_to_seed:
            setting, created = ParkingSetting.objects.get_or_create(
                key=setting_data['key'],
                defaults={
                    'value': setting_data['value'],
                    'description': setting_data['description']
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Default setting '{setting_data['key']}' created with value '{setting_data['value']}'."))
            else:
                # Keep existing values but update description if needed
                setting.description = setting_data['description']
                setting.save()

        # 2. Initialize spots
        # VIP spots: A9, A10, B9, B10
        # Disabled spots: A1, B1
        # Standard: others
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
                    # Update spot_type to match configuration
                    if spot.spot_type != spot_type:
                        spot.spot_type = spot_type
                        spot.save()
                        spots_updated_count += 1

        if spots_created_count > 0:
            self.stdout.write(self.style.SUCCESS(f"Successfully created {spots_created_count} parking spots."))
        if spots_updated_count > 0:
            self.stdout.write(self.style.SUCCESS(f"Successfully updated {spots_updated_count} parking spots to correct types."))
        if spots_created_count == 0 and spots_updated_count == 0:
            self.stdout.write(self.style.WARNING("All parking spots already exist and are set up correctly."))
        
        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully."))
