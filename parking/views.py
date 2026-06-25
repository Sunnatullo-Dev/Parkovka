import json
from decimal import Decimal
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum

from parking.models import ParkingSpot, ParkingSession, ParkingSetting

# Helper function to get current hourly rate
def get_hourly_rate():
    try:
        setting = ParkingSetting.objects.get(key='hourly_rate')
        return float(setting.value)
    except ParkingSetting.DoesNotExist:
        return 10000.0

def dashboard_view(request):
    """Renders the main dashboard page."""
    # We will pass the current hourly rate to the template context
    context = {
        'hourly_rate': get_hourly_rate()
    }
    return render(request, 'parking/dashboard.html', context)

@require_http_methods(["GET"])
def api_spots(request):
    """Returns status of all parking spots."""
    spots = ParkingSpot.objects.all().order_by('code')
    spots_data = []
    
    # Pre-fetch active sessions to join active plate info with spots
    active_sessions = {s.spot_id: s for s in ParkingSession.objects.filter(is_active=True)}
    
    for spot in spots:
        session = active_sessions.get(spot.id)
        spots_data.append({
            'id': spot.id,
            'code': spot.code,
            'is_occupied': spot.is_occupied,
            'plate': session.plate if session else None,
            'session_id': session.id if session else None,
            'entry_time': session.entry_time.isoformat() if session else None
        })
    return JsonResponse({'spots': spots_data})

@require_http_methods(["GET"])
def api_active_sessions(request):
    """Returns list of currently active parking sessions."""
    sessions = ParkingSession.objects.filter(is_active=True).select_related('spot')
    data = [{
        'id': s.id,
        'spot_code': s.spot.code,
        'plate': s.plate,
        'entry_time': s.entry_time.isoformat()
    } for s in sessions]
    return JsonResponse({'sessions': data})

@csrf_exempt
@require_http_methods(["POST"])
def api_start_session(request):
    """Starts a new parking session."""
    try:
        data = json.loads(request.body)
        spot_code = data.get('spot_code')
        plate = data.get('plate', '').strip().upper()
        
        if not spot_code or not plate:
            return JsonResponse({'error': 'Joy kodi va davlat raqami kiritilishi shart.'}, status=400)
            
        with transaction.atomic():
            try:
                spot = ParkingSpot.objects.select_for_update().get(code=spot_code)
            except ParkingSpot.DoesNotExist:
                return JsonResponse({'error': f"'{spot_code}' kodi bo'yicha parking joyi topilmadi."}, status=404)
                
            if spot.is_occupied:
                return JsonResponse({'error': f"'{spot_code}' joyi hozirda band."}, status=400)
                
            # Check if there is already an active session with the same plate
            # to prevent a car from double parking
            if ParkingSession.objects.filter(plate=plate, is_active=True).exists():
                return JsonResponse({'error': f"'{plate}' raqamli mashina uchun faol sessiya allaqachon mavjud."}, status=400)
                
            # Create session
            session = ParkingSession.objects.create(
                spot=spot,
                plate=plate,
                entry_time=timezone.now(),
                is_active=True
            )
            
            # Mark spot as occupied
            spot.is_occupied = True
            spot.save()
            
            return JsonResponse({
                'message': 'Sessiya muvaffaqiyatli boshlandi.',
                'session_id': session.id,
                'spot_code': spot.code,
                'plate': session.plate,
                'entry_time': session.entry_time.isoformat()
            })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def api_calculate_fee(request):
    """Calculates active session fee in real-time."""
    session_id = request.GET.get('session_id')
    if not session_id:
        return JsonResponse({'error': 'Sessiya ID kiritilishi shart.'}, status=400)
        
    try:
        session = ParkingSession.objects.select_related('spot').get(id=session_id)
        if not session.is_active:
            return JsonResponse({
                'is_active': False,
                'total_minutes': session.total_minutes,
                'amount': float(session.amount),
                'exit_time': session.exit_time.isoformat() if session.exit_time else None
            })
            
        hourly_rate = get_hourly_rate()
        minutes, amount = session.calculate_fee(hourly_rate)
        
        return JsonResponse({
            'is_active': True,
            'plate': session.plate,
            'spot_code': session.spot.code,
            'entry_time': session.entry_time.isoformat(),
            'current_time': timezone.now().isoformat(),
            'total_minutes': minutes,
            'amount': amount,
            'hourly_rate': hourly_rate
        })
    except ParkingSession.DoesNotExist:
        return JsonResponse({'error': 'Sessiya topilmadi.'}, status=404)

