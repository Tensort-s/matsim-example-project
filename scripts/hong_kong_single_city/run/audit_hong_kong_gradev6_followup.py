#!/usr/bin/env python3
"""Read-only GradeV6 diagnostics; write only into a new analysis1 audit directory.

Completes the CSV/TCS, road-log/storage, selected-pair and PT-event audit scope.
An audit finishing does not mean every gate passes or that a run is calibrated.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET


def stamp():
    return datetime.now(timezone.utc).astimezone().isoformat()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def quantiles(values):
    values = sorted(values)
    if not values:
        return {'n': 0, 'mean_min': None}
    return {'n': len(values), 'mean_min': sum(values) / len(values) / 60,
            **{f'p{p}_min': values[max(0, math.ceil(len(values) * p / 100) - 1)] / 60
               for p in (50, 90, 95)}}


def run_audit(audit):
    root = Path('/mnt/DiskI/by')
    assert root.resolve(strict=True) == root
    assert audit.resolve().parent == root
    assert audit.name == 'hk_stage11_candidate11_taxi_dvrp_20260906_gradev6_walk030_cap052_t32_audit1'
    run = root / audit.name.replace('_audit1', '_run1')
    oldrun = root / 'hk_stage11_candidate11_taxi_dvrp_20260905_gradev5_cap052_t32_run1'
    oldaudit = root / 'hk_stage11_candidate11_taxi_dvrp_20260905_gradev5_cap052_t32_audit1/results'
    out = audit / 'analysis1'
    out.mkdir(exist_ok=False)
    state = {'started_at': stamp(), 'status': 'WAITING_FOR_BASE_AUDIT', 'stages': []}

    def stage(name):
        state['status'] = name
        state['updated_at'] = stamp()
        dump(out / 'status.json', state)
        print(stamp(), name, flush=True)

    stage('WAITING_FOR_BASE_AUDIT')
    deadline = time.monotonic() + 3600
    while not (audit / 'exit_code.txt').exists():
        if time.monotonic() > deadline:
            raise RuntimeError('Base audit did not finish within one hour')
        time.sleep(10)
    assert (audit / 'exit_code.txt').read_text().strip() == '0', 'Base audit failed'
    assert (run / 'exit_code.txt').read_text().strip() == '0', 'Simulation failed'
    spec = importlib.util.spec_from_file_location('base_audit', audit / 'audit_hong_kong_tcs_boardings_population_groups.py')
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)

    def rows(path, delimiter=','):
        with base.text_stream(path) as stream:
            yield from csv.DictReader(stream, delimiter=delimiter)

    def table(path, data):
        if data:
            base.write_csv(path, list(data[0]), data)

    stage('IDENTITY_TCS_AND_VERSION_COMPARISON')
    summary = {'run': str(run), 'baseline': str(oldrun), 'iteration': 31,
               'scope': 'identity/TCS, completed trip times, Taxi censoring, road/storage/turns, selected household pairs, PT event waits',
               'limitations': ['Completed-trip means are conditional on completion and not matched-OD causal estimates.',
                   'MTR paid-area collapse is a proxy; TCS SPB and overnight visitor scopes differ from model.',
                   'No same-OD counterfactual routing or production adoption is included.',
                   'Audit execution completion does not imply zero traffic errors or calibration acceptance.']}
    comparison = []
    for r in rows(audit / 'results/tcs_boarding_share_comparison.csv'):
        old = next(x for x in rows(oldaudit / 'tcs_boarding_share_comparison.csv')
                   if (x['comparison_group'], x['category']) == (r['comparison_group'], r['category']))
        comparison.append({'group': r['comparison_group'], 'mode': r['category'],
            'gradev5_percent': float(old['modeled_share_percent']), 'gradev6_percent': float(r['modeled_share_percent']),
            'difference_pp': float(r['modeled_share_percent']) - float(old['modeled_share_percent']),
            'tcs_percent': float(r['tcs_share_percent'])})
    table(out / 'boarding_comparison.csv', comparison)
    times = []
    for group in ('resident_household', 'resident_collective', 'resident_other', 'visitor_overnight', 'visitor_same_day'):
        for scope, modes in [('mechanised', {'private_vehicle', 'pt', 'school_bus', 'taxi'}),
                             ('private_plus_taxi', {'private_vehicle', 'taxi'}), ('pt_plus_school_bus', {'pt', 'school_bus'})]:
            result = {'group': group, 'scope': scope}
            for version, source in [('gradev5', oldaudit), ('gradev6', audit / 'results')]:
                selected = [r for r in rows(source / 'main_trips_by_group_mode.csv')
                            if r['population_group'] == group and r['planned_main_mode'] in modes]
                n = sum(float(r['expanded_completed_main_trips']) for r in selected)
                result[version + '_mean_min'] = sum(float(r['mean_duration_min']) * float(r['expanded_completed_main_trips']) for r in selected) / n if n else None
            result['tcs_mean_min'] = ({'mechanised': 42, 'private_plus_taxi': 31, 'pt_plus_school_bus': 45}.get(scope)
                if group == 'resident_household' else 41 if group == 'visitor_overnight' and scope == 'mechanised' else None)
            times.append(result)
    table(out / 'identity_time_comparison.csv', times)
    summary['base_validation'] = json.loads((audit / 'results/validation.json').read_text(encoding='utf-8'))
    summary['identity_times'] = times
    state['stages'].append('identity_tcs')

    stage('TRIP_LEG_TAXI_AND_ROAD_SUMMARIES')
    def csv_metrics(current):
        it = current / 'output/ITERS/it.31'
        stats = defaultdict(lambda: [0, 0., 0.])
        for r in rows(it / '31.trips.csv.zst', ';'):
            t, w = base.parse_clock(r['trav_time']), base.parse_clock(r['wait_time'])
            assert t is not None and w is not None and t >= 0 and w >= 0
            for key in ['all', r['main_mode']] + (['mechanised'] if r['main_mode'] != 'walk' else []):
                x = stats[key]; x[0] += 1; x[1] += t; x[2] += w
        taxi_status = Counter(); completed_wait = []; waiting_lower_bound = []; rejected = []
        for r in rows(it / '31.taxi_request_audit.csv.gz'):
            if r['operational_only'].lower() == 'true':
                continue
            taxi_status[r['status']] += 1
            if r['status'] in ('completed', 'onboard'):
                completed_wait.append(float(r['wait_s']))
            elif r['status'] == 'waiting':
                waiting_lower_bound.append(max(0, float(r['horizon_s']) - float(r['submitted_s'])))
            elif r['status'] == 'rejected':
                rejected.append(r['request_id'])
        road = list(rows(it / '31.explicit_storage_capacity_audit.csv'))
        badflow = [r for r in road if not math.isclose(float(r['expected_flow_capacity_qsim_pcu_per_step']), float(r['actual_flow_capacity_qsim_pcu_per_step']), rel_tol=1e-8, abs_tol=1e-8)]
        badstorage = [r for r in road if not math.isclose(float(r['requested_storage_qsim_pcu']), float(r['actual_storage_qsim_pcu']), rel_tol=1e-8, abs_tol=1e-8)]
        turns = Counter(); inside_final = False; final_log = []; selections = []
        with (current / 'output/logfile.log').open(encoding='utf-8', errors='replace') as f:
            for line in f:
                if '### ITERATION 31 BEGINS' in line: inside_final = True
                if 'Household joint-plan selector:' in line: selections.append(line.strip())
                if inside_final:
                    if 'Cannot move vehicle ' in line:
                        m = re.search(r'from link (\S+) to link (\S+)', line)
                        if m: turns[m.group(1) + ' -> ' + m.group(2)] += 1
                    if 'SIMULATION (NEW QSim)' in line: final_log.append(line.strip())
                if '### ITERATION 31 ENDS' in line: inside_final = False
        return {'trip_stats': {k: {'n': v[0], 'mean_min': v[1]/v[0]/60, 'mean_wait_min': v[2]/v[0]/60} for k, v in stats.items()},
            'taxi_status_requests': dict(taxi_status), 'picked_up_request_wait': quantiles(completed_wait),
            'waiting_request_lower_bounds': quantiles(waiting_lower_bound), 'rejected_request_count': len(rejected),
            'taxi_censoring_note': 'Waiting requests are separate right-censored lower bounds; rejected requests have no fabricated horizon wait. No completed-only mean is labeled unconditional.',
            'blocked_inflow_seconds': sum(float(r['blocked_inflow_seconds']) for r in road),
            'blocked_links': sum(float(r['blocked_inflow_seconds']) > 0 for r in road),
            'flow_mismatch_count': len(badflow), 'storage_mismatch_count': len(badstorage),
            'top_blocked_links': sorted(road, key=lambda r: float(r['blocked_inflow_seconds']), reverse=True)[:30],
            'final_turn_warning_occurrences': sum(turns.values()), 'top_turn_pairs': turns.most_common(30),
            'turn_note': 'Warning occurrences are not unique stuck vehicles, and this report does not repair network topology.',
            'final_qsim_log': final_log[-1:] , 'joint_selection_log': selections}
    summary['versions'] = {'gradev5': csv_metrics(oldrun), 'gradev6': csv_metrics(run)}
    dump(out / 'csv_road_taxi_comparison.json', summary['versions'])
    state['stages'].append('trip_taxi_road')

    stage('SELECTED_HOUSEHOLD_PAIR_VALIDATION')
    meta = json.loads((run / 'run_metadata.json').read_text(encoding='utf-8'))
    release = Path(meta['release_root'])
    assert release.resolve().is_relative_to(root)
    catalog = {r['candidate_id']: r for r in rows(release / 'input/household_joint_plan_potential_candidates.csv')}
    pairs = defaultdict(lambda: defaultdict(set)); vehicles = defaultdict(set); population = set(); errors = []
    with base.binary_stream(run / 'output/output_plans.xml.zst') as f:
        for _, person in ET.iterparse(f, events=('end',)):
            if person.tag != 'person': continue
            pid = person.attrib['id']; population.add(pid)
            plans = [p for p in person.findall('plan') if p.get('selected') == 'yes']
            if len(plans) != 1:
                errors.append({'person': pid, 'reason': 'selected_plan_count', 'count': len(plans)})
            for plan in plans:
                for leg in plan.findall('leg'):
                    attrs = base.element_attributes(leg)
                    cid = attrs.get('hkHouseholdJointCandidateId')
                    if not cid: continue
                    pairs[cid][pid].add(leg.get('mode', ''))
                    vehicle = attrs.get('hkHouseholdJointVehicleId')
                    if vehicle: vehicles[cid].add(vehicle)
            person.clear()
    valid = Counter(); demand = Counter()
    for cid, people in pairs.items():
        c = catalog.get(cid)
        if c is None:
            errors.append({'candidate': cid, 'reason': 'unknown_candidate'}); continue
        driver, passenger = c['driver_person_id'], c['passenger_person_id']
        if set(people) != {driver, passenger} or 'car' not in people.get(driver, set()) or 'car_passenger' not in people.get(passenger, set()):
            errors.append({'candidate': cid, 'reason': 'incorrect_pair_or_mode', 'persons': {p: sorted(m) for p, m in people.items()}})
        else: valid[c['candidate_type']] += 1
        if len(vehicles[cid]) > 1: errors.append({'candidate': cid, 'reason': 'conflicting_bound_vehicle_ids'})
        demand[c['passenger_demand_key']] += 1
    duplicates = {k: n for k, n in demand.items() if n > 1}
    pairing = {'selected_candidate_count': len(pairs), 'valid_pairs_by_type': dict(valid),
        'error_count': len(errors), 'errors': errors, 'duplicate_passenger_demands': duplicates,
        'note': 'Exact catalog driver/passenger identities and selected-leg modes checked. No claim of complete vehicle occupancy/spacetime continuity validation.'}
    dump(out / 'household_pairing.json', pairing)
    summary['household_pairing'] = pairing
    state['stages'].append('household_pairing')

    stage('PT_EVENT_WAIT_AND_STUCK_AUDIT')
    transit, _ = base.parse_transit_vehicle_modes(run / 'output/output_transitSchedule.xml.zst')
    types, _ = base.parse_transit_vehicle_types(run / 'output/output_transitVehicles.xml.zst')
    private, _ = base.parse_private_vehicle_modes(run / 'output/output_vehicles.xml.zst')
    active = {}; completed = defaultdict(list); censored = []; anomalies = Counter(); stuck = Counter(); stuck_links = Counter()
    boarding_modes = Counter(); horizon = 108000.0
    wanted = {b'departure', b'arrival', b'PersonEntersVehicle', b'PersonEntersPtVehicle', b'PersonLeavesVehicle', b'stuckAndAbort'}
    with base.binary_stream(run / 'output/ITERS/it.31/31.events.xml.zst') as f:
        for line in f:
            kind = base.byte_attribute(line, b'type')
            if kind not in wanted: continue
            a = ET.fromstring(line).attrib
            pid = a.get('person', ''); t = float(a['time']); mode = a.get('legMode', a.get('mode', ''))
            if kind == b'stuckAndAbort':
                residency = 'population' if pid in population else 'nonpopulation'
                stuck[residency + '|' + mode] += 1; stuck_links[a.get('link', '')] += 1
            if pid not in population: continue
            if kind == b'departure' and mode == 'pt':
                if pid in active: anomalies['overlapping_pt_departure'] += 1
                active[pid] = {'dep': t, 'board': None, 'alight': None, 'vehicle': None, 'mode': 'unknown_before_boarding'}
            elif pid in active:
                x = active[pid]
                if kind in (b'PersonEntersVehicle', b'PersonEntersPtVehicle'):
                    if x['board'] is not None:
                        anomalies['duplicate_or_multiple_boarding_in_pt_leg'] += 1; continue
                    x['board'] = t; x['vehicle'] = a.get('vehicle', '')
                    x['mode'] = base.classify_vehicle(x['vehicle'], transit, types, private) or 'unknown_vehicle'
                    boarding_modes[x['mode']] += 1
                elif kind == b'PersonLeavesVehicle':
                    if a.get('vehicle') == x['vehicle']: x['alight'] = t
                elif kind == b'arrival' and mode == 'pt':
                    if x['board'] is None: anomalies['pt_arrival_without_boarding'] += 1
                    else:
                        wait = x['board'] - x['dep']
                        if wait < 0: anomalies['negative_wait'] += 1
                        else: completed[x['mode']].append(wait)
                    del active[pid]
                elif kind == b'stuckAndAbort':
                    end = 'waiting' if x['board'] is None else 'aboard' if x['alight'] is None else 'after_alighting'
                    censored.append({'person': pid, 'state': end, 'mode': x['mode'], 'end_s': t,
                        'observed_wait_s': max(0, (x['board'] if x['board'] is not None else t) - x['dep'])})
                    del active[pid]
    for pid, x in active.items():
        end = 'waiting' if x['board'] is None else 'aboard' if x['alight'] is None else 'after_alighting'
        censored.append({'person': pid, 'state': end, 'mode': x['mode'], 'end_s': horizon,
            'observed_wait_s': max(0, (x['board'] if x['board'] is not None else horizon) - x['dep'])})
    event_result = {'completed_pt_leg_wait_by_boarded_mode': {k: quantiles(v) for k, v in completed.items()},
        'censored_pt_legs_by_state': dict(Counter(x['state'] for x in censored)),
        'censored_pt_legs': len(censored), 'stuck_events_by_population_and_mode': dict(stuck),
        'top_stuck_links': stuck_links.most_common(30), 'anomalies': dict(anomalies),
        'boarding_modes_for_pt_departures': dict(boarding_modes),
        'limitations': ['Unboarded PT legs cannot be assigned a realised transit submode.',
            'Stuck/end-of-day waits are censored observations, not completed waits.',
            'No explicit denial event is inferred from a long wait; headway vs denial cause remains unresolved.',
            'Event-leg waiting and trips.csv waiting use different reporting boundaries; exact cross-writer reconciliation is not asserted.']}
    table(out / 'pt_censored_legs.csv', censored)
    dump(out / 'pt_event_audit.json', event_result)
    summary['pt_event_audit'] = event_result
    state['stages'].append('pt_events')

    issues = []
    if errors or duplicates: issues.append('Selected household pairing requires review')
    if anomalies: issues.append('PT event-state anomalies require review')
    if censored: issues.append('PT legs remain unfinished/censored')
    if stuck: issues.append('Final iteration contains stuck events')
    for name, values in summary['versions'].items():
        if values['flow_mismatch_count'] or values['storage_mismatch_count']: issues.append(name + ': capacity mismatch')
    summary['issues_for_review'] = issues
    summary['completed_at'] = stamp()
    summary['audit_execution_status'] = 'COMPLETED_WITH_FINDINGS' if issues else 'COMPLETED'
    dump(out / 'summary.json', summary)
    (out / 'README.md').write_text('# GradeV6 full-scope audit results\n\n'
        + 'Audit execution: ' + summary['audit_execution_status'] + '\n\n'
        + 'Completed: ' + summary['completed_at'] + '\n\n'
        + 'Base identity/boarding/completion results: ../results/.\n'
        + 'TCS comparison: boarding_comparison.csv and identity_time_comparison.csv.\n'
        + 'Road/Taxi/actual trip comparison: csv_road_taxi_comparison.json.\n'
        + 'Selected pairs: household_pairing.json. PT events/censoring: pt_event_audit.json and pt_censored_legs.csv.\n\n'
        + 'Findings requiring review:\n' + ''.join('- ' + x + '\n' for x in issues)
        + '\nKnown limitations are explicit in summary.json and the component results. '
        + 'Completion of this audit does not establish production readiness, causality, or zero defects.\n', encoding='utf-8')
    stage(summary['audit_execution_status'])
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--audit-root', type=Path, required=True)
    args = parser.parse_args()
    run_audit(args.audit_root)
