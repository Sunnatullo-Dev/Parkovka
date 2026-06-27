"""Parking tariff defaults shared across models, views, and management commands."""

PARKING_SETTING_DEFAULTS = {
    'hourly_rate': ('10000', 'Parking fee rate per hour in UZS'),
    'free_minutes': ('0', 'Number of initial minutes that are free of charge (0 = bill immediately)'),
    'min_charge_amount': ('0', 'Minimum charge amount in UZS (0 = minute billing)'),
    'min_charge_duration': ('0', 'Minimum charge duration in minutes'),
    'daily_max_cap': ('80000', 'Maximum parking charge amount per 24 hours in UZS'),
    'lost_ticket_penalty': ('50000', 'Flat rate penalty fee for losing check-in ticket in UZS'),
}

NUMERIC_SETTING_KEYS = tuple(PARKING_SETTING_DEFAULTS.keys())

SPOT_MULTIPLIERS = {
    'VIP': 2.0,
    'DISABLED': 0.0,
    'RESERVED': 1.5,
    'STANDARD': 1.0,
}
