#!/usr/bin/env python3
"""Build the rolling WHPD arrest dataset from public zKillboard killmails."""

import argparse
import gzip
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


WINDOW_SECONDS = 7 * 24 * 60 * 60
WHPD_ALLIANCE_ID = 99010102  # The Wormhole Police
ZKILL_URL = 'https://zkillboard.com/api/kills/w-space/allianceID/{alliance_id}/pastSeconds/604800/page/{page}/'
ZKILL_CHARACTER_STATS_URL = 'https://zkillboard.com/api/stats/characterID/{character_id}/kills/'
ESI_NAMES_URL = 'https://esi.evetech.net/latest/universe/names/?datasource=tranquility'
USER_AGENT = 'whpd.space zKill updater (https://whpd.space; https://github.com/whpd-space/site)'
MAX_ZKILL_PAGES = 100
ZKILL_PAGE_LIMIT = 200


def utc_timestamp(value):
    """Return a UTC datetime in the format used by ESI and zKillboard."""
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def parse_timestamp(value):
    """Parse an ESI-style ISO timestamp."""
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def request_json(url, *, payload=None, retries=3):
    """Request JSON with the headers and retry behavior expected by zKillboard."""
    body = None
    headers = {
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip',
        'User-Agent': USER_AGENT,
    }
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(request, timeout=45) as response:
                response_body = response.read()
                if response.headers.get('Content-Encoding') == 'gzip':
                    response_body = gzip.decompress(response_body)
                return json.loads(response_body.decode('utf-8'))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as error:
            if attempt == retries:
                raise RuntimeError(f'Request failed after {retries} attempts: {url}') from error
            time.sleep(2 ** (attempt - 1))


def fetch_alliance_kills():
    """Fetch the alliance's W-space kills from the last week."""
    kills = {}

    for page in range(1, MAX_ZKILL_PAGES + 1):
        url = ZKILL_URL.format(alliance_id=WHPD_ALLIANCE_ID, page=page)
        result = request_json(url)
        if not isinstance(result, list):
            raise RuntimeError(f'zKillboard returned an unexpected response for alliance {WHPD_ALLIANCE_ID}')

        for killmail in result:
            kills[int(killmail['killmail_id'])] = killmail

        # The documented API maximum is 200 records per request. A shorter
        # result means there is no next page to retrieve.
        if len(result) < ZKILL_PAGE_LIMIT:
            break
        if page == MAX_ZKILL_PAGES:
            raise RuntimeError(
                f'zKillboard results for alliance {WHPD_ALLIANCE_ID} exceed the safe pagination limit'
            )
        time.sleep(1)

    return list(kills.values())


def resolve_names(ids):
    """Resolve EVE entity IDs to names with the public ESI universe endpoint."""
    unique_ids = sorted({int(entity_id) for entity_id in ids if entity_id})
    names = {}
    chunk_size = 900

    for offset in range(0, len(unique_ids), chunk_size):
        chunk = unique_ids[offset:offset + chunk_size]
        for entity in request_json(ESI_NAMES_URL, payload=chunk):
            names[int(entity['id'])] = entity['name']
        if offset + chunk_size < len(unique_ids):
            time.sleep(1)
    return names


def is_whpd_attacker(attacker):
    """Use affiliation on this killmail, never a local personnel list."""
    return bool(attacker.get('character_id')) and attacker.get('alliance_id') == WHPD_ALLIANCE_ID


def fetch_current_member_ids(character_ids):
    """Check current affiliation in zKillboard's character stats, not kill history."""
    current_member_ids = set()
    character_ids = sorted(set(character_ids))
    for index, character_id in enumerate(character_ids):
        result = request_json(ZKILL_CHARACTER_STATS_URL.format(character_id=character_id))
        info = result.get('info') if isinstance(result, dict) else None
        if not isinstance(info, dict) or info.get('id') != character_id or not info.get('name'):
            raise RuntimeError(f'zKillboard returned unexpected character stats for {character_id}')
        alliance_id = info.get('alliance_id', info.get('allianceID'))
        if alliance_id == WHPD_ALLIANCE_ID:
            current_member_ids.add(character_id)
        if index < len(character_ids) - 1:
            time.sleep(1)
    return current_member_ids


def collect_name_ids(killmails):
    """Collect every public entity ID needed to render the weekly blotter."""
    ids = set()
    for killmail in killmails:
        ids.add(killmail.get('solar_system_id'))
        victim = killmail.get('victim', {})
        ids.update((
            victim.get('character_id'),
            victim.get('corporation_id'),
            victim.get('alliance_id'),
            victim.get('ship_type_id'),
        ))
        for attacker in killmail.get('attackers', []):
            if is_whpd_attacker(attacker):
                ids.update((attacker['character_id'], attacker.get('ship_type_id')))
    return {entity_id for entity_id in ids if entity_id}


