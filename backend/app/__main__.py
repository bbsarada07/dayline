"""Run the server: `python -m app` (listens on 0.0.0.0 so phones on the LAN can connect)."""

import uvicorn

from app.config import settings

if __name__ == "__main__":
    # Hosts like Render terminate HTTPS in front of the app; trust their forwarded headers.
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, proxy_headers=True, forwarded_allow_ips="*")