@csrf_exempt
@require_http_methods(["POST"])
def api_end_session(request):
    """Closes an active session, records calculations, and releases the spot."""
    try:
        data = json.loads(request.body)
        session_id = data.get('session_id')
        
        if not session_id:
            return JsonResponse({'error': 'Sessiya ID kiritilishi shart.'}, status=400)
            
        with transaction.atomic():
            try:
                session = ParkingSession.objects.select_for_update().select_related('spot').get(id=session_id)
            except ParkingSession.DoesNotExist:
                return JsonResponse({'error': 'Sessiya topilmadi.'}, status=404)
                
            if not session.is_active:
                return JsonResponse({'error': 'Sessiya allaqachon yakunlangan.'}, status=400)
                
            hourly_rate = get_hourly_rate()
            exit_time = timezone.now()
            
            # Set values
            session.exit_time = exit_time
            minutes, amount = session.calculate_fee(hourly_rate)
            session.total_minutes = minutes
            session.amount = Decimal(str(amount))
            session.is_active = False
            session.save()
            
            # Free the spot
            spot = session.spot
            spot.is_occupied = False
            spot.save()
            
            return JsonResponse({
                'message': 'Sessiya muvaffaqiyatli yakunlandi.',
                'session_id': session.id,
                'spot_code': spot.code,
                'plate': session.plate,
                'entry_time': session.entry_time.isoformat(),
                'exit_time': session.exit_time.isoformat(),
                'total_minutes': minutes,
                'amount': amount,
                'hourly_rate': hourly_rate
            })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def api_today_report(request):
    """Calculates today's report (earnings and count of cars)."""
    now = timezone.now()
    # Today starts at 00:00:00 Tashkent time
    # timezone.now() yields UTC, but we can compute today's range in local time.
    local_now = timezone.localtime(now)
    start_of_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Filter sessions closed today
    sessions_today = ParkingSession.objects.filter(
        is_active=False,
        exit_time__gte=start_of_day
    ).select_related('spot').order_by('-exit_time')
    
    # Active sessions
    active_sessions_count = ParkingSession.objects.filter(is_active=True).count()
    
    # Statistics
    total_cars_today = sessions_today.count()
    total_revenue_today = sessions_today.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    sessions_data = [{
        'id': s.id,
        'spot_code': s.spot.code,
        'plate': s.plate,
        'entry_time': s.entry_time.isoformat(),
        'exit_time': s.exit_time.isoformat(),
        'total_minutes': s.total_minutes,
        'amount': float(s.amount)
    } for s in sessions_today]
    
    return JsonResponse({
        'date': start_of_day.strftime('%d.%m.%Y'),
        'total_cars_completed': total_cars_today,
        'total_active_cars': active_sessions_count,
        'total_revenue': float(total_revenue_today),
        'sessions': sessions_data
    })

@csrf_exempt
@require_http_methods(["POST"])
def api_update_rate(request):
    """Updates the global hourly parking rate."""
    try:
        data = json.loads(request.body)
        new_rate_str = data.get('hourly_rate')
        
        if new_rate_str is None:
            return JsonResponse({'error': 'Tarif kiritilishi shart.'}, status=400)
            
        try:
            new_rate = float(new_rate_str)
            if new_rate < 0:
                raise ValueError
        except ValueError:
            return JsonResponse({'error': 'Tarif musbat son bo\'lishi shart.'}, status=400)
            
        setting, created = ParkingSetting.objects.get_or_create(key='hourly_rate')
        setting.value = str(int(new_rate))
        setting.save()
        
        return JsonResponse({
            'message': 'Tarif muvaffaqiyatli yangilandi.',
            'hourly_rate': int(new_rate)
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