def build_dirtbag_rankings(arrests, limit=10):
    """Group arrests by suspect and return the highest-ranked repeat offenders."""
    dirtbags = {}
    for arrest in arrests:
        victim = arrest['victim']
        character_id = int(victim['character_id'])
        dirtbag = dirtbags.setdefault(character_id, {
            'character_id': character_id,
            'name': victim['name'],
            'corporation_id': victim['corporation_id'],
            'corporation_name': victim['corporation_name'],
            'arrests': 0,
            'total_value': 0.0,
            'most_expensive_loss': None,
        })
        dirtbag['arrests'] += 1
        dirtbag['total_value'] += float(arrest['total_value'])

        expensive_loss = dirtbag['most_expensive_loss']
        if expensive_loss is None or (
            float(arrest['total_value']), arrest['time'], arrest['killmail_id']
        ) > (
            float(expensive_loss['total_value']), expensive_loss['time'], expensive_loss['killmail_id']
        ):
            dirtbag['most_expensive_loss'] = {
                'killmail_id': arrest['killmail_id'],
                'time': arrest['time'],
                'total_value': arrest['total_value'],
                'ship_type_id': victim['ship_type_id'],
                'ship_name': victim['ship_name'],
                'system_id': arrest['system_id'],
                'system_name': arrest['system_name'],
            }

    rankings = sorted(
        dirtbags.values(),
        key=lambda dirtbag: (-dirtbag['arrests'], -dirtbag['total_value'], dirtbag['name'].lower()),
    )[:limit]
    for placement, dirtbag in enumerate(rankings, start=1):
        dirtbag['placement'] = placement
        dirtbag['total_value'] = round(dirtbag['total_value'], 2)
    return rankings


def build_hotspot_rankings(arrests, limit=5):
    """Group arrests by system and rank the busiest enforcement hotspots."""
    hotspots = {}
    for arrest in arrests:
        system_id = int(arrest['system_id'])
        hotspot = hotspots.setdefault(system_id, {
            'system_id': system_id,
            'system_name': arrest['system_name'],
            'arrests': 0,
            'total_value': 0.0,
            'top_killmail': None,
        })
        hotspot['arrests'] += 1
        hotspot['total_value'] += float(arrest['total_value'])

        top_killmail = hotspot['top_killmail']
        if top_killmail is None or (
            float(arrest['total_value']), arrest['time'], arrest['killmail_id']
        ) > (
            float(top_killmail['total_value']), top_killmail['time'], top_killmail['killmail_id']
        ):
            victim = arrest['victim']
            hotspot['top_killmail'] = {
                'killmail_id': arrest['killmail_id'],
                'time': arrest['time'],
                'total_value': arrest['total_value'],
                'victim_name': victim['name'],
                'ship_type_id': victim['ship_type_id'],
                'ship_name': victim['ship_name'],
            }

    rankings = sorted(
        hotspots.values(),
        key=lambda hotspot: (
            -hotspot['arrests'],
            -hotspot['total_value'],
            hotspot['system_name'].lower(),
        ),
    )[:limit]
    for placement, hotspot in enumerate(rankings, start=1):
        hotspot['placement'] = placement
        hotspot['total_value'] = round(hotspot['total_value'], 2)
    return rankings


