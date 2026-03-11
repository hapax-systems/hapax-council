"""Accommodation endpoints — confirm/disable accommodations."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/accommodations", tags=["accommodations"])


@router.post("/{accommodation_id}/confirm")
async def confirm_accommodation(accommodation_id: str):
    """Activate an accommodation."""
    import asyncio

    def _confirm():
        from cockpit.accommodations import load_accommodations, confirm_accommodation as _confirm_fn
        accom_set = load_accommodations()
        for a in accom_set.accommodations:
            if a.id == accommodation_id:
                _confirm_fn(accommodation_id)
                return {"status": "ok", "id": accommodation_id, "active": True}
        return None

    result = await asyncio.to_thread(_confirm)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Accommodation '{accommodation_id}' not found")
    return result


@router.post("/{accommodation_id}/disable")
async def disable_accommodation(accommodation_id: str):
    """Deactivate an accommodation."""
    import asyncio

    def _disable():
        from cockpit.accommodations import load_accommodations, disable_accommodation as _disable_fn
        accom_set = load_accommodations()
        for a in accom_set.accommodations:
            if a.id == accommodation_id:
                _disable_fn(accommodation_id)
                return {"status": "ok", "id": accommodation_id, "active": False}
        return None

    result = await asyncio.to_thread(_disable)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Accommodation '{accommodation_id}' not found")
    return result
