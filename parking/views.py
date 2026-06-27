import json
import csv
from decimal import Decimal
from datetime import datetime, timedelta
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.contrib.auth import authenticate, login, logout
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import TruncDate

from parking.constants import NUMERIC_SETTING_KEYS
from parking.models import ParkingSpot, ParkingSession, ParkingSetting, ParkingSubscription, ParkingNotification
from parking.services import get_all_settings, dispatch_notification, get_active_shift
def dashboard_view(request):
    """Renders the main dashboard page."""
    context = get_all_settings()
    active_shift = get_active_shift()
    context['active_shift_guard'] = active_shift.guard_name if active_shift else None
    context['is_admin'] = request.user.is_authenticated and request.user.is_staff
    context['username'] = request.user.username if request.user.is_authenticated else None
    return render(request, 'parking/dashboard.html', context)

@require_http_methods(["GET"])
@never_cache
def api_spots(request):
    """Returns status of all parking spots, including live earning rate."""
    spots = ParkingSpot.objects.all().order_by('code')
    spots_data = []
    
    # Pre-fetch active sessions to join active plate info with spots
    active_sessions = {
        s.spot_id: s
        for s in ParkingSession.objects.filter(is_active=True).select_related('spot')
    }
    settings = get_all_settings()
    hourly_rate = settings['hourly_rate']
    
    earning_rate_per_minute = 0.0
    
    for spot in spots:
        session = active_sessions.get(spot.id)
        session_id = None
        plate = None
        entry_time = None
        session_type = None
        
        if session:
            session_id = session.id
            plate = session.plate
            entry_time = session.entry_time.isoformat()
            session_type = session.session_type
            
            # Subscribed cars do not generate revenue rate
            if session_type == 'PAID':
                multiplier = spot.get_multiplier()
                earning_rate_per_minute += (hourly_rate * multiplier) / 60.0
        
        spots_data.append({
            'id': spot.id,
            'code': spot.code,
            'is_occupied': spot.is_occupied,
            'spot_type': spot.spot_type,
            'spot_type_display': spot.get_spot_type_display(),
            'multiplier': spot.get_multiplier(),
            'plate': plate,
            'session_id': session_id,
            'session_type': session_type,
            'entry_time': entry_time
        })
        
    return JsonResponse({
        'spots': spots_data,
        'earning_rate_per_minute': round(earning_rate_per_minute, 2)
    })

@require_http_methods(["GET"])
@never_cache
def api_active_sessions(request):
    """Returns list of currently active parking sessions."""
    sessions = ParkingSession.objects.filter(is_active=True).select_related('spot')
    data = [{
        'id': s.id,
        'spot_code': s.spot.code,
        'spot_type': s.spot.spot_type,
        'plate': s.plate,
        'session_type': s.session_type,
        'entry_time': s.entry_time.isoformat()
    } for s in sessions]
    return JsonResponse({'sessions': data})

