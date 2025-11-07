#!/usr/bin/env python3
"""Generate drop chance CSV reports from DropTable and DropPackageTable."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DROP_CHANCE_DIR = ROOT / "drop_chance"


def _load_json(filename: str) -> Dict:
    candidates = [ROOT / filename, ROOT / "ztable" / filename]
    for path in candidates:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
    raise FileNotFoundError(f"Could not find {filename} in repo root or ztable directory")


def _load_item_names() -> Dict[int, str]:
    try:
        raw_items = _load_json("ItemTable.json")
    except FileNotFoundError:
        return {}
    names: Dict[int, str] = {}
    for entry in raw_items.values():
        item_id = entry.get("Id")
        if item_id is None:
            continue
        name = entry.get("Name")
        if not isinstance(name, str) or not name:
            name = f"Item_{item_id}"
        names[int(item_id)] = name
    return names


def _aggregate_weights(
    contents: List[Iterable],
    weights: Optional[List[float]],
) -> Tuple[Dict[int, float], float]:
    per_item: Dict[int, float] = defaultdict(float)
    if weights is None:
        for entry in contents:
            item_id = int(entry[0])
            per_item[item_id] += 1.0
    else:
        for entry, weight in zip(contents, weights):
            item_id = int(entry[0])
            per_item[item_id] += float(weight)
    total_weight = sum(per_item.values())
    if total_weight <= 0 and per_item:
        # fallback to equal distribution if weights sum to zero
        equal_weight = 1.0
        for key in per_item:
            per_item[key] = equal_weight
        total_weight = equal_weight * len(per_item)
    return per_item, total_weight


def _normalise(values: Dict[int, float]) -> Dict[int, float]:
    total = sum(values.values())
    if total <= 0:
        length = len(values)
        if length == 0:
            return {}
        equal = 1.0 / length
        return {key: equal for key in values}
    return {key: (val / total) for key, val in values.items()}


def _extract_award_items(award_data: Dict) -> Dict[int, float]:
    contents = award_data.get("GroupContent") or []
    if not contents:
        return {}
    group_weight = award_data.get("GroupWeight") or []
    group_rates = award_data.get("GroupRates") or []
    weights: Optional[List[float]]
    if group_weight:
        weights = [float(w) for w in group_weight[: len(contents)]]
    elif group_rates:
        weights = [float(w) for w in group_rates[: len(contents)]]
    else:
        weights = None
    per_item, total_weight = _aggregate_weights(contents, weights)
    if not per_item:
        return {}
    return _normalise(per_item)


def _extract_pack_awards(pack_data: Dict) -> Tuple[Dict[int, int], Dict[int, float]]:
    pack_content = pack_data.get("PackContent") or []
    if not pack_content:
        return {}, {}
    group_weight = pack_data.get("GroupWeight") or []
    group_rates = pack_data.get("GroupRates") or []

    rolls_by_award: Dict[int, int] = defaultdict(int)
    weights_by_award: Dict[int, float] = defaultdict(float)

    use_weight = bool(group_weight)
    use_rates = bool(group_rates) and not use_weight

    for index, entry in enumerate(pack_content):
        if not entry:
            continue
        award_id = int(entry[0])
        max_count = entry[2] if len(entry) >= 3 else entry[-1]
        rolls_by_award[award_id] += int(max_count)
        if use_weight and index < len(group_weight):
            weights_by_award[award_id] += float(group_weight[index])
        elif use_rates and index < len(group_rates):
            weights_by_award[award_id] += float(group_rates[index])

    if use_weight or use_rates:
        probabilities = _normalise(weights_by_award)
    else:
        probabilities = {award_id: 1.0 for award_id in rolls_by_award}

    return dict(rolls_by_award), probabilities


def generate_reports() -> None:
    drop_table = _load_json("DropTable.json")
    drop_package_table = _load_json("DropPackageTable.json")
    item_names = _load_item_names()

    award_item_probabilities: Dict[int, Dict[int, float]] = {}
    for award_entry in drop_table.values():
        award_id = int(award_entry.get("AwardID"))
        award_item_probabilities[award_id] = _extract_award_items(award_entry)

    DROP_CHANCE_DIR.mkdir(parents=True, exist_ok=True)

    index_rows: List[List[str]] = []
    header = [
        "AwardID",
        "PackID",
        "ItemID",
        "ItemName",
        "Rolls",
        "InPoolProbability",
        "PackTriggerProbability",
        "FinalPerRunProbability",
    ]

    for pack_entry in drop_package_table.values():
        pack_id = int(pack_entry.get("PackID"))
        rolls_by_award, pack_probabilities = _extract_pack_awards(pack_entry)
        for award_id, rolls in rolls_by_award.items():
            items = award_item_probabilities.get(award_id)
            if not items:
                continue
            pack_trigger_prob = pack_probabilities.get(award_id, 1.0)
            for item_id, in_pool_prob in sorted(items.items()):
                final_prob = pack_trigger_prob * (1.0 - (1.0 - in_pool_prob) ** rolls)
                item_name = item_names.get(item_id, f"Item_{item_id}")
                row = [
                    str(award_id),
                    str(pack_id),
                    str(item_id),
                    item_name,
                    str(rolls),
                    f"{in_pool_prob:.6f}",
                    f"{pack_trigger_prob:.6f}",
                    f"{final_prob:.6f}",
                ]
                index_rows.append(row)

    # organise rows per award
    rows_by_award: Dict[int, List[List[str]]] = defaultdict(list)
    for row in index_rows:
        award_id = int(row[0])
        rows_by_award[award_id].append(row)

    for award_id, rows in rows_by_award.items():
        award_path = DROP_CHANCE_DIR / f"award_{award_id}.csv"
        rows_sorted = sorted(rows, key=lambda r: (int(r[1]), int(r[2])))
        with award_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(header)
            writer.writerows(rows_sorted)

    # Ensure empty awards create files with header only
    for award_id in award_item_probabilities.keys():
        if award_id not in rows_by_award:
            award_path = DROP_CHANCE_DIR / f"award_{award_id}.csv"
            with award_path.open("w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(header)

    index_path = DROP_CHANCE_DIR / "index.csv"
    index_sorted = sorted(index_rows, key=lambda r: (int(r[0]), int(r[1]), int(r[2])))
    with index_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(header)
        writer.writerows(index_sorted)


if __name__ == "__main__":
    generate_reports()
