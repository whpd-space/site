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
ZKILL_URL = 'https://zkillboard.com/api/kills/w-space/characterID/{character_id}/pastSeconds/604800/page/{page}/'
ESI_NAMES_URL = 'https://esi.evetech.net/latest/universe/names/?datasource=tranquility'
USER_AGENT = 'whpd.space zKill updater (https://whpd.space; https://github.com/whpd-space/site)'
MAX_ZKILL_PAGES = 5
ZKILL_PAGE_LIMIT = 1000


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


def fetch_officer_kills(character_id):
    """Fetch up to five pages of an officer's W-space kills from the last week."""
    kills = []
    seen_killmail_ids = set()

    for page in range(1, MAX_ZKILL_PAGES + 1):
        url = ZKILL_URL.format(character_id=character_id, page=page)
        result = request_json(url)
        if not isinstance(result, list):
            raise RuntimeError(f'zKillboard returned an unexpected response for character {character_id}')

        for killmail in result:
            killmail_id = int(killmail['killmail_id'])
            if killmail_id not in seen_killmail_ids:
                seen_killmail_ids.add(killmail_id)
                kills.append(killmail)

        # The documented API maximum is 1,000 records per request. A shorter
        # result means there is no next page to retrieve.
        if len(result) < ZKILL_PAGE_LIMIT:
            break
        if page == MAX_ZKILL_PAGES:
            raise RuntimeError(
                f'zKillboard results for character {character_id} exceed the safe pagination limit'
            )
        time.sleep(1)

    return kills


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


def collect_name_ids(killmails, officer_ids):
    """Collect every public entity ID needed to render the weekly blotter."""
    ids = set(officer_ids)
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
            if attacker.get('character_id') in officer_ids:
                ids.add(attacker.get('ship_type_id'))
    return {entity_id for entity_id in ids if entity_id}


def build_dirtbag_rankings(arrests, limit=25):
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


def build_dataset(officers, killmails, names, now):
    """Deduplicate killmails and calculate the arrest and personnel standings."""
    officer_by_id = {int(officer['character_id']): officer for officer in officers}
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
            if int(attacker.get('character_id') or 0) in officer_by_id
        ]
        victim = killmail.get('victim', {})
        if not whpd_attackers or not victim.get('character_id'):
            continue

        unique_killmails[int(killmail['killmail_id'])] = killmail

    stats = {
        character_id: {
            'character_id': character_id,
            'name': officer['name'],
            'rank': officer['rank'],
            'arrests': 0,
            'final_blows': 0,
            'case_value': 0.0,
            '_roster_order': roster_order,
        }
        for roster_order, (character_id, officer) in enumerate(officer_by_id.items())
    }

    arrests = []
    for killmail in sorted(unique_killmails.values(), key=lambda item: item['killmail_time'], reverse=True):
        victim = killmail['victim']
        total_value = float(killmail.get('zkb', {}).get('totalValue') or 0)
        arresting_officers = []

        for attacker in killmail.get('attackers', []):
            character_id = int(attacker.get('character_id') or 0)
            if character_id not in officer_by_id:
                continue

            officer = officer_by_id[character_id]
            final_blow = bool(attacker.get('final_blow'))
            stats[character_id]['arrests'] += 1
            stats[character_id]['final_blows'] += int(final_blow)
            stats[character_id]['case_value'] += total_value
            ship_type_id = int(attacker.get('ship_type_id') or 0)
            arresting_officers.append({
                'character_id': character_id,
                'name': officer['name'],
                'rank': officer['rank'],
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
            officer['_roster_order'],
        ),
    )
    for placement, officer in enumerate(rankings, start=1):
        officer['placement'] = placement
        officer['case_value'] = round(officer['case_value'], 2)
        del officer['_roster_order']

    return {
        'schema_version': 2,
        'generated_at': utc_timestamp(now),
        'window': {
            'start': utc_timestamp(window_start),
            'end': utc_timestamp(now),
            'seconds': WINDOW_SECONDS,
        },
        'source': {
            'name': 'zKillboard',
            'url': 'https://zkillboard.com/',
            'filter': 'kills/w-space/characterID/pastSeconds/604800',
        },
        'summary': {
            'arrests': len(arrests),
            'suspects': len({arrest['victim']['character_id'] for arrest in arrests}),
            'total_value': round(sum(arrest['total_value'] for arrest in arrests), 2),
        },
        'rankings': rankings,
        'dirtbags': build_dirtbag_rankings(arrests),
        'arrests': arrests,
    }


def load_officers(config_path):
    """Load and validate the configured WHPD personnel roster."""
    with open(config_path, 'r', encoding='utf-8') as config_file:
        officers = json.load(config_file)
    required_fields = {'character_id', 'name', 'rank'}
    if not officers or any(not required_fields.issubset(officer) for officer in officers):
        raise ValueError(f'{config_path} must contain a non-empty WHPD personnel roster')
    character_ids = [int(officer['character_id']) for officer in officers]
    if len(character_ids) != len(set(character_ids)):
        raise ValueError(f'{config_path} contains duplicate character IDs')
    return officers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('data/officers.json'))
    parser.add_argument('--output', type=Path, default=Path('data/arrests.json'))
    args = parser.parse_args()

    officers = load_officers(args.config)
    now = datetime.now(timezone.utc)
    raw_killmails = []

    for index, officer in enumerate(officers):
        character_id = int(officer['character_id'])
        officer_kills = fetch_officer_kills(character_id)
        raw_killmails.extend(officer_kills)
        print(f'Fetched {len(officer_kills):,} W-space kills for {officer["rank"]} {officer["name"]}')
        if index < len(officers) - 1:
            time.sleep(1)

    officer_ids = {int(officer['character_id']) for officer in officers}
    unique_killmails = {int(killmail['killmail_id']): killmail for killmail in raw_killmails}
    names = resolve_names(collect_name_ids(unique_killmails.values(), officer_ids))
    dataset = build_dataset(officers, unique_killmails.values(), names, now)

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
