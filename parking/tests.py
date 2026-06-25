import json
import csv
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from datetime import timedelta
from parking.models import ParkingSpot, ParkingSession, ParkingSetting

class ParkingSystemTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Create different spot types
        self.spot_standard = ParkingSpot.objects.create(code="A1", spot_type="STANDARD")
        self.spot_vip = ParkingSpot.objects.create(code="A9", spot_type="VIP")
        self.spot_disabled = ParkingSpot.objects.create(code="A2", spot_type="DISABLED")
        
        # Seed settings
        ParkingSetting.objects.create(key="hourly_rate", value="10000")
        ParkingSetting.objects.create(key="free_minutes", value="10")
        ParkingSetting.objects.create(key="min_charge_amount", value="5000")
        ParkingSetting.objects.create(key="min_charge_duration", value="60")

    def test_fee_calculation_free_minutes(self):
        """Verifies duration <= free_minutes results in 0 UZS."""
        entry = timezone.now() - timedelta(minutes=8)
        session = ParkingSession.objects.create(
            spot=self.spot_standard,
            plate="01A123BC",
            entry_time=entry,
            exit_time=timezone.now()
        )
        
        # Calculate
        minutes, amount = session.calculate_fee(10000.0, 10, 5000, 60)
        self.assertAlmostEqual(minutes, 8.0, delta=0.5)
        self.assertEqual(amount, 0)

    def test_fee_calculation_min_charge(self):
        """Verifies minutes <= min_charge_duration results in min_charge_amount."""
        entry = timezone.now() - timedelta(minutes=45)
        session = ParkingSession.objects.create(
            spot=self.spot_standard,
            plate="01A123BC",
            entry_time=entry,
            exit_time=timezone.now()
        )
        
        minutes, amount = session.calculate_fee(10000.0, 10, 5000, 60)
        self.assertAlmostEqual(minutes, 45.0, delta=0.5)
        self.assertEqual(amount, 5000)

    def test_fee_calculation_long_duration(self):
        """
        Verifies duration > min_charge_duration adds minute rate.
        For 90 minutes standard spot:
        60 minutes = 5000 UZS
        30 extra minutes at 10000 UZS/hour = 30 * (10000 / 60) = 5000 UZS.
        Total standard: 10,000 UZS.
        """
        entry = timezone.now() - timedelta(minutes=90)
        session = ParkingSession.objects.create(
            spot=self.spot_standard,
            plate="01A123BC",
            entry_time=entry,
            exit_time=timezone.now()
        )
        
        minutes, amount = session.calculate_fee(10000.0, 10, 5000, 60)
        self.assertAlmostEqual(minutes, 90.0, delta=0.5)
        self.assertEqual(amount, 10000)

    def test_fee_calculation_vip_multiplier(self):
        """Verifies VIP spot doubles the calculation total."""
        entry = timezone.now() - timedelta(minutes=90)
        session = ParkingSession.objects.create(
            spot=self.spot_vip,
            plate="01A123BC",
            entry_time=entry,
            exit_time=timezone.now()
        )
        
        # Standard calculation is 10,000 UZS. For VIP it should be 20,000 UZS.
        minutes, amount = session.calculate_fee(10000.0, 10, 5000, 60)
        self.assertEqual(amount, 20000)

    def test_fee_calculation_disabled_free(self):
        """Verifies Disabled spot is always free (0 UZS)."""
        entry = timezone.now() - timedelta(minutes=180) # 3 hours
        session = ParkingSession.objects.create(
            spot=self.spot_disabled,
            plate="01A123BC",
            entry_time=entry,
            exit_time=timezone.now()
        )
        
        minutes, amount = session.calculate_fee(10000.0, 10, 5000, 60)
        self.assertEqual(amount, 0)

    def test_api_export_csv_headers(self):
        """Verifies CSV export endpoint returns text/csv format and attachment header."""
        # Create a closed session to export
        session = ParkingSession.objects.create(
            spot=self.spot_standard,
            plate="01A123BC",
            entry_time=timezone.now() - timedelta(hours=1),
            exit_time=timezone.now(),
            total_minutes=60,
            amount=Decimal('5000'),
            is_active=False
        )
        
        response = self.client.get('/api/export-csv/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="parking_history.csv"', response['Content-Disposition'])

    def test_api_history_filtering(self):
        """Verifies history report filtering by date and license plate."""
        # Create closed session
        session = ParkingSession.objects.create(
            spot=self.spot_standard,
            plate="99X999XX",
            entry_time=timezone.now() - timedelta(hours=2),
            exit_time=timezone.now(),
            total_minutes=120,
            amount=Decimal('15000'),
            is_active=False
        )
        
        # Query with match
        response = self.client.get('/api/history-report/?plate=99X999')
        data = response.json()
        self.assertEqual(data['total_count'], 1)
        self.assertEqual(data['sessions'][0]['plate'], '99X999XX')
        
        # Query with non-match
        response_nomatch = self.client.get('/api/history-report/?plate=01A')
        self.assertEqual(response_nomatch.json()['total_count'], 0)