@csrf_exempt
@require_http_methods(["POST"])
def api_start_session(request):
    """Starts a new parking session, checking for active shifts and monthly subscription."""
    try:
        # Check active shift
        shift = get_active_shift()
        if not shift:
            return JsonResponse({'error': 'Smena ochilmagan! Iltimos, oldin yangi smena oching.'}, status=400)
            
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
                
            # Check subscription
            try:
                sub = ParkingSubscription.objects.get(plate=plate, is_active=True, expiry_date__gte=timezone.localdate())
                session_type = 'SUBSCRIBED'
                message = f"'{plate}' obunachisi aniqlandi (Abonement)."
            except ParkingSubscription.DoesNotExist:
                session_type = 'PAID'
                message = 'Sessiya muvaffaqiyatli boshlandi.'
                
            session = ParkingSession.objects.create(
                spot=spot,
                shift=shift,
                plate=plate,
                entry_time=timezone.now(),
                is_active=True,
                session_type=session_type
            )
            
            spot.is_occupied = True
            spot.save()
            
            try:
                receipt_url = f"{request.scheme}://{request.get_host()}/receipt/{session.id}/"
                msg = (
                    f"🚗 *KIRISH QAYD ETILDI*\n\n"
                    f"• *Davlat raqami:* {session.plate}\n"
                    f"• *Parking joyi:* {spot.code} ({spot.get_spot_type_display()})\n"
                    f"• *Kirish vaqti:* {timezone.localtime(session.entry_time).strftime('%d.%m.%Y %H:%M:%S')}\n"
                    f"• *Tarif turi:* {session.get_session_type_display()}\n\n"
                    f"🔗 [Onlayn Kvitansiyani ko'rish]({receipt_url})"
                )
                dispatch_notification('TELEGRAM', session.plate, msg)
            except Exception as e:
                print(f"Failed to queue checkin notification: {e}")
            
            return JsonResponse({
                'message': message,
                'session_id': session.id,
                'spot_code': spot.code,
                'spot_type': spot.spot_type,
                'spot_type_display': spot.get_spot_type_display(),
                'plate': session.plate,
                'session_type': session.session_type,
                'entry_time': session.entry_time.isoformat()
            })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
@never_cache
def api_calculate_fee(request):
    """Calculates active session fee in real-time based on advanced tariff rules."""
    session_id = request.GET.get('session_id')
    is_lost_param = request.GET.get('is_lost_ticket') == 'true'
    
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
            
        # Temporarily mock lost ticket if parameter matches
        is_lost = is_lost_param if is_lost_param else None
        minutes, amount = session.calculate_fee_with_settings(settings, is_lost_ticket=is_lost)
        
        return JsonResponse({
            'is_active': True,
            'plate': session.plate,
            'spot_code': session.spot.code,
            'spot_type': session.spot.spot_type,
            'spot_type_display': session.spot.get_spot_type_display(),
            'multiplier': session.spot.get_multiplier(),
            'session_type': session.session_type,
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
        # Check active shift
        shift = get_active_shift()
        if not shift:
            return JsonResponse({'error': 'Smena ochilmagan! Iltimos, oldin yangi smena oching.'}, status=400)
            
        data = json.loads(request.body)
        session_id = data.get('session_id')
        is_lost_ticket = data.get('is_lost_ticket', False)
        
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
            session.is_lost_ticket = is_lost_ticket
            minutes, amount = session.calculate_fee_with_settings(settings)
            
            session.total_minutes = minutes
            session.amount = Decimal(str(amount))
            session.is_active = False
            # Bind to current shift just in case
            session.shift = shift
            session.save()
            
            # Free the spot
            spot = session.spot
            spot.is_occupied = False
            spot.save()
            
            try:
                msg = (
                    f"💳 *TO'LOV TASDIQLANDI*\n\n"
                    f"• *Davlat raqami:* {session.plate}\n"
                    f"• *Parking joyi:* {spot.code}\n"
                    f"• *Jami turgan vaqti:* {round(minutes)} daqiqa\n"
                    f"• *To'langan summa:* {int(amount):,} so'm\n"
                    f"• *Chiqish vaqti:* {timezone.localtime(session.exit_time).strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                    f"👋 *Oq yo'l, xavfsiz safar tilaymiz!*"
                )
                dispatch_notification('SMS', session.plate, msg)
            except Exception as e:
                print(f"Failed to queue checkout notification: {e}")
            
            return JsonResponse({
                'message': 'Sessiya muvaffaqiyatli yakunlandi.',
                'session_id': session.id,
                'spot_code': spot.code,
                'spot_type': spot.spot_type,
                'plate': session.plate,
                'session_type': session.session_type,
                'is_lost_ticket': session.is_lost_ticket,
                'entry_time': session.entry_time.isoformat(),
                'exit_time': session.exit_time.isoformat(),
                'total_minutes': minutes,
                'amount': amount,
                'multiplier': spot.get_multiplier()
            })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
@never_cache
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
        'session_type': s.session_type,
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
@never_cache
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
        'session_type': s.get_session_type_display(),
        'entry_time': s.entry_time.isoformat(),
        'exit_time': s.exit_time.isoformat(),
        'total_minutes': s.total_minutes,
        'amount': float(s.amount)
    } for s in sessions[:100]]
    
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
    response.write('\ufeff'.encode('utf8'))
    
    writer = csv.writer(response)
    writer.writerow(['Davlat Raqami', 'Joy Kodi', 'Joy Turi', 'Tarif turi', 'Kirish Vaqti', 'Chiqish Vaqti', 'Turgan Vaqti (Daqiqa)', 'To\'lov Miqdori (UZS)'])
    
    for s in sessions:
        in_local = timezone.localtime(s.entry_time).strftime('%d.%m.%Y %H:%M:%S')
        out_local = timezone.localtime(s.exit_time).strftime('%d.%m.%Y %H:%M:%S')
        writer.writerow([
            s.plate,
            s.spot.code,
            s.spot.get_spot_type_display(),
            s.get_session_type_display(),
            in_local,
            out_local,
            round(s.total_minutes or 0, 1),
            int(s.amount or 0)
        ])
        
    return response

