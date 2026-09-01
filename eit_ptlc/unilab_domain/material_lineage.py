"""Pure identity-preserving lineage joins used by typed workflows."""

from __future__ import annotations

from typing import Any


def record_spotting(sample_vial: object, plate: object) -> dict[str, Any]:
    return {"sample_vial": sample_vial, "plate": plate, "stage": "spotted"}


def record_scraping(plate: object, powder_collector: object) -> dict[str, Any]:
    return {
        "plate": plate,
        "powder_collector": powder_collector,
        "stage": "scraped",
    }


def record_collection(powder_collector: object, vial: object) -> dict[str, Any]:
    return {"powder_collector": powder_collector, "vial": vial, "stage": "collected"}


__all__ = ["record_collection", "record_scraping", "record_spotting"]
