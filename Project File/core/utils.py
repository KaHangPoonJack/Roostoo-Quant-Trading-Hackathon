from datetime import datetime, timezone
import pytz
import time

def wait_until_next_quarter_hour():

    while True:
        now = datetime.now(timezone.utc)
        current_minute = now.minute
        current_second = now.second
        current_microsecond = now.microsecond

        # Determine target minute (next quarter)
        quarter = (current_minute // 15) * 15
        next_quarter = quarter + 15
        if next_quarter >= 60:
            next_quarter = 0

        # Calculate seconds until next quarter:00
        if current_minute < next_quarter or (current_minute == next_quarter and (current_second > 0 or current_microsecond > 0)):
            # Still within current hour block
            minutes_to_wait = next_quarter - current_minute - 1
            seconds_to_wait = 60 - current_second
            total_wait = minutes_to_wait * 60 + seconds_to_wait - (current_microsecond / 1_000_000)
        else:
            # Roll over to next hour (e.g., 14:45 → 15:00)
            minutes_to_wait = 60 - current_minute - 1 + next_quarter
            seconds_to_wait = 60 - current_second
            total_wait = minutes_to_wait * 60 + seconds_to_wait - (current_microsecond / 1_000_000)

        if total_wait > 0.1:  # Wait only if >100ms needed
            print(f"⏰ Waiting {total_wait:.1f}s until next quarter hour ({now.hour:02d}:{next_quarter:02d} UTC)")
            time.sleep(total_wait)
            break
        else:
            # We're already at or just past the boundary → wait a bit more to ensure candle closes
            print("⏳ Very close to boundary — waiting 2 seconds to ensure candle completeness...")
            time.sleep(2)
            break

def is_us_market_open():
    # Define US/Eastern timezone (handles EST/EDT automatically)
    eastern = pytz.timezone('US/Eastern')
    now_eastern = datetime.now(eastern)
    
    current_hour = now_eastern.hour
    current_minute = now_eastern.minute

    # US market hours: 9:30 AM to 4:00 PM Eastern Time
    us_open_hour, us_open_minute = 9, 30
    us_close_hour, us_close_minute = 16, 0  # 4:00 PM

    # Check if current time is within [9:30, 16:00] inclusive
    is_after_open = (current_hour > us_open_hour) or \
                    (current_hour == us_open_hour and current_minute >= us_open_minute)
    
    is_before_close = (current_hour < us_close_hour) or \
                      (current_hour == us_close_hour and current_minute <= us_close_minute)

    return is_after_open and is_before_close
