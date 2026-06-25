from django.core.management.base import BaseCommand
from parking.models import ParkingSpot, ParkingSetting

class Command(BaseCommand):
    help = 'Initializes default parking spots (A1-A10, B1-B10) and default settings'

    def handle(self, *args, **options):
        # 1. Initialize settings
        rate_setting, created = ParkingSetting.objects.get_or_create(
            key='hourly_rate',
            defaults={
                'value': '10000',
                'description': 'Parking fee rate per hour in UZS'
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Default setting 'hourly_rate' created (10,000 UZS)."))
        else:
            self.stdout.write(self.style.WARNING("Setting 'hourly_rate' already exists."))

        # 2. Initialize spots
        spots_created_count = 0
        
        # We will create A1-A10 and B1-B10
        spots_to_create = []
        for section in ['A', 'B']:
            for num in range(1, 11):
                code = f"{section}{num}"
                spots_to_create.append(code)

        for code in spots_to_create:
            spot, created = ParkingSpot.objects.get_or_create(code=code)
            if created:
                spots_created_count += 1

        if spots_created_count > 0:
            self.stdout.write(self.style.SUCCESS(f"Successfully created {spots_created_count} parking spots."))
        else:
            self.stdout.write(self.style.WARNING("All parking spots already exist."))
