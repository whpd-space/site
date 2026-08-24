#!/usr/bin/env python3
"""Build historical Sunday MemeFleet statistics from public zKillboard data."""

import argparse
import json
import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from scripts.update_arrests import request_json, utc_timestamp
except ModuleNotFoundError:  # Direct execution adds scripts/, not the repository root.
    from update_arrests import request_json, utc_timestamp


EASTERN = ZoneInfo('America/New_York')
HISTORY_START = date(2020, 7, 1)
WHPD_ALLIANCE_ID = 99010102  # The Wormhole Police
FLEET_START_HOUR = 13
FLEET_DURATION_HOURS = 2
ZKILL_PAGE_SIZE = 200
MAX_PAGES_PER_MONTH = 50
ZKILL_MONTH_URL = (
    'https://zkillboard.com/api/kills/w-space/{entity_type}/{entity_id}/'
    'year/{year}/month/{month}/page/{page}/'
)


def parse_timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def month_range(start_date, end_date):
    """Yield every (year, month) pair between two dates, inclusively."""
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        yield year, month
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1


def recent_months(current_date):
    """Return the previous and current months for incremental refreshes."""
    if current_date.month == 1:
        previous = (current_date.year - 1, 12)
    else:
        previous = (current_date.year, current_date.month - 1)
    return [previous, (current_date.year, current_date.month)]


def history_source(year, month):
    """Return the official WHPD alliance source for every historical month."""
    return 'allianceID', WHPD_ALLIANCE_ID


def fetch_month_kills(year, month):
    """Fetch all W-space kills for the WHPD entity active during a month."""
    entity_type, entity_id = history_source(year, month)
    kills = []
    seen_killmail_ids = set()

    for page in range(1, MAX_PAGES_PER_MONTH + 1):
        url = ZKILL_MONTH_URL.format(
            entity_type=entity_type,
            entity_id=entity_id,
            year=year,
            month=month,
            page=page,
        )
        result = request_json(url)
        if not isinstance(result, list):
            raise RuntimeError(f'zKillboard returned an unexpected response for {year}-{month:02d}')

        for killmail in result:
            killmail_id = int(killmail['killmail_id'])
            if killmail_id not in seen_killmail_ids:
                seen_killmail_ids.add(killmail_id)
                kills.append(killmail)

        if len(result) < ZKILL_PAGE_SIZE:
            break
        if page == MAX_PAGES_PER_MONTH:
            raise RuntimeError(f'zKillboard results for {year}-{month:02d} exceed the pagination limit')
        time.sleep(1)

    return kills


def fleet_window(killmail_time):
    """Return the DST-aware local fleet window containing a timestamp, if any."""
    local_time = killmail_time.astimezone(EASTERN)
    if local_time.weekday() != 6:  # Sunday
        return None

    start = datetime.combine(
        local_time.date(),
        datetime_time(FLEET_START_HOUR, 0),
        tzinfo=EASTERN,
    )
    end = start + timedelta(hours=FLEET_DURATION_HOURS)
    if not start <= local_time < end:
        return None
    return start, end


