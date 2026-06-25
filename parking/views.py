import json
import csv
from decimal import Decimal
from datetime import datetime, timedelta
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Count

from parking.models import ParkingSpot, ParkingSession, ParkingSetting

# Helpers to get settings
def get_setting(key, default_val):
    try:
        setting = ParkingSetting.objects.get(key=key)
        return setting.value
    except ParkingSetting.DoesNotExist:
        return default_val

def get_all_settings():
    return {
        'hourly_rate': float(get_setting('hourly_rate', '10000')),
        'free_minutes': float(get_setting('free_minutes', '10')),
        'min_charge_amount': float(get_setting('min_charge_amount', '5000')),
        'min_charge_duration': float(get_setting('min_charge_duration', '60')),
    }

def dashboard_view(request):
    """Renders the main dashboard page."""
    context = get_all_settings()
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
            'spot_type': spot.spot_type,
            'spot_type_display': spot.get_spot_type_display(),
            'multiplier': spot.get_multiplier(),
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
        'spot_type': s.spot.spot_type,
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
                
            if ParkingSession.objects.filter(plate=plate, is_active=True).exists():
                return JsonResponse({'error': f"'{plate}' raqamli mashina uchun faol sessiya allaqachon mavjud."}, status=400)
                
            session = ParkingSession.objects.create(
                spot=spot,
                plate=plate,
                entry_time=timezone.now(),
                is_active=True
            )
            
            spot.is_occupied = True
            spot.save()
            
            return JsonResponse({
                'message': 'Sessiya muvaffaqiyatli boshlandi.',
                'session_id': session.id,
                'spot_code': spot.code,
                'spot_type': spot.spot_type,
                'spot_type_display': spot.get_spot_type_display(),
                'plate': session.plate,
                'entry_time': session.entry_time.isoformat()
            })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def api_calculate_fee(request):
    """Calculates active session fee in real-time based on advanced tariff rules."""
    session_id = request.GET.get('session_id')
    if not session_id:
        return JsonResponse({'error': 'Sessiya ID kiritilishi shart.'}, status=400)
        
    try:
        session = ParkingSession.objects.select_related('spot').get(id=session_id)
        settings = get_all_settings()
        
        if not session.is_active:
            return JsonResponse({
                'is_active': False,
                'total_minutes': session.total_minutes,
                'amount': float(session.amount),
                'exit_time': session.exit_time.isoformat() if session.exit_time else None
            })
            
        minutes, amount = session.calculate_fee(
            hourly_rate=settings['hourly_rate'],
            free_minutes=settings['free_minutes'],
            min_charge_amount=settings['min_charge_amount'],
            min_charge_duration=settings['min_charge_duration']
        )
        
        return JsonResponse({
            'is_active': True,
            'plate': session.plate,
            'spot_code': session.spot.code,
            'spot_type': session.spot.spot_type,
            'spot_type_display': session.spot.get_spot_type_display(),
            'multiplier': session.spot.get_multiplier(),
            'entry_time': session.entry_time.isoformat(),
            'current_time': timezone.now().isoformat(),
            'total_minutes': minutes,
            'amount': amount,
            'settings': settings
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
                
            settings = get_all_settings()
            exit_time = timezone.now()
            
            # Set values
            session.exit_time = exit_time
            minutes, amount = session.calculate_fee(
                hourly_rate=settings['hourly_rate'],
                free_minutes=settings['free_minutes'],
                min_charge_amount=settings['min_charge_amount'],
                min_charge_duration=settings['min_charge_duration']
            )
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
                'spot_type': spot.spot_type,
                'plate': session.plate,
                'entry_time': session.entry_time.isoformat(),
                'exit_time': session.exit_time.isoformat(),
                'total_minutes': minutes,
                'amount': amount,
                'multiplier': spot.get_multiplier()
            })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def api_today_report(request):
    """Calculates today's report (earnings and count of cars)."""
    now = timezone.now()
    local_now = timezone.localtime(now)
    start_of_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    sessions_today = ParkingSession.objects.filter(
        is_active=False,
        exit_time__gte=start_of_day
    ).select_related('spot').order_by('-exit_time')
    
    active_sessions_count = ParkingSession.objects.filter(is_active=True).count()
    total_cars_today = sessions_today.count()
    total_revenue_today = sessions_today.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    sessions_data = [{
        'id': s.id,
        'spot_code': s.spot.code,
        'spot_type_display': s.spot.get_spot_type_display(),
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

def _get_filtered_history(request):
    """Helper to parse filters and query historical sessions."""
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    plate = request.GET.get('plate', '').strip().upper()
    
    sessions = ParkingSession.objects.filter(is_active=False).select_related('spot')
    
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            # timezone aware
            start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
            sessions = sessions.filter(exit_time__gte=start_dt)
        except ValueError:
            pass
            
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
            sessions = sessions.filter(exit_time__lte=end_dt)
        except ValueError:
            pass
            
    if plate:
        sessions = sessions.filter(plate__icontains=plate)
        
    return sessions.order_by('-exit_time')

@require_http_methods(["GET"])
def api_history_report(request):
    """Returns historical list of sessions with filters."""
    sessions = _get_filtered_history(request)
    
    total_revenue = sessions.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    total_count = sessions.count()
    
    data = [{
        'id': s.id,
        'spot_code': s.spot.code,
        'spot_type': s.spot.spot_type,
        'spot_type_display': s.spot.get_spot_type_display(),
        'plate': s.plate,
        'entry_time': s.entry_time.isoformat(),
        'exit_time': s.exit_time.isoformat(),
        'total_minutes': s.total_minutes,
        'amount': float(s.amount)
    } for s in sessions[:100]] # Limit to 100 entries for performance, CSV gets all
    
    return JsonResponse({
        'total_count': total_count,
        'total_revenue': float(total_revenue),
        'sessions': data
    })

@require_http_methods(["GET"])
def api_export_csv(request):
    """Exports the filtered historical records to CSV spreadsheet."""
    sessions = _get_filtered_history(request)
    
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="parking_history.csv"'
    
    # Write UTF-8 BOM for Excel compatibility on Windows
    response.write('\ufeff'.encode('utf8'))
    
    writer = csv.writer(response)
    writer.writerow(['Davlat Raqami', 'Joy Kodi', 'Joy Turi', 'Kirish Vaqti', 'Chiqish Vaqti', 'Turgan Vaqti (Daqiqa)', 'To\'lov Miqdori (UZS)'])
    
    for s in sessions:
        in_local = timezone.localtime(s.entry_time).strftime('%d.%m.%Y %H:%M:%S')
        out_local = timezone.localtime(s.exit_time).strftime('%d.%m.%Y %H:%M:%S')
        writer.writerow([
            s.plate,
            s.spot.code,
            s.spot.get_spot_type_display(),
            in_local,
            out_local,
            round(s.total_minutes or 0, 1),
            int(s.amount or 0)
        ])
        
    return response

@require_http_methods(["GET"])
def api_analytics_data(request):
    """Returns analytics data (earnings last 7 days and hourly traffic breakdown)."""
    now = timezone.now()
    local_now = timezone.localtime(now)
    
    # 1. Earnings Trend (Last 7 Days)
    earnings_trend = []
    for i in range(6, -1, -1):
        day = local_now.date() - timedelta(days=i)
        day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        day_end = timezone.make_aware(datetime.combine(day, datetime.max.time()))
        
        revenue = ParkingSession.objects.filter(
            is_active=False,
            exit_time__range=(day_start, day_end)
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        earnings_trend.append({
            'label': day.strftime('%d-%b'), # e.g. "25-Jun"
            'value': float(revenue)
        })
        
    # 2. Hourly Check-in Distribution
    # Group check-ins by hour (0 to 23)
    hourly_distribution = [0] * 24
    
    # Analyze sessions from past 30 days for rich distribution data
    thirty_days_ago = local_now - timedelta(days=30)
    sessions = ParkingSession.objects.filter(entry_time__gte=thirty_days_ago)
    
    for s in sessions:
        local_entry = timezone.localtime(s.entry_time)
        hour = local_entry.hour
        hourly_distribution[hour] += 1
        
    # Convert hourly data to label/value format
    hourly_data = [{
        'label': f"{h:02d}:00",
        'value': hourly_distribution[h]
    } for h in range(24)]
    
    return JsonResponse({
        'earnings_trend': earnings_trend,
        'hourly_traffic': hourly_data
    })

@csrf_exempt
@require_http_methods(["POST"])
def api_update_rate(request):
    """Updates the parking settings parameters."""
    try:
        data = json.loads(request.body)
        
        keys = ['hourly_rate', 'free_minutes', 'min_charge_amount', 'min_charge_duration']
        response_data = {}
        
        for key in keys:
            if key in data:
                val_str = str(data[key]).strip()
                try:
                    val_num = float(val_str)
                    if val_num < 0:
                        return JsonResponse({'error': f"'{key}' qiymati musbat son bo'lishi shart."}, status=400)
                except ValueError:
                    return JsonResponse({'error': f"'{key}' qiymati son bo'lishi shart."}, status=400)
                
                setting, created = ParkingSetting.objects.get_or_create(key=key)
                setting.value = str(int(val_num))
                setting.save()
                response_data[key] = int(val_num)
                
        return JsonResponse({
            'message': 'Sozlamalar muvaffaqiyatli yangilandi.',
            'settings': response_data
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
