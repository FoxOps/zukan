from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser
from app.services.app_release import AndroidRelease, latest_android

router = APIRouter(prefix="/app", tags=["app"])


@router.get("/android")
async def android_release(_: CurrentUser) -> AndroidRelease:
    """Latest Android app (GitHub release): web download link and the app's update check."""
    release = await latest_android()
    if release is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Android release available")
    return release