@require_http_methods(["GET"])
@never_cache
def api_analytics_data(request):
    """Returns analytics data (earnings last 7 days and hourly traffic breakdown)."""
    now = timezone.now()
    local_now = timezone.localtime(now)
    
    # 1. Earnings Trend (Last 7 Days) — single aggregated query
    start_date = local_now.date() - timedelta(days=6)
    day_start = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))

    daily_revenue = {
        row['day']: row['total'] or Decimal('0.00')
        for row in ParkingSession.objects.filter(
            is_active=False,
            exit_time__gte=day_start,
        ).annotate(day=TruncDate('exit_time')).values('day').annotate(total=Sum('amount'))
    }

    earnings_trend = []
    for i in range(6, -1, -1):
        day = local_now.date() - timedelta(days=i)
        earnings_trend.append({
            'label': day.strftime('%d-%b'),
            'value': float(daily_revenue.get(day, Decimal('0.00'))),
        })
        
    # 2. Hourly Check-in Distribution
    hourly_distribution = [0] * 24
    thirty_days_ago = local_now - timedelta(days=30)
    sessions = ParkingSession.objects.filter(entry_time__gte=thirty_days_ago)
    
    for s in sessions:
        local_entry = timezone.localtime(s.entry_time)
        hour = local_entry.hour
        hourly_distribution[hour] += 1
        
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
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'error': 'Ushbu amalni bajarish uchun administrator huquqi talab qilinadi.'}, status=403)
    try:
        data = json.loads(request.body)
        keys = list(NUMERIC_SETTING_KEYS)
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

# ==================== NEW SHIFT MANAGER APIs ====================