def build_memefleet_dataset(killmails, now):
    """Aggregate completed weekly fleet windows and omit zero-value fleets."""
    now = now.astimezone(timezone.utc)
    unique_killmails = {
        int(killmail['killmail_id']): killmail
        for killmail in killmails
    }
    fleets = {}

    for killmail in unique_killmails.values():
        if killmail.get('zkb', {}).get('npc') is True:
            continue
        if not killmail.get('victim', {}).get('character_id'):
            continue

        window = fleet_window(parse_timestamp(killmail['killmail_time']))
        if window is None:
            continue
        start, end = window
        if end.astimezone(timezone.utc) > now:
            continue

        fleet_date = start.date().isoformat()
        fleet = fleets.setdefault(fleet_date, {
            'date': fleet_date,
            'start_local': start.isoformat(),
            'end_local': end.isoformat(),
            'start_utc': utc_timestamp(start),
            'end_utc': utc_timestamp(end),
            'timezone': start.tzname(),
            'participants_max': 0,
            'systems_protected': 0,
            'arrests': 0,
            'total_value': 0.0,
            '_system_ids': set(),
        })
        participant_ids = {
            int(attacker['character_id'])
            for attacker in killmail.get('attackers', [])
            if attacker.get('character_id')
        }
        fleet['participants_max'] = max(fleet['participants_max'], len(participant_ids))
        if killmail.get('solar_system_id'):
            fleet['_system_ids'].add(int(killmail['solar_system_id']))
        fleet['arrests'] += 1
        fleet['total_value'] += float(killmail.get('zkb', {}).get('totalValue') or 0)

    fleet_history = [fleet for fleet in fleets.values() if fleet['total_value'] > 0]
    fleet_history.sort(key=lambda fleet: fleet['date'], reverse=True)
    for fleet in fleet_history:
        fleet['systems_protected'] = len(fleet.pop('_system_ids'))
        fleet['total_value'] = round(fleet['total_value'], 2)

    return {
        'schema_version': 2,
        'generated_at': utc_timestamp(now),
        'history_start': HISTORY_START.isoformat(),
        'schedule': {
            'timezone': 'America/New_York',
            'weekday': 'Sunday',
            'start_hour': FLEET_START_HOUR,
            'duration_hours': FLEET_DURATION_HOURS,
        },
        'source': {
            'name': 'zKillboard',
            'url': 'https://zkillboard.com/',
            'alliance_id': WHPD_ALLIANCE_ID,
        },
        'fleets': fleet_history,
    }


def merge_memefleet_datasets(existing, refreshed, refreshed_months):
    """Replace refreshed months while retaining the stored historical fleet rows."""
    month_keys = {f'{year:04d}-{month:02d}' for year, month in refreshed_months}
    merged_fleets = {
        fleet['date']: fleet
        for fleet in existing.get('fleets', [])
        if fleet['date'] >= HISTORY_START.isoformat() and fleet['date'][:7] not in month_keys
    }
    merged_fleets.update({fleet['date']: fleet for fleet in refreshed.get('fleets', [])})
    refreshed['fleets'] = sorted(
        merged_fleets.values(),
        key=lambda fleet: fleet['date'],
        reverse=True,
    )
    refreshed['history_start'] = HISTORY_START.isoformat()
    return refreshed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('data/memefleets.json'))
    parser.add_argument('--full', action='store_true', help='Re-fetch every month since the WHPD alliance was founded')
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    existing = {}
    if args.output.exists():
        with open(args.output, 'r', encoding='utf-8') as existing_file:
            existing = json.load(existing_file)

    needs_systems_backfill = any(
        'systems_protected' not in fleet
        for fleet in existing.get('fleets', [])
    )
    full_refresh = args.full or not existing.get('fleets') or needs_systems_backfill
    months = (
        list(month_range(HISTORY_START, now.date()))
        if full_refresh
        else recent_months(now.date())
    )
    if needs_systems_backfill and not args.full:
        print('Existing history needs the Systems Protected backfill.')
    print('Refresh mode:', 'full history' if full_refresh else 'current and previous month')

    raw_killmails = []
    for index, (year, month) in enumerate(months):
        month_kills = fetch_month_kills(year, month)
        raw_killmails.extend(month_kills)
        print(f'Fetched {len(month_kills):,} W-space kills for {year}-{month:02d}')
        if index < len(months) - 1:
            time.sleep(1)

    refreshed = build_memefleet_dataset(raw_killmails, now)
    dataset = (
        refreshed
        if full_refresh
        else merge_memefleet_datasets(existing, refreshed, months)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.output.with_suffix(args.output.suffix + '.tmp')
    with open(temporary_output, 'w', encoding='utf-8') as output_file:
        json.dump(dataset, output_file, indent=2, ensure_ascii=False)
        output_file.write('\n')
    temporary_output.replace(args.output)

    print(f'Wrote {len(dataset["fleets"]):,} non-zero MemeFleet reports to {args.output}')


if __name__ == '__main__':
    main()
