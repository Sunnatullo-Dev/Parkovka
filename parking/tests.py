import json
from decimal import Decimal
from django.test import TestCase, Client
from django.utils import timezone
from datetime import datetime, timedelta
from parking.models import ParkingSpot, ParkingSession, ParkingSetting, ParkingSubscription, ParkingShift

class CommercialParkingTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Create different spots
        self.spot_std = ParkingSpot.objects.create(code="A1", spot_type="STANDARD")
        self.spot_vip = ParkingSpot.objects.create(code="A9", spot_type="VIP")
        
        # Seed settings (every minute paid, free_minutes = 0)
        ParkingSetting.objects.create(key="hourly_rate", value="10000")
        ParkingSetting.objects.create(key="free_minutes", value="0")
        ParkingSetting.objects.create(key="min_charge_amount", value="0")
        ParkingSetting.objects.create(key="min_charge_duration", value="0")
        ParkingSetting.objects.create(key="daily_max_cap", value="80000")
        ParkingSetting.objects.create(key="lost_ticket_penalty", value="50000")
        
        # Seed active subscriber
        self.sub = ParkingSubscription.objects.create(
            plate="01A777AA",
            owner_name="Samandarov Sunnatulla",
            expiry_date=timezone.localdate() + timedelta(days=30),
            is_active=True
        )

    def test_shift_restriction_enforcement(self):
        """Verifies session check-in fails if no shift is currently open."""
        # No shift open yet
        response = self.client.post(
            '/api/start-session/',
            data=json.dumps({'spot_code': 'A1', 'plate': '01X999XX'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
        self.assertEqual(response.json()['error'], 'Smena ochilmagan! Iltimos, oldin yangi smena oching.')

    def test_minute_billing_without_free_minutes(self):
        """Verifies 5 minutes parking calculates correct minute rate rounded to nearest 100 UZS."""
        # Standard rate: 10,000 UZS / hour = 166.67 UZS / minute.
        # 5 minutes: 5 * 166.67 = 833.33 UZS.
        # Rounded to nearest 100 UZS: 800 UZS.
        entry = timezone.now() - timedelta(minutes=5)
        session = ParkingSession.objects.create(
            spot=self.spot_std,
            plate="01X999XX",
            entry_time=entry,
            exit_time=timezone.now()
        )
        
        # Billing details
        minutes, amount = session.calculate_fee(10000.0, 0, 0, 0, 80000, 50000)
        self.assertAlmostEqual(minutes, 5.0, delta=0.5)
        self.assertEqual(amount, 800)

    def test_daily_capping_limit(self):
        """
        Verifies billing caps at 80,000 UZS per 24 hours.
        For 28 hours (1 day + 4 hours):
        Day 1: capped at 80,000 UZS.
        Extra 4 hours: 4 * 10,000 UZS = 40,000 UZS (less than cap, so no extra capping).
        Total standard: 120,000 UZS.
        
        For VIP (multiplier 2x):
        Base amount = 120,000 UZS.
        Total VIP = 120,000 * 2 = 240,000 UZS.
        """
        # Test Standard Spot capping
        entry_std = timezone.now() - timedelta(hours=28)
        session_std = ParkingSession.objects.create(
            spot=self.spot_std,
            plate="01X999XX",
            entry_time=entry_std,
            exit_time=timezone.now()
        )
        _, amount_std = session_std.calculate_fee(10000.0, 0, 0, 0, 80000, 50000)
        self.assertEqual(amount_std, 120000)

        # Test VIP Spot capping
        entry_vip = timezone.now() - timedelta(hours=28)
        session_vip = ParkingSession.objects.create(
            spot=self.spot_vip,
            plate="01X999XX",
            entry_time=entry_vip,
            exit_time=timezone.now()
        )
        _, amount_vip = session_vip.calculate_fee(10000.0, 0, 0, 0, 80000, 50000)
        self.assertEqual(amount_vip, 240000)

    def test_lost_ticket_penalty(self):
        """Verifies lost ticket flag triggers flat lost_ticket_penalty charge."""
        session = ParkingSession.objects.create(
            spot=self.spot_std,
            plate="01X999XX",
            entry_time=timezone.now() - timedelta(hours=5),
            exit_time=timezone.now(),
            is_lost_ticket=True
        )
        _, amount = session.calculate_fee(10000.0, 0, 0, 0, 80000, 50000)
        self.assertEqual(amount, 50000)

    def test_monthly_subscriptions_bypass_fee(self):
        """Verifies registered monthly subscriber plate starts SUBSCRIBED session with 0 UZS bill."""
        # Open shift
        shift = ParkingShift.objects.create(guard_name="Sunnatulla", is_active=True)
        
        # Start session for subscriber plate
        response = self.client.post(
            '/api/start-session/',
            data=json.dumps({'spot_code': 'A1', 'plate': '01A777AA'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['session_type'], 'SUBSCRIBED')
        
        session = ParkingSession.objects.get(id=response.json()['session_id'])
        self.assertEqual(session.session_type, 'SUBSCRIBED')
        
        # Check fee
        _, amount = session.calculate_fee(10000.0, 0, 0, 0, 80000, 50000)
        self.assertEqual(amount, 0)

    def test_admin_permissions_enforcement(self):
        """Verifies admin permission restrictions on settings update and subscription changes."""
        from django.contrib.auth.models import User
        admin_user = User.objects.create_superuser('testadmin', 'admin@test.com', 'pass123')
        
        # Test 1: Update rate fails for guest
        response = self.client.post(
            '/api/update-rate/',
            data=json.dumps({'hourly_rate': '15000'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)

        # Test 2: Update rate succeeds for admin
        self.client.login(username='testadmin', password='pass123')
        response = self.client.post(
            '/api/update-rate/',
            data=json.dumps({'hourly_rate': '15000'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['settings']['hourly_rate'], 15000)

        # Test 3: Delete subscription fails for guest after logout
        self.client.logout()
        response = self.client.delete(f"/api/subscriptions/?id={self.sub.id}")
        self.assertEqual(response.status_code, 403)

        # Test 4: Delete subscription succeeds for admin
        self.client.login(username='testadmin', password='pass123')
        response = self.client.delete(f"/api/subscriptions/?id={self.sub.id}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ParkingSubscription.objects.filter(id=self.sub.id).exists())