@require_http_methods(["GET", "POST"])
@csrf_exempt
@never_cache
def api_active_shift(request):
    """Manages active shift. GET returns current shift state. POST opens new shift."""
    if request.method == "GET":
        shift = get_active_shift()
        if not shift:
            return JsonResponse({'active': False})
            
        # Aggregate stats
        sessions = ParkingSession.objects.filter(shift=shift, is_active=False)
        total_revenue = sessions.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        count_completed = sessions.count()
        count_active = ParkingSession.objects.filter(shift=shift, is_active=True).count()
        
        return JsonResponse({
            'active': True,
            'shift_id': shift.id,
            'guard_name': shift.guard_name,
            'start_time': shift.start_time.isoformat(),
            'total_revenue': float(total_revenue),
            'count_completed': count_completed,
            'count_active': count_active
        })
    elif request.method == "POST":
        active = get_active_shift()
        if active:
            return JsonResponse({'error': 'Faol smena allaqachon ochilgan. Avval uni yoping.'}, status=400)
            
        try:
            data = json.loads(request.body)
            guard_name = data.get('guard_name', '').strip()
            if not guard_name:
                return JsonResponse({'error': 'Qorovul ismi kiritilishi shart.'}, status=400)
                
            shift = ParkingShift.objects.create(
                guard_name=guard_name,
                start_time=timezone.now(),
                is_active=True
            )
            return JsonResponse({
                'message': f"Smena muvaffaqiyatli ochildi. Operator: {shift.guard_name}",
                'shift_id': shift.id,
                'guard_name': shift.guard_name,
                'start_time': shift.start_time.isoformat()
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def api_close_shift(request):
    """Closes the current active cashier shift and returns closeout metrics."""
    shift = get_active_shift()
    if not shift:
        return JsonResponse({'error': 'Faol smena topilmadi.'}, status=400)
        
    try:
        with transaction.atomic():
            # Close active sessions linked to this shift
            active_sessions = ParkingSession.objects.filter(shift=shift, is_active=True)
            active_count = active_sessions.count()
            
            # Close shift
            shift.is_active = False
            shift.end_time = timezone.now()
            shift.save()
            
            # Calculate shift statistics
            sessions_closed = ParkingSession.objects.filter(shift=shift, is_active=False)
            total_revenue = sessions_closed.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            count_completed = sessions_closed.count()
            count_standard = sessions_closed.filter(session_type='PAID').count()
            count_subscribed = sessions_closed.filter(session_type='SUBSCRIBED').count()
            count_lost_ticket = sessions_closed.filter(is_lost_ticket=True).count()
            
            return JsonResponse({
                'message': 'Smena muvaffaqiyatli yakunlandi.',
                'shift_id': shift.id,
                'guard_name': shift.guard_name,
                'start_time': shift.start_time.isoformat(),
                'end_time': shift.end_time.isoformat(),
                'total_revenue': float(total_revenue),
                'count_completed': count_completed,
                'count_standard': count_standard,
                'count_subscribed': count_subscribed,
                'count_lost_ticket': count_lost_ticket,
                'remaining_active_cars_orphaned': active_count
            })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# ==================== NEW SUBSCRIPTION APIs ====================

@require_http_methods(["GET", "POST", "DELETE"])
@csrf_exempt
@never_cache
def api_subscriptions(request):
    """GET returns subscribers list. POST adds/renews. DELETE removes a subscription."""
    if request.method == "GET":
        # Check and warn for expiring subscriptions
        try:
            today = timezone.localdate()
            target_expiry = today + timedelta(days=3)
            expiring_subs = ParkingSubscription.objects.filter(is_active=True, expiry_date=target_expiry)
            for sub in expiring_subs:
                warning_msg = (
                    f"⚠️ *ABONEMENT MUDDATI TUGAMOQDA*\n\n"
                    f"• *Davlat raqami:* {sub.plate}\n"
                    f"• *Mijoz:* {sub.owner_name}\n"
                    f"• *Tugash sanasi:* {sub.expiry_date.strftime('%d.%m.%Y')}\n\n"
                    f"Iltimos, oylik abonementni o'z vaqtida uzaytiring."
                )
                already_sent = ParkingNotification.objects.filter(
                    notification_type='TELEGRAM',
                    recipient=sub.plate,
                    message=warning_msg,
                    sent_time__gte=timezone.now() - timedelta(hours=24)
                ).exists()
                if not already_sent:
                    dispatch_notification('TELEGRAM', sub.plate, warning_msg)
        except Exception as e:
            print(f"Failed to check expiring subscriptions: {e}")

        subs = ParkingSubscription.objects.all().order_by('-expiry_date')
        data = [{
            'id': s.id,
            'plate': s.plate,
            'owner_name': s.owner_name,
            'expiry_date': s.expiry_date.isoformat(),
            'is_valid': s.is_valid()
        } for s in subs]
        return JsonResponse({'subscriptions': data})
        
    elif request.method == "POST":
        if not request.user.is_authenticated or not request.user.is_staff:
            return JsonResponse({'error': 'Ushbu amalni bajarish uchun administrator huquqi talab qilinadi.'}, status=403)
        try:
            data = json.loads(request.body)
            plate = data.get('plate', '').strip().upper()
            owner_name = data.get('owner_name', '').strip()
            expiry_str = data.get('expiry_date', '').strip()
            
            if not plate or not owner_name or not expiry_str:
                return JsonResponse({'error': 'Barcha maydonlarni to\'ldirish shart.'}, status=400)
                
            try:
                expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'Sana formati noto\'g\'ri (YYYY-MM-DD).'}, status=400)
                
            sub, created = ParkingSubscription.objects.get_or_create(
                plate=plate,
                defaults={
                    'owner_name': owner_name,
                    'expiry_date': expiry_date,
                    'is_active': True
                }
            )
            
            if not created:
                sub.owner_name = owner_name
                sub.expiry_date = expiry_date
                sub.is_active = True
                sub.save()
                message = "Abonement muddati muvaffaqiyatli uzaytirildi."
            else:
                message = "Yangi abonement muvaffaqiyatli qo'shildi."
                
            return JsonResponse({
                'message': message,
                'id': sub.id,
                'plate': sub.plate,
                'owner_name': sub.owner_name,
                'expiry_date': sub.expiry_date.isoformat(),
                'is_valid': sub.is_valid()
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
            
    elif request.method == "DELETE":
        if not request.user.is_authenticated or not request.user.is_staff:
            return JsonResponse({'error': 'Ushbu amalni bajarish uchun administrator huquqi talab qilinadi.'}, status=403)
        try:
            sub_id = request.GET.get('id')
            if not sub_id:
                return JsonResponse({'error': 'Abonement ID kiritilishi shart.'}, status=400)
            sub = ParkingSubscription.objects.get(id=sub_id)
            plate = sub.plate
            sub.delete()
            return JsonResponse({'message': f"'{plate}' raqamli abonement muvaffaqiyatli o'chirildi."})
        except ParkingSubscription.DoesNotExist:
            return JsonResponse({'error': 'Abonement topilmadi.'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def api_admin_login(request):
    try:
        data = json.loads(request.body)
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not username or not password:
            return JsonResponse({'error': 'Foydalanuvchi nomi va parol kiritilishi shart.'}, status=400)
            
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_staff:
                login(request, user)
                return JsonResponse({
                    'message': 'Tizimga muvaffaqiyatli kirildi.',
                    'username': user.username,
                    'is_admin': True
                })
            else:
                return JsonResponse({'error': 'Ushbu panelga faqat administratorlar kira oladi.'}, status=403)
        else:
            return JsonResponse({'error': 'Foydalanuvchi nomi yoki parol noto\'g\'ri.'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def api_admin_logout(request):
    logout(request)
    return JsonResponse({'message': 'Tizimdan muvaffaqiyatli chiqildi.'})

@never_cache
def online_receipt_view(request, session_id):
    """Renders a public online receipt status page with live ticking calculations."""
    try:
        session = ParkingSession.objects.select_related('spot').get(id=session_id)
        settings = get_all_settings()
        minutes, amount = session.calculate_fee_with_settings(settings)
        
        context = {
            'session': session,
            'settings': settings,
            'current_time': timezone.now(),
            'total_minutes': minutes,
            'amount': amount,
            'hourly_rate': settings['hourly_rate'],
            'multiplier': session.spot.get_multiplier()
        }
        return render(request, 'parking/online_receipt.html', context)
    except ParkingSession.DoesNotExist:
        return render(request, 'parking/online_receipt.html', {'error': 'Sessiya topilmadi.'}, status=404)

@require_http_methods(["GET"])
@never_cache
def api_notifications(request):
    """Returns the last 15 sent notifications for the dashboard feed logs."""
    notifs = ParkingNotification.objects.all().order_by('-sent_time')[:15]
    data = [{
        'id': n.id,
        'notification_type': n.notification_type,
        'notification_type_display': n.get_notification_type_display(),
        'recipient': n.recipient,
        'message': n.message,
        'sent_time': n.sent_time.isoformat()
    } for n in notifs]
    return JsonResponse({'notifications': data})