def build_dataset(killmails, names, now, *, current_member_ids):
    """Credit current WHPD members for kills made while affiliated with WHPD."""
    window_start = now - timedelta(seconds=WINDOW_SECONDS)
    unique_killmails = {}

    for killmail in killmails:
        killmail_time = parse_timestamp(killmail['killmail_time'])
        if not window_start <= killmail_time <= now:
            continue
        if killmail.get('zkb', {}).get('npc') is True:
            continue

        whpd_attackers = [
            attacker for attacker in killmail.get('attackers', [])
            if is_whpd_attacker(attacker) and attacker['character_id'] in current_member_ids
        ]
        victim = killmail.get('victim', {})
        if not whpd_attackers or not victim.get('character_id'):
            continue

        unique_killmails[int(killmail['killmail_id'])] = {**killmail, 'attackers': whpd_attackers}

    stats = {}

    arrests = []
    for killmail in sorted(unique_killmails.values(), key=lambda item: item['killmail_time'], reverse=True):
        victim = killmail['victim']
        total_value = float(killmail.get('zkb', {}).get('totalValue') or 0)
        arresting_officers = []

        for attacker in killmail.get('attackers', []):
            character_id = int(attacker['character_id'])
            officer = stats.setdefault(character_id, {
                'character_id': character_id,
                'name': names.get(character_id, f'Character {character_id}'),
                'arrests': 0,
                'final_blows': 0,
                'case_value': 0.0,
            })
            final_blow = bool(attacker.get('final_blow'))
            officer['arrests'] += 1
            officer['final_blows'] += int(final_blow)
            officer['case_value'] += total_value
            ship_type_id = int(attacker.get('ship_type_id') or 0)
            arresting_officers.append({
                'character_id': character_id,
                'name': officer['name'],
                'final_blow': final_blow,
                'damage_done': int(attacker.get('damage_done') or 0),
                'ship_type_id': ship_type_id,
                'ship_name': names.get(ship_type_id, f'Type {ship_type_id}') if ship_type_id else 'Unknown ship',
            })

        arresting_officers.sort(key=lambda officer: (not officer['final_blow'], officer['name'].lower()))
        victim_id = int(victim['character_id'])
        corporation_id = int(victim.get('corporation_id') or 0)
        ship_type_id = int(victim.get('ship_type_id') or 0)
        system_id = int(killmail['solar_system_id'])
        arrests.append({
            'killmail_id': int(killmail['killmail_id']),
            'time': killmail['killmail_time'],
            'system_id': system_id,
            'system_name': names.get(system_id, f'System {system_id}'),
            'total_value': round(total_value, 2),
            'points': int(killmail.get('zkb', {}).get('points') or 0),
            'victim': {
                'character_id': victim_id,
                'name': names.get(victim_id, f'Character {victim_id}'),
                'corporation_id': corporation_id,
                'corporation_name': names.get(corporation_id, f'Corporation {corporation_id}'),
                'ship_type_id': ship_type_id,
                'ship_name': names.get(ship_type_id, f'Type {ship_type_id}'),
            },
            'officers': arresting_officers,
        })

    rankings = sorted(
        stats.values(),
        key=lambda officer: (
            -officer['arrests'],
            -officer['final_blows'],
            -officer['case_value'],
            officer['name'].lower(),
            officer['character_id'],
        ),
    )
    for placement, officer in enumerate(rankings, start=1):
        officer['placement'] = placement
        officer['case_value'] = round(officer['case_value'], 2)

    return {
        'schema_version': 4,
        'generated_at': utc_timestamp(now),
        'window': {
            'start': utc_timestamp(window_start),
            'end': utc_timestamp(now),
            'seconds': WINDOW_SECONDS,
        },
        'source': {
            'name': 'zKillboard',
            'url': 'https://zkillboard.com/',
            'filter': 'kills/w-space/allianceID/pastSeconds/604800',
            'alliance_id': WHPD_ALLIANCE_ID,
            'membership': 'zKillboard character stats info',
        },
        'summary': {
            'arrests': len(arrests),
            'suspects': len({arrest['victim']['character_id'] for arrest in arrests}),
            'systems_protected': len({arrest['system_id'] for arrest in arrests}),
            'total_value': round(sum(arrest['total_value'] for arrest in arrests), 2),
        },
        'rankings': rankings,
        'dirtbags': build_dirtbag_rankings(arrests),
        'hotspots': build_hotspot_rankings(arrests),
        'arrests': arrests,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('data/arrests.json'))
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    killmails = fetch_alliance_kills()
    print(f'Fetched {len(killmails):,} W-space kills for WHPD alliance {WHPD_ALLIANCE_ID}')
    character_ids = {
        int(attacker['character_id'])
        for killmail in killmails
        for attacker in killmail.get('attackers', [])
        if is_whpd_attacker(attacker)
    }
    current_member_ids = fetch_current_member_ids(character_ids)
    print(f'Confirmed {len(current_member_ids):,} current WHPD members through zKillboard stats')
    names = resolve_names(collect_name_ids(killmails))
    dataset = build_dataset(killmails, names, now, current_member_ids=current_member_ids)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.output.with_suffix(args.output.suffix + '.tmp')
    with open(temporary_output, 'w', encoding='utf-8') as output_file:
        json.dump(dataset, output_file, indent=2, ensure_ascii=False)
        output_file.write('\n')
    temporary_output.replace(args.output)

    print(
        f'Wrote {dataset["summary"]["arrests"]:,} arrests and '
        f'{len(dataset["rankings"]):,} personnel rankings to {args.output}'
    )


if __name__ == '__main__':
    main()
