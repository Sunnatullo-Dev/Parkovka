import json
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from datetime import timedelta
from parking.models import ParkingSpot, ParkingSession, ParkingSetting

class ParkingSystemTests(TestCase):
    def setUp(self):
        # Create standard test client
        self.client = Client()
        
        # Create test spot
        self.spot = ParkingSpot.objects.create(code="A1")
        
        # Create default hourly rate setting
        self.rate_setting = ParkingSetting.objects.create(
            key="hourly_rate",
            value="10000",
            description="Hourly rate"
        )

    def test_fee_calculation(self):
        """
        Verify that fee calculation behaves according to formula:
        minutes = duration_in_seconds / 60
        amount = minutes * (hourly_rate / 60)
        For 3 hours and 30 minutes (210 minutes) with 10,000 UZS/hour rate:
        amount should be exactly 35,000 UZS.
        """
        entry = timezone.now() - timedelta(hours=3, minutes=30)
        session = ParkingSession.objects.create(
            spot=self.spot,
            plate="01A123BC",
            entry_time=entry,
            exit_time=timezone.now()
        )
        
        minutes, amount = session.calculate_fee(10000.0)
        
        self.assertAlmostEqual(minutes, 210.0, places=2)
        self.assertEqual(amount, 35000)

    def test_api_start_session_success(self):
        """Verify checking in a car occupies the spot and starts a session."""
        response = self.client.post(
            '/api/start-session/',
            data=json.dumps({'spot_code': 'A1', 'plate': '01A123BC'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['plate'], '01A123BC')
        self.assertEqual(data['spot_code'], 'A1')
        
        # Verify spot state in DB
        self.spot.refresh_from_db()
        self.assertTrue(self.spot.is_occupied)
        
        # Verify session state in DB
        session = ParkingSession.objects.get(id=data['session_id'])
        self.assertTrue(session.is_active)
        self.assertEqual(session.plate, '01A123BC')

    def test_api_start_session_already_occupied(self):
        """Verify you cannot start a session on a spot that is already occupied."""
        # Occupy the spot
        self.spot.is_occupied = True
        self.spot.save()
        
        response = self.client.post(
            '/api/start-session/',
            data=json.dumps({'spot_code': 'A1', 'plate': '01A123BC'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
        self.assertEqual(response.json()['error'], "'A1' joyi hozirda band.")

    def test_api_end_session_success(self):
        """Verify checking out ends the session, calculates fee, and frees the spot."""
        # Start a session manually 1 hour ago
        entry = timezone.now() - timedelta(hours=1)
        self.spot.is_occupied = True
        self.spot.save()
        
        session = ParkingSession.objects.create(
            spot=self.spot,
            plate="01A123BC",
            entry_time=entry,
            is_active=True
        )
        
        response = self.client.post(
            '/api/end-session/',
            data=json.dumps({'session_id': session.id}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # 1 hour duration => 60 minutes. 60 * (10000 / 60) = 10,000 UZS.
        self.assertAlmostEqual(data['total_minutes'], 60.0, delta=1.0)
        self.assertAlmostEqual(data['amount'], 10000, delta=200)
        
        # Verify spot state in DB is now empty
        self.spot.refresh_from_db()
        self.assertFalse(self.spot.is_occupied)
        
        # Verify session state in DB is now closed
        session.refresh_from_db()
        self.assertFalse(session.is_active)
        self.assertIsNotNone(session.exit_time)
        self.assertAlmostEqual(float(session.amount), 10000.0, delta=200)

    def test_api_update_rate(self):
        """Verify rate is updated successfully."""
        response = self.client.post(
            '/api/update-rate/',
            data=json.dumps({'hourly_rate': '15000'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['hourly_rate'], 15000)
        
        # Check database setting value
        self.rate_setting.refresh_from_db()
        self.assertEqual(self.rate_setting.value, '15000')
